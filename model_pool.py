"""Multi-Model Rotation & Quota Management Subsystem for Akira.

Provides resilient free-tier LLM execution across verified >=27B and compound class
models on Groq.

Note on providers:
- Cerebras was removed from the free-tier pool as of July 2026 after replacing its free tier
  with a card-gated free trial ($5 expiring in 30 days).
- NVIDIA NIM, Cloudflare Workers AI, and OpenRouter are excluded to ensure 100% verified,
  card-free operation solely on Groq.

Design principles:
1. Model Quality Tiering: Prioritizes high-capability reasoning models (e.g. gpt-oss-120b,
   qwen3.8-27b) over smaller/standard compound models (compound-mini) when available.
2. 5-Task Session Batch Pinning: Pins one selected model for up to 5 consecutive turns
   within a conversational session to maintain reasoning and tone continuity. Rotates after
   5 tasks, with immediate failover on 429 or transport error.
3. Request-Level Burst Smoothing: Sliding-window RPM smoothing spreads load across models.
4. Live Header Quota Tracking: Dynamically updates remaining requests from response headers.
5. Instant 429 Failover: Immediate retry against the next model in the pool on HTTP 429.
"""

from __future__ import annotations

import collections
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
import llm_json

# ── Duration & Reset Header Parsing ──────────────────────────────────────────


def parse_reset_seconds(val: Any) -> float | None:
    """Parse various rate limit reset string/number formats into seconds.
    
    Examples:
        '4m19.2s' -> 259.2
        '52.86s'  -> 52.86
        '10m4.8s' -> 604.8
        '15'      -> 15.0
        '1h30m'   -> 5400.0
        '250ms'   -> 0.25
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    s = str(val).strip()
    if not s:
        return None
    try:
        return max(0.0, float(s))
    except ValueError:
        pass

    pattern = (
        r'^(?:(?P<hours>\d+(?:\.\d+)?)\s*h(?:ours?)?)?\s*'
        r'(?:(?P<minutes>\d+(?:\.\d+)?)\s*m(?:in(?:ute)?s?)?)?\s*'
        r'(?:(?P<seconds>\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?)?\s*'
        r'(?:(?P<ms>\d+(?:\.\d+)?)\s*ms)?$'
    )
    m = re.match(pattern, s, re.IGNORECASE)
    if m and any(m.groupdict().values()):
        d = m.groupdict()
        h = float(d.get("hours") or 0)
        mins = float(d.get("minutes") or 0)
        sec = float(d.get("seconds") or 0)
        ms = float(d.get("ms") or 0)
        return max(0.0, h * 3600.0 + mins * 60.0 + sec + ms / 1000.0)

    # Fallback search for numbers in case header is phrased e.g. "try again in 12.5s"
    search_m = re.search(r'(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|ms)?', s, re.IGNORECASE)
    if search_m:
        num = float(search_m.group(1))
        unit = (search_m.group(2) or "s").lower()
        if unit.startswith("h"):
            return num * 3600.0
        elif unit.startswith("m") and not unit.startswith("ms"):
            return num * 60.0
        elif unit == "ms":
            return num / 1000.0
        return num
    return None


# ── Endpoint & Runtime State ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelEndpoint:
    """Definition of a free-tier LLM model endpoint."""
    provider: str        # 'groq'
    model_id: str        # e.g. 'openai/gpt-oss-120b', 'qwen/qwen3.8-27b'
    param_class: str     # '27B', '120B', 'compound'
    rpm_limit: int       # Requests per minute ceiling
    rpd_limit: int       # Requests per day ceiling
    key_env: str         # Environment variable name containing API key
    base_url: str        # Base URL for OpenAI-compatible endpoint
    quality_tier: str = "high"  # 'high' vs 'standard'
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.provider}/{self.model_id}"

    @property
    def is_available(self) -> bool:
        key = (os.environ.get(self.key_env) or "").strip()
        if not key:
            return False
        if "{account_id}" in self.base_url:
            acc_id = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
            if not acc_id:
                return False
        return True

    def get_headers(self) -> dict[str, str]:
        key = (os.environ.get(self.key_env) or "").strip()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        return headers

    def get_url(self) -> str:
        url = self.base_url
        if "{account_id}" in url:
            acc_id = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
            url = url.replace("{account_id}", acc_id)
        return f"{url.rstrip('/')}/chat/completions"


@dataclass
class ModelRuntimeState:
    """Dynamic, in-memory tracking of model quota, rate limits, and burst usage."""
    endpoint: ModelEndpoint
    recent_calls: collections.deque = field(default_factory=collections.deque)  # monotonic timestamps
    last_used_time: float = 0.0
    backoff_until: float = 0.0          # monotonic timestamp when 429 expires
    live_remaining_rpm: int | None = None
    live_remaining_rpd: int | None = None
    live_reset_seconds: float | None = None
    total_calls: int = 0
    total_429s: int = 0

    def clean_recent_calls(self, now: float) -> None:
        """Discard call timestamps older than 60 seconds (sliding window)."""
        cutoff = now - 60.0
        while self.recent_calls and self.recent_calls[0] < cutoff:
            self.recent_calls.popleft()

    @property
    def current_rpm_load(self) -> int:
        now = time.monotonic()
        self.clean_recent_calls(now)
        return len(self.recent_calls)

    @property
    def rpm_utilization_ratio(self) -> float:
        if self.endpoint.rpm_limit <= 0:
            return 0.0
        return self.current_rpm_load / float(self.endpoint.rpm_limit)

    def is_in_backoff(self, now: float) -> bool:
        return self.backoff_until > now

    def mark_used(self, now: float) -> None:
        self.clean_recent_calls(now)
        self.recent_calls.append(now)
        self.last_used_time = now
        self.total_calls += 1

    def record_429(self, backoff_seconds: float, now: float) -> None:
        self.total_429s += 1
        self.backoff_until = max(self.backoff_until, now + max(2.0, backoff_seconds))

    def update_from_headers(self, headers: dict[str, str], now: float) -> None:
        """Update live quota estimates from HTTP response headers."""
        h_lower = {k.lower(): v for k, v in headers.items()}

        # Remaining requests
        rem_req = (
            h_lower.get("x-ratelimit-remaining-requests") or
            h_lower.get("x-ratelimit-remaining-requests-minute") or
            h_lower.get("x-ratelimit-remaining")
        )
        if rem_req is not None:
            try:
                self.live_remaining_rpm = int(rem_req)
            except ValueError:
                pass

        # Daily remaining requests
        rem_day = h_lower.get("x-ratelimit-remaining-requests-day")
        if rem_day is not None:
            try:
                self.live_remaining_rpd = int(rem_day)
            except ValueError:
                pass

        # Reset times
        reset_val = (
            h_lower.get("x-ratelimit-reset-requests") or
            h_lower.get("x-ratelimit-reset-requests-minute") or
            h_lower.get("x-ratelimit-reset") or
            h_lower.get("retry-after")
        )
        parsed_reset = parse_reset_seconds(reset_val)
        if parsed_reset is not None:
            self.live_reset_seconds = parsed_reset


@dataclass
class ModelCallResult:
    """Standardized response from any provider in the pool."""
    text: str
    parsed: dict | None
    provider: str
    model: str
    elapsed_ms: float
    status_code: int = 200
    retries_made: int = 0


class PoolExhaustedError(RuntimeError):
    """Raised when all eligible models in the pool are temporarily rate-limited."""
    def __init__(self, retry_after: float, message: str | None = None):
        self.retry_after = retry_after
        msg = message or f"All free models are rate-limited. Retry after {retry_after:.1f}s"
        super().__init__(msg)


# ── Canonical Candidate Pool (Groq Free Tier Only) ───────────────────────────
# All candidate models verified live against Groq /v1/models and chat endpoint.
# Models are partitioned into High and Standard quality tiers.

DEFAULT_MODELS: list[ModelEndpoint] = [
    # ── High Quality Tier: Superior reasoning, instruction following, and schema precision
    ModelEndpoint(
        provider="groq",
        model_id="openai/gpt-oss-120b",
        param_class="120B",
        rpm_limit=30,
        rpd_limit=1000,
        key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        quality_tier="high",
    ),
    ModelEndpoint(
        provider="groq",
        model_id="qwen/qwen3.8-27b",
        param_class="27B",
        rpm_limit=30,
        rpd_limit=1000,
        key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        quality_tier="high",
    ),
    ModelEndpoint(
        provider="groq",
        model_id="qwen/qwen3.6-27b",
        param_class="27B",
        rpm_limit=30,
        rpd_limit=1000,
        key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        quality_tier="high",
    ),

    # ── Standard Quality Tier: Fast compound/mini models for secondary or fallback execution
    ModelEndpoint(
        provider="groq",
        model_id="groq/compound",
        param_class="compound",
        rpm_limit=30,
        rpd_limit=1000,
        key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        quality_tier="standard",
    ),
    ModelEndpoint(
        provider="groq",
        model_id="groq/compound-mini",
        param_class="compound",
        rpm_limit=30,
        rpd_limit=1000,
        key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        quality_tier="standard",
    ),
]



# ── Model Pool Manager ────────────────────────────────────────────────────────

class ModelPoolManager:
    """Manages multi-model selection, rotation, quality tiering, and session pinning."""

    def __init__(self, endpoints: list[ModelEndpoint] | None = None):
        self._endpoints = list(endpoints or DEFAULT_MODELS)
        self._lock = threading.Lock()
        self._states: dict[str, ModelRuntimeState] = {
            ep.full_name: ModelRuntimeState(endpoint=ep)
            for ep in self._endpoints
        }
        self._round_robin_counter = 0
        self._session_pins: dict[str, dict] = {}  # session_id -> {"endpoint": ModelEndpoint, "turns_used": int}

    @property
    def registered_endpoints(self) -> list[ModelEndpoint]:
        return list(self._endpoints)

    def add_endpoint(self, endpoint: ModelEndpoint) -> None:
        with self._lock:
            if endpoint.full_name not in self._states:
                self._endpoints.append(endpoint)
                self._states[endpoint.full_name] = ModelRuntimeState(endpoint=endpoint)

    def get_state(self, endpoint: ModelEndpoint) -> ModelRuntimeState:
        with self._lock:
            if endpoint.full_name not in self._states:
                self._states[endpoint.full_name] = ModelRuntimeState(endpoint=endpoint)
            return self._states[endpoint.full_name]

    def get_available_endpoints(self) -> list[ModelEndpoint]:
        """Return all endpoints whose API keys are set in the environment."""
        env_groq_model = (os.environ.get("GROQ_MODEL") or "").strip()
        available = [ep for ep in self._endpoints if ep.is_available]

        # If user explicitly set GROQ_MODEL, ensure it is prioritized within Groq models
        if env_groq_model:
            def _sort_key(ep: ModelEndpoint):
                if ep.provider == "groq" and ep.model_id == env_groq_model:
                    return (0, ep.rpd_limit)
                return (1, ep.rpd_limit)
            available.sort(key=_sort_key)
        return available

    def reset_session_pin(self, session_id: str | None) -> None:
        """Reset the pinned model for a session (e.g. on session end or timeout)."""
        if not session_id:
            return
        with self._lock:
            self._session_pins.pop(session_id, None)

    def get_session_pin(self, session_id: str | None) -> dict | None:
        """Retrieve the current pin dictionary for a session, if any."""
        if not session_id:
            return None
        with self._lock:
            pin = self._session_pins.get(session_id)
            if pin is None:
                return None
            return dict(pin)

    def unpin_session_model(self, session_id: str | None) -> None:
        """Immediately unpin a session model (e.g. after hitting 429 or transport error)."""
        self.reset_session_pin(session_id)

    def select_next_model(
        self,
        exclude_names: set[str] | None = None,
        session_id: str | None = None,
    ) -> ModelEndpoint | None:
        """Select the next optimal model from the pool using:
        
        1. 5-Task Session Pinning: If a session_id is provided, reuses the pinned model
           for up to 5 consecutive turns to maintain reasoning and conversational continuity.
           Immediately unpins/fails over if the pinned model is in 429 backoff or rate-limited.
        2. Quality-Tier Prioritization: High quality tier models (e.g. gpt-oss-120b, qwen3.8-27b)
           are heavily prioritized (+20.0 bonus) over standard models (compound-mini) whenever
           they are available (not rate-limited or in backoff).
        3. Exclusion of models currently in 429 backoff or at/near RPM limits.
        4. Recency / Burst Penalty: models used within the last 3.0s yield to idle models during bursts.
        5. Fair Round-Robin rotation among candidates with equivalent availability.
        """
        exclude = set(exclude_names or ())
        now = time.monotonic()

        with self._lock:
            # ── 1. Check 5-Task Session Pinning ──────────────────────────────
            if session_id:
                pin = self._session_pins.get(session_id)
                if pin is not None:
                    pinned_ep: ModelEndpoint = pin["endpoint"]
                    pinned_state = self._states.get(pinned_ep.full_name)
                    # Check if pinned model is healthy, not excluded, not in backoff, and below RPM limit
                    is_healthy = (
                        pinned_ep.full_name not in exclude
                        and pinned_state is not None
                        and not pinned_state.is_in_backoff(now)
                        and pinned_state.current_rpm_load < pinned_ep.rpm_limit
                        and (pinned_state.live_remaining_rpm is None or pinned_state.live_remaining_rpm > 0)
                    )
                    if is_healthy:
                        if pin["turns_used"] < 5:
                            pin["turns_used"] += 1
                            return pinned_ep
                        else:
                            # 5-task batch limit reached -> rotate to next model for next batch
                            self._session_pins.pop(session_id, None)
                            exclude.add(pinned_ep.full_name)
                    else:
                        # Pinned model hit error, backoff, or capacity limit -> fail over mid-batch
                        self._session_pins.pop(session_id, None)

            # ── 2. Candidate Selection ───────────────────────────────────────
            candidates = [
                ep for ep in self.get_available_endpoints()
                if ep.full_name not in exclude
            ]
            if not candidates:
                # If everything was excluded due to batch-rotation exclusion, fall back to base exclude
                if exclude != (exclude_names or set()):
                    candidates = [
                        ep for ep in self.get_available_endpoints()
                        if ep.full_name not in (exclude_names or set())
                    ]
                if not candidates:
                    return None

            # Filter out models currently in active 429 backoff
            non_backed_off: list[tuple[ModelEndpoint, ModelRuntimeState]] = []
            for ep in candidates:
                state = self._states[ep.full_name]
                if not state.is_in_backoff(now):
                    state.clean_recent_calls(now)
                    non_backed_off.append((ep, state))

            if not non_backed_off:
                return None

            def _score(item: tuple[ModelEndpoint, ModelRuntimeState]) -> float:
                _ep, _st = item
                rpm_load = len(_st.recent_calls)
                if rpm_load >= _ep.rpm_limit or _st.live_remaining_rpm == 0:
                    return -1000.0 - rpm_load

                # Quality Tier Priority Bonus (+12.0 for high quality models)
                quality_bonus = 12.0 if getattr(_ep, "quality_tier", "standard") == "high" else 0.0

                # Daily quota priority bonus
                if _ep.rpd_limit >= 10000:
                    daily_bonus = 6.0
                elif _ep.rpd_limit >= 1000:
                    daily_bonus = 2.0
                else:
                    daily_bonus = 0.5

                time_since = now - _st.last_used_time
                burst_penalty = -25.0 * (1.0 - (time_since / 3.0)) if time_since < 3.0 else 0.0
                load_ratio = (rpm_load / float(_ep.rpm_limit))
                load_penalty = load_ratio * 40.0 + (load_ratio ** 2) * 35.0
                idle_bonus = min(5.0, time_since * 0.1)

                return quality_bonus + daily_bonus + burst_penalty - load_penalty + idle_bonus

            scored = sorted(non_backed_off, key=_score, reverse=True)
            top_score = _score(scored[0])

            # Group candidates with approximately equal scores for round-robin rotation
            top_candidates = [
                item for item in scored
                if abs(_score(item) - top_score) < 0.5
            ]

            selected_item = top_candidates[self._round_robin_counter % len(top_candidates)]
            self._round_robin_counter += 1
            selected_ep = selected_item[0]

            # If session_id was provided, pin this newly selected model as turn 1
            if session_id:
                self._session_pins[session_id] = {
                    "endpoint": selected_ep,
                    "turns_used": 1,
                }

            return selected_ep


    def get_pool_exhaustion_wait(self) -> float:
        """Compute the minimum time (in seconds) until at least one model cools down."""
        now = time.monotonic()
        available = self.get_available_endpoints()
        if not available:
            return 30.0

        with self._lock:
            waits = []
            for ep in available:
                st = self._states.get(ep.full_name)
                if st and st.is_in_backoff(now):
                    waits.append(st.backoff_until - now)
                elif st and st.recent_calls:
                    # Time until oldest call in sliding 60s window expires
                    oldest = st.recent_calls[0]
                    waits.append(max(0.1, (oldest + 60.0) - now))
                else:
                    return 0.1
            return min(waits) if waits else 5.0

    def call_model(
        self,
        messages: list[dict],
        system: str | None = None,
        json_mode: bool = True,
        timeout: float = 10.0,
        max_tokens: int | None = None,
        preferred_provider: str | None = None,
        session_id: str | None = None,
        on_attempt: Callable[[ModelEndpoint], None] | None = None,
    ) -> ModelCallResult:
        """Call the optimal model from the pool with automatic failover on 429 / transport errors.
        
        Raises:
            PoolExhaustedError: If all models in the pool are rate-limited.
            RuntimeError: If all eligible providers fail or no models are configured.
        """
        tried_names: set[str] = set()
        retries = 0
        last_error: Exception | None = None

        # OpenAI-compatible strict JSON schema requirement: prompt must contain the word 'json'
        if json_mode:
            has_json = any(
                "json" in (m.get("content") or "").lower() for m in messages
            ) or (system and "json" in system.lower())
            if not has_json:
                json_hint = "Respond strictly with valid JSON."
                if system:
                    system = f"{system}\n{json_hint}"
                else:
                    system = json_hint

        while True:
            endpoint = self.select_next_model(exclude_names=tried_names, session_id=session_id)
            now = time.monotonic()

            if endpoint is None:
                # No more unexhausted models available right now
                wait_time = self.get_pool_exhaustion_wait()
                if tried_names or self.get_available_endpoints():
                    raise PoolExhaustedError(
                        retry_after=wait_time,
                        message=f"All free model rate limits are temporarily busy across available models. Please wait {wait_time:.1f}s."
                    )
                raise RuntimeError("No free tier models configured with active API keys.")

            tried_names.add(endpoint.full_name)
            if on_attempt:
                on_attempt(endpoint)

            state = self.get_state(endpoint)
            state.mark_used(now)

            # Assemble payload
            body_messages = []
            if system:
                body_messages.append({"role": "system", "content": system})
            body_messages.extend(messages)

            payload: dict[str, Any] = {
                "model": endpoint.model_id,
                "messages": body_messages,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            if max_tokens:
                payload["max_tokens"] = max_tokens

            url = endpoint.get_url()
            headers = endpoint.get_headers()

            start_t = time.monotonic()
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
                elapsed_ms = (time.monotonic() - start_t) * 1000.0

                # Live header tracking
                state.update_from_headers(dict(resp.headers), time.monotonic())

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices") or []
                    if not choices:
                        raise RuntimeError(f"Empty choices from {endpoint.full_name}")
                    raw_text = (choices[0].get("message", {}).get("content") or "").strip()

                    # Clean reasoning / thinking blocks (<think>...</think>)
                    clean_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
                    # Clean safety headers
                    clean_text = re.sub(r"^(User Safety:\s*\w+|\[Safety\]:\s*\w+)\s*", "", clean_text, flags=re.I).strip()

                    parsed_obj = None
                    if json_mode:
                        parsed_obj, _ = llm_json.parse(clean_text or raw_text)

                    return ModelCallResult(
                        text=clean_text or raw_text,
                        parsed=parsed_obj,
                        provider=endpoint.provider,
                        model=endpoint.model_id,
                        elapsed_ms=elapsed_ms,
                        status_code=200,
                        retries_made=retries,
                    )

                elif resp.status_code == 429:
                    # Unpin immediately on 429 so failover selects next model
                    self.unpin_session_model(session_id)
                    backoff = parse_reset_seconds(
                        resp.headers.get("retry-after") or
                        resp.headers.get("x-ratelimit-reset-requests") or
                        resp.headers.get("x-ratelimit-reset-requests-minute") or
                        15.0
                    ) or 15.0
                    state.record_429(backoff, time.monotonic())
                    retries += 1
                    print(f"[model_pool] 429 on {endpoint.full_name} (cooling {backoff:.1f}s). Failing over to next model...")
                    continue

                elif resp.status_code == 404:
                    self.unpin_session_model(session_id)
                    state.record_429(3600.0, time.monotonic())
                    retries += 1
                    print(f"[model_pool] 404 Model Not Found for {endpoint.full_name}. Bypassing...")
                    continue

                else:
                    self.unpin_session_model(session_id)
                    print(f"[model_pool] HTTP {resp.status_code} from {endpoint.full_name}: {resp.text[:120]}")
                    state.record_429(5.0, time.monotonic())
                    retries += 1
                    continue

            except requests.exceptions.RequestException as e:
                self.unpin_session_model(session_id)
                last_error = e
                print(f"[model_pool] Transport error on {endpoint.full_name}: {e!r}. Failing over...")
                state.record_429(5.0, time.monotonic())
                retries += 1
                continue

    def call_json(
        self,
        system: str,
        user: str,
        timeout: float = 10.0,
        max_tokens: int = 400,
        session_id: str | None = None,
        label: str = "",
    ) -> tuple[dict, dict]:
        """Drop-in JSON completion interface compatible with servant_clients.call_json."""
        messages = [{"role": "user", "content": user}]
        result = self.call_model(
            messages=messages,
            system=system,
            json_mode=True,
            timeout=timeout,
            max_tokens=max_tokens,
            session_id=session_id,
        )
        if result.parsed is not None:
            return result.parsed, {"status": "repaired", "provider": result.provider, "model": result.model}

        # Attempt recovery via llm_json parse
        parsed, info = llm_json.parse(result.text)
        if parsed is not None:
            return parsed, info
        raise RuntimeError(f"Unparseable JSON from {result.provider}/{result.model}: {result.text[:200]}")



# Global Singleton Instance
_GLOBAL_POOL: ModelPoolManager | None = None
_GLOBAL_POOL_LOCK = threading.Lock()

def get_pool() -> ModelPoolManager:
    global _GLOBAL_POOL
    with _GLOBAL_POOL_LOCK:
        if _GLOBAL_POOL is None:
            _GLOBAL_POOL = ModelPoolManager()
        return _GLOBAL_POOL


def throttle_chain_step(
    step_idx: int,
    total_steps: int,
    stagger_ms: int = 300,
    max_safe_length: int = 8,
    pacing_interval: int = 5,
    pacing_pause_s: float = 1.0,
    on_log: Callable[[str], None] | None = None,
) -> float:
    """Apply inter-step stagger and periodic pacing pauses within a command chain.

    Returns the duration slept (in seconds).
    """
    log = on_log or print
    slept = 0.0

    if step_idx == 0 and total_steps >= max_safe_length:
        log(f"[chain_throttle] Long multi-action chain detected ({total_steps} sub-actions). Enforcing strict rotation & pacing.")

    if step_idx > 0:
        if pacing_interval > 0 and step_idx % pacing_interval == 0:
            log(f"[chain_throttle] Periodic pacing pause ({pacing_pause_s:.1f}s) at step {step_idx}/{total_steps}")
            if pacing_pause_s > 0:
                time.sleep(pacing_pause_s)
                slept += pacing_pause_s
        elif stagger_ms > 0:
            stagger_s = stagger_ms / 1000.0
            time.sleep(stagger_s)
            slept += stagger_s

    return slept

