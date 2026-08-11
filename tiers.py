"""Free / Standard / Pro tier configuration — five independently switchable layers.

WHAT THIS IS
============
Declarative config layered ON TOP of the Guard (guard.py) and router
(action_router.py). It resolves "what is available at this tier" and nothing
else: no model is called here, no action is dispatched here, and executor.py is
untouched. Every layer answers with either a usable spec or an `Unavailable`
carrying a reason a user can act on.

THE FIVE LAYERS ARE SEPARATE ENV VARS, NOT ONE tier=pro SWITCH
--------------------------------------------------------------
    SENSEI_TIER                  default for any layer not set below
    SENSEI_HEAD_TIER             Head (brain)
    SENSEI_GUARD_TIER            Guard model
    SENSEI_SERVANT_TIER          Servant for A / A-adjacent work
    SENSEI_SERVANT_GATED_TIER    Servant for Gated work
    SENSEI_GUARD_MODE_TIER       parallel / serial / reliability-gate policy

So `SENSEI_TIER=standard SENSEI_GUARD_TIER=free` runs a Standard Head against a
Free Guard with no code change, which is the stated requirement.

MIXING IS UNRESTRICTED BUT THREE COMBINATIONS ARE GENUINELY BROKEN
-----------------------------------------------------------------
Not softened, and not blocked — `warnings()` reports them at startup and the
combinations still run, because a maintainer testing a specific pairing needs
them to. The concrete failures:

1. HEAD=free + SERVANT=free/standard  ->  NOTHING WORKS.
   servant_clients' documented policy is that ServantUnavailable makes the
   CALLER fall back to its brain-tier model. That fallback assumes a working
   brain. Free Head is inert (no Gemini routing adapter, see head() below) and
   Free/Standard Servant is inert (no local runtime), so the fallback chain
   terminates in nothing. This is the default-install state and it is why Free
   tier is not a usable configuration today.

2. GUARD_MODE=standard|pro + SERVANT_GATED=free  ->  CONTRADICTION.
   Guard mode enables the serial Gated path while the Servant layer says Gated
   is unavailable. Gated actions stay off, so the serial path and the whole
   reliability gate silently do nothing. Nothing breaks; it just is not the
   configuration the operator thinks they set.

3. GUARD=free + GUARD_MODE=pro  ->  UNTESTED PAIRING, and the risky direction.
   Pro guard mode makes Gated enforcement live, i.e. real destructive actions
   depend on Guard verdict quality, while the Free Guard row is the free API
   quota. On exhaustion guard.review() fails closed to FLAG (never ALLOW), so
   the safety property holds — but every Gated action degrades to "ask the
   human", and an operator who reads that as the Guard approving things has it
   exactly backwards.

WHY THE LOCAL ROWS ARE INERT AND STAY INERT
-------------------------------------------
No local inference runtime exists anywhere in this codebase and no fine-tuning
dataset exists, so `LocalModel.resolve()` ALWAYS returns Unavailable. Setting
SENSEI_LOCAL_MODEL_PATH changes the reason text, never the availability — a slot
that flipped to "available" because a path string was set would be a fake
success path, and the first real call would fail somewhere far from the config
that caused it. Wiring a runtime is separate future work; this is the seam it
will attach to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

import reliability
import servant_clients

FREE, STANDARD, PRO = "free", "standard", "pro"
_PLANS = (FREE, STANDARD, PRO)


class Layer(str, Enum):
    HEAD = "head"
    GUARD = "guard"
    SERVANT = "servant"                 # A / A-adjacent
    SERVANT_GATED = "servant_gated"
    GUARD_MODE = "guard_mode"


_ENV = {
    Layer.HEAD: "SENSEI_HEAD_TIER",
    Layer.GUARD: "SENSEI_GUARD_TIER",
    Layer.SERVANT: "SENSEI_SERVANT_TIER",
    Layer.SERVANT_GATED: "SENSEI_SERVANT_GATED_TIER",
    Layer.GUARD_MODE: "SENSEI_GUARD_MODE_TIER",
}


def plan_for(layer: Layer) -> str:
    """Resolve one layer's plan: its own env var, else SENSEI_TIER, else free.

    Defaults to FREE rather than PRO deliberately. An unset or misspelled env
    var must not silently grant the most capable tier — the failure direction
    for a config typo should be "less is available", never "destructive actions
    are now unlocked".
    """
    raw = (os.environ.get(_ENV[layer])
           or os.environ.get("SENSEI_TIER") or FREE).strip().lower()
    return raw if raw in _PLANS else FREE


@dataclass(frozen=True)
class Unavailable:
    """A layer that cannot serve, with a reason meant for a human.

    Falsy so callers can write `if not spec:` — but it carries the reason rather
    than being None, because "unavailable" with no explanation is what produces
    a silent hang or a bare failure at the call site.
    """
    layer: str
    plan: str
    reason: str

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return f"{self.layer} unavailable on {self.plan} tier: {self.reason}"


@dataclass(frozen=True)
class HeadSpec:
    plan: str
    provider: str
    model_env: str
    key_env: str
    daily_budget_usd: float | None   # None = unmetered
    priority: bool

    def __bool__(self) -> bool:
        return True


@dataclass(frozen=True)
class ServantSpec:
    """A servant resolution: which local slot was tried, and what serves instead.

    `local` is always the inert slot. `hosted` is the fallthrough, present only
    where the tier table gives one.
    """
    plan: str
    local: "LocalModel"
    hosted: object | None
    adapters: bool

    def __bool__(self) -> bool:
        return self.hosted is not None


@dataclass(frozen=True)
class GuardMode:
    plan: str
    parallel: bool            # race guard with execution for A / A-adjacent
    serial_gated: bool        # blocking guard in front of Gated
    reliability_gate: bool    # Gated unlocks per action type via reliability.py


@dataclass(frozen=True)
class LocalModel:
    """Config slot for a local model + optional LoRA adapters. Never available.

    Structurally real so the tier table is faithfully represented and so future
    work has one obvious attachment point — but `resolve()` cannot return a
    usable handle, because there is no runtime to hand back.
    """
    plan: str
    path_env: str = "SENSEI_LOCAL_MODEL_PATH"
    adapter_env: str = "SENSEI_LOCAL_ADAPTER_PATH"
    adapters: bool = False

    @property
    def path(self) -> str | None:
        return (os.environ.get(self.path_env) or "").strip() or None

    @property
    def adapter_path(self) -> str | None:
        return (os.environ.get(self.adapter_env) or "").strip() or None

    def resolve(self) -> Unavailable:
        """Always Unavailable. The reason distinguishes the two real cases so a
        maintainer who HAS set a path is told the runtime is missing, not that
        their path is wrong — otherwise this looks like a config bug forever."""
        if self.path:
            return Unavailable(
                "local servant", self.plan,
                f"model path is set ({self.path}) but no local inference runtime "
                f"is wired into this build. The runtime is separate future work; "
                f"until then this slot cannot serve.")
        return Unavailable(
            "local servant", self.plan,
            f"no local model configured ({self.path_env} unset) and no local "
            f"inference runtime is wired into this build.")


# ── Layer resolution ─────────────────────────────────────────────────────────

def head(plan: str | None = None) -> HeadSpec | Unavailable:
    """Head (brain) for a plan.

    FREE is inert BY VERIFICATION, not by omission. The table specifies the
    Gemini free tier, and gemini_content.py does hold a working Gemini client
    with the daily-cap pattern this row needs — but it is a CONTENT GENERATOR:
    prompt in, prose out. The Head role needs tool/action routing, strict JSON
    schema output, and the prompt-caching path claude_handler's routing depends
    on. None of those exist for Gemini here, so there is no honest way to seat
    it as Head.

    It therefore returns Unavailable rather than quietly falling through to paid
    Claude. Silent escalation would mean a user who chose Free to avoid spending
    money spends it without being told, and cost surprise is the worst failure
    mode a tier system can have.
    """
    plan = plan or plan_for(Layer.HEAD)
    if plan == FREE:
        return Unavailable(
            "Head", FREE,
            "the Free Head is Gemini, but no Gemini routing adapter exists in "
            "this build (gemini_content.py generates prose only — it has no "
            "tool-routing or JSON-schema path). Set SENSEI_HEAD_TIER=standard "
            "to use paid Claude, or build the adapter. Not falling back to paid "
            "Claude automatically, because that would spend money you did not "
            "agree to.")
    if plan == STANDARD:
        return HeadSpec(STANDARD, "anthropic", "CLAUDE_MODEL", "ANTHROPIC_API_KEY",
                        daily_budget_usd=_budget("SENSEI_HEAD_BUDGET_USD", 5.0),
                        priority=False)
    return HeadSpec(PRO, "anthropic", "CLAUDE_MODEL", "ANTHROPIC_API_KEY",
                    daily_budget_usd=_budget("SENSEI_HEAD_BUDGET_USD_PRO", 25.0),
                    priority=True)


def guard(plan: str | None = None):
    """Guard model. Available on every tier — the table gives all three the
    hosted Qwen/Kimi free API, and this is the one layer that must never be
    inert: a guard that cannot be reached fails closed to FLAG (guard.py), so
    removing it does not open a hole, but it does turn every Gated action into a
    confirmation prompt and gets the whole layer switched off by an annoyed user.

    Returns the existing servant_clients.GUARD spec unchanged. Tier affects
    budget expectations and whether Gated enforcement is live (see guard_mode),
    not which model answers.
    """
    plan = plan or plan_for(Layer.GUARD)
    if not servant_clients.GUARD.available:
        return Unavailable(
            "Guard", plan,
            f"{servant_clients.GUARD.key_env} is not set. The guard fails closed "
            f"without it, so every consequential action will ask for "
            f"confirmation until a key is added.")
    return servant_clients.GUARD


def servant(plan: str | None = None) -> ServantSpec:
    """Servant for A / A-adjacent work.

    Per the tier table, hosted fallback exists on PRO only. The brief's
    fallthrough rule is "hosted if available, otherwise a clear error" — on
    Free and Standard no hosted row is configured, so those resolve to no
    server. That is the strict reading of the table.

    CONSEQUENCE, stated plainly: on Free/Standard every servant call site raises
    ServantUnavailable and falls back to its brain-tier model per
    servant_clients' documented policy. That is the pre-existing fail-open path,
    so nothing breaks silently — calls get pricier, and on Free (inert Head)
    they fail outright. See warnings() combination 1.
    """
    plan = plan or plan_for(Layer.SERVANT)
    slot = LocalModel(plan, adapters=(plan in (STANDARD, PRO)))
    hosted = _hosted_fallback() if plan == PRO else None
    return ServantSpec(plan, slot, hosted, adapters=slot.adapters)


def servant_gated(plan: str | None = None):
    """Servant for Gated work. Not available on Free, per the table."""
    plan = plan or plan_for(Layer.SERVANT_GATED)
    if plan == FREE:
        return Unavailable(
            "Gated actions", FREE,
            "Gated actions are not available on the Free tier. Set "
            "SENSEI_SERVANT_GATED_TIER=standard to enable them with the full "
            "confirmation flow.")
    return servant(plan)


def guard_mode(plan: str | None = None) -> GuardMode:
    """Guard timing/enforcement policy.

    FREE     parallel only; Gated unavailable, so no serial path is needed.
    STANDARD parallel for A/A-adjacent + serial for Gated.
    PRO      as Standard, plus Gated unlocks per action type via reliability.py.
    """
    plan = plan or plan_for(Layer.GUARD_MODE)
    if plan == FREE:
        return GuardMode(FREE, parallel=True, serial_gated=False,
                         reliability_gate=False)
    if plan == STANDARD:
        return GuardMode(STANDARD, parallel=True, serial_gated=True,
                         reliability_gate=_flag("SENSEI_RELIABILITY_GATE", False))
    # Pro: the gate is ON by default here and configurable, so the same bar can
    # be applied to Standard for testing without a code change.
    return GuardMode(PRO, parallel=True, serial_gated=True,
                     reliability_gate=_flag("SENSEI_RELIABILITY_GATE", True))


# ── The one composite decision ───────────────────────────────────────────────

def gated_available(action: str) -> Unavailable | None:
    """May this Gated action be OFFERED to the user right now?

    Returns None when it may, or an Unavailable explaining why not. Two gates,
    in order: does this tier have Gated at all, then has this specific action
    type cleared the reliability bar.

    NOT A TIER-NAME BYPASS. The reliability check consults reliability.cleared()
    which knows nothing about tiers; the tier only decides whether the gate is
    consulted. So Pro does not skip the bar — it is the tier that enforces it
    per action type, which is why a Pro user can temporarily have FEWER Gated
    actions available than Standard. That inversion is what the table specifies
    and it is intentional: Standard trades the per-action bar for the
    confirmation flow alone.
    """
    seat = servant_gated()
    if not seat:
        return seat if isinstance(seat, Unavailable) else Unavailable(
            "Gated actions", plan_for(Layer.SERVANT_GATED), "not available")

    mode = guard_mode()
    if mode.reliability_gate and not reliability.cleared(action):
        left = reliability.remaining(action)
        return Unavailable(
            action.replace("_", " "), mode.plan,
            f"it has not cleared the {reliability.THRESHOLD}-run reliability "
            f"protocol yet — {left} more successful run"
            f"{'s' if left != 1 else ''} needed.")
    return None


# ── Diagnostics ──────────────────────────────────────────────────────────────

def warnings() -> list[str]:
    """Concrete broken/untested cross-tier combinations for the current config.

    Reported, never enforced: the brief asks for independent toggling, and a
    maintainer deliberately testing a mixed pairing must be able to run it.
    """
    out: list[str] = []
    h, s = plan_for(Layer.HEAD), plan_for(Layer.SERVANT)
    sg, gm, g = (plan_for(Layer.SERVANT_GATED), plan_for(Layer.GUARD_MODE),
                 plan_for(Layer.GUARD))

    if h == FREE and s in (FREE, STANDARD):
        out.append(
            "HEAD=free + SERVANT=%s: nothing will work. Servant failures fall "
            "back to the brain, and the Free brain is inert, so the fallback "
            "chain ends nowhere. Set SENSEI_HEAD_TIER=standard." % s)
    if sg == FREE and gm in (STANDARD, PRO):
        out.append(
            f"GUARD_MODE={gm} + SERVANT_GATED=free: the serial Gated path and "
            f"the reliability gate are enabled but Gated actions are off, so "
            f"both do nothing.")
    if g == FREE and gm == PRO:
        out.append(
            "GUARD=free + GUARD_MODE=pro: Gated enforcement is live against a "
            "free-quota Guard. On exhaustion the guard fails closed to FLAG, so "
            "Gated actions degrade to 'ask the human' rather than being "
            "approved. Safe, but untested as a pairing.")
    return out


def summary() -> dict:
    """Current resolved configuration, for a startup log or a status command."""
    return {
        "plans": {l.value: plan_for(l) for l in Layer},
        "head": str(head()),
        "guard": str(guard()),
        "servant": str(servant().hosted or servant().local.resolve()),
        "servant_gated": str(servant_gated()),
        "guard_mode": guard_mode(),
        "reliability": {"mode": reliability.MODE,
                        "threshold": reliability.THRESHOLD},
        "warnings": warnings(),
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def _flag(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _budget(name: str, default: float) -> float | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    if raw.lower() in ("none", "unlimited", "0"):
        return None
    try:
        return float(raw)
    except ValueError:
        return default


def _hosted_fallback():
    """Pro's hosted servant fallback (Together / Fireworks).

    Reuses the existing servant Tier shape and the OpenAI-compatible transport,
    because both providers speak /chat/completions — the same reasoning
    servant_clients records for not adding a second HTTP implementation.

    Returns None when unconfigured, which keeps ServantSpec falsy and produces a
    clear error instead of a hang.
    """
    for key_env, model_env, base_env, default_base, default_model in (
        ("TOGETHER_API_KEY", "TOGETHER_MODEL", "TOGETHER_BASE_URL",
         "https://api.together.xyz/v1", "Qwen/Qwen2.5-72B-Instruct-Turbo"),
        ("FIREWORKS_API_KEY", "FIREWORKS_MODEL", "FIREWORKS_BASE_URL",
         "https://api.fireworks.ai/inference/v1",
         "accounts/fireworks/models/qwen2p5-72b-instruct"),
    ):
        if (os.environ.get(key_env) or "").strip():
            return servant_clients.Tier(
                f"SERVANT_HOSTED[{key_env.split('_')[0].lower()}]",
                os.environ.get(model_env, default_model),
                os.environ.get(base_env, default_base),
                key_env)
    return None