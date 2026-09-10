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
    AKIRA_TIER                  default for any layer not set below
    AKIRA_HEAD_TIER             Head (brain)
    AKIRA_GUARD_TIER            Guard model
    AKIRA_SERVANT_TIER          Servant for A / A-adjacent work
    AKIRA_SERVANT_GATED_TIER    Servant for Gated work
    AKIRA_GUARD_MODE_TIER       parallel / serial / reliability-gate policy

So `AKIRA_TIER=standard AKIRA_GUARD_TIER=free` runs a Standard Head against a
Free Guard with no code change, which is the stated requirement.

MIXING IS UNRESTRICTED BUT THREE COMBINATIONS ARE GENUINELY BROKEN
-----------------------------------------------------------------
Not softened, and not blocked — `warnings()` reports them at startup and the
combinations still run, because a maintainer testing a specific pairing needs
them to. The concrete failures:

1. HEAD=free + SERVANT=free/standard  ->  ROUTING WORKS, SERVANT WORK DOES NOT.
   Free Head routes via Groq (GROQ_MODEL in .env, e.g. qwen/qwen3.6-27b) with
   GROQ_API_KEY set. Gemini has been completely removed from use. Voice turns
   are classified and planned with sub-second latency.

   What remains genuinely broken is the SERVANT half — Free/Standard Servant is
   still inert (no local runtime, and servant_allowed() refuses to escalate to
   hosted inference on those tiers). So Akira can work out what to do and run
   anything the executor handles directly, but any step needing servant
   inference cannot serve. Free tier is now PARTIALLY usable rather than
   entirely unusable.

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
AKIRA_LOCAL_MODEL_PATH changes the reason text, never the availability — a slot
that flipped to "available" because a path string was set would be a fake
success path, and the first real call would fail somewhere far from the config
that caused it. Wiring a runtime is separate future work; this is the seam it
will attach to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from dotenv import load_dotenv

load_dotenv()

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
    Layer.HEAD: "AKIRA_HEAD_TIER",
    Layer.GUARD: "AKIRA_GUARD_TIER",
    Layer.SERVANT: "AKIRA_SERVANT_TIER",
    Layer.SERVANT_GATED: "AKIRA_SERVANT_GATED_TIER",
    Layer.GUARD_MODE: "AKIRA_GUARD_MODE_TIER",
}


def plan_for(layer: Layer) -> str:
    """Resolve one layer's plan: its own env var, else AKIRA_TIER, else free.

    Defaults to FREE rather than PRO deliberately. An unset or misspelled env
    var must not silently grant the most capable tier — the failure direction
    for a config typo should be "less is available", never "destructive actions
    are now unlocked".
    """
    raw = (os.environ.get(_ENV[layer])
           or os.environ.get("AKIRA_TIER") or FREE).strip().lower()
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
    daily_turns_cap: int = 0

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
class GatedSeat:
    """Permission to OFFER Gated actions at a tier. Deliberately not a model spec.

    A distinct type from ServantSpec because the two answer different questions
    and share no field that would make sense in both. Truthy whenever it exists:
    the only way for Gated to be unpermitted is Free, which returns Unavailable
    instead of a seat — so there is no falsy GatedSeat and no ambiguous middle
    state for a caller to misread.
    """
    plan: str
    adapters: bool = False

    def __bool__(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"Gated actions available on {self.plan} tier"


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
    path_env: str = "AKIRA_LOCAL_MODEL_PATH"
    adapter_env: str = "AKIRA_LOCAL_ADAPTER_PATH"
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

    FREE TIER — NO SERVER INVOLVEMENT AT ALL
    Free tier is intentionally excluded from the gateway — no caps, no server
    round-trip, no auth required. Free Head routes directly to its local configured
    model (e.g. Groq with GROQ_MODEL in .env).

    STANDARD & PRO TIERS — SERVER GATED WITH GROQ FALLBACK
    Standard: 30 turns/day Claude head.
    Pro: 53 turns/day Claude head (priority routing).
    Both fall back to Groq free API when their Claude daily cap is reached.
    """
    plan = plan or plan_for(Layer.HEAD)
    if plan == FREE:
        groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
        if not groq_key:
            return Unavailable("Head", FREE,
                               "GROQ_API_KEY is not set in .env. Set GROQ_API_KEY to use the Free Head.")
        return HeadSpec(FREE, "groq", "GROQ_MODEL", "GROQ_API_KEY",
                        daily_budget_usd=0.0,
                        priority=False,
                        daily_turns_cap=0)
    if plan == STANDARD:
        return HeadSpec(STANDARD, "anthropic", "CLAUDE_MODEL", "ANTHROPIC_API_KEY",
                        daily_budget_usd=_budget("AKIRA_HEAD_BUDGET_USD", 5.0),
                        priority=False,
                        daily_turns_cap=30)
    return HeadSpec(PRO, "anthropic", "CLAUDE_MODEL", "ANTHROPIC_API_KEY",
                    daily_budget_usd=_budget("AKIRA_HEAD_BUDGET_USD_PRO", 25.0),
                    priority=True,
                    daily_turns_cap=53)


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

    Per the tier table, hosted fallback exists on PRO only. On Free and Standard
    the row is local-only, and no local runtime exists, so those resolve to no
    server at all — the strict reading of the table.
    """
    plan = plan or plan_for(Layer.SERVANT)
    slot = LocalModel(plan, adapters=(plan in (STANDARD, PRO)))
    hosted = _hosted_fallback() if plan == PRO else None
    return ServantSpec(plan, slot, hosted, adapters=slot.adapters)


def servant_allowed(plan: str | None = None) -> Unavailable | None:
    """May a servant-tier LLM call proceed on hosted infrastructure right now?

    None = yes, Unavailable = no, with a reason.

    WHY THIS EXISTS AS A SEPARATE GATE, AND WHY IT IS THE OPPOSITE OF
    servant_clients' POLICY
    ----------------------------------------------------------------
    servant_clients documents a fail-OPEN policy: ServantUnavailable makes the
    caller fall back to its brain-tier model (claude_handler.servant_or_none
    returns None, and the call runs on paid Claude). That is correct for the
    failure it was written for — a revoked GLM_API_KEY should degrade to
    working-but-pricier, not to a broken feature.

    It is the WRONG behaviour for a tier decision, and the difference is intent.
    An unset key is an accident, so absorbing it is a kindness. A Free tier is a
    deliberate instruction not to spend money. Routing a Free-tier servant call
    up to paid Claude would honour the letter of "the feature still works" while
    breaking the only promise the Free tier actually makes. Cost surprise is the
    worst failure mode a tier system has, because the user cannot see it happen
    and finds out from a bill.

    So on Free/Standard this returns Unavailable and the call site must FAIL,
    not escalate. That is a deliberate fail-CLOSED override of the module-level
    fail-open policy, scoped to the tier check alone: a genuine mid-flight
    ServantUnavailable on Pro still falls back exactly as before, because Pro
    resolves to a hosted spec and never reaches this branch.

    Consequence, stated plainly rather than softened: Free and Standard cannot
    run servant-tier work at all today. Every such call fails with the reason
    below. This is the intended meaning of "structurally present but inert" and
    it is temporary — it resolves when a local runtime is wired to
    LocalModel.resolve(), with no change to this function.
    """
    plan = plan or plan_for(Layer.SERVANT)
    spec = servant(plan)
    if spec:
        return None  # Pro with a hosted key: proceed, normal fallback applies.

    local = spec.local.resolve()
    if plan == PRO:
        # Pro is entitled to hosted fallback but no provider key is set. Distinct
        # reason from Free/Standard: this is a missing-config problem the operator
        # can fix, not a tier that forbids the spend.
        return Unavailable(
            "servant", plan,
            f"{local.reason} Pro allows a hosted fallback, but neither "
            f"TOGETHER_API_KEY nor FIREWORKS_API_KEY is set, so there is "
            f"nothing to fall back to.")
    return Unavailable(
        "servant", plan,
        f"{local.reason} The {plan} tier has no hosted servant fallback by "
        f"design — it is not permitted to spend money on hosted inference. "
        f"Set AKIRA_SERVANT_TIER=pro and a TOGETHER_API_KEY/FIREWORKS_API_KEY "
        f"to allow hosted servant calls.")


def servant_gated(plan: str | None = None):
    """Is the GATED CAPABILITY permitted at this tier? Available across all tiers under confirmation.

    In the unified tier architecture, the fallback model pool absorbs Standard
    and Pro traffic with the full action set. All Gated actions are permitted
    behind serial Guard review and spoken human confirmation.
    """
    plan = plan or plan_for(Layer.SERVANT_GATED)
    return GatedSeat(plan, adapters=(plan == PRO))


def guard_mode(plan: str | None = None) -> GuardMode:
    """Guard timing/enforcement policy.

    FREE     parallel for A/A-adjacent + serial for Gated (same safety as Standard).
    STANDARD parallel for A/A-adjacent + serial for Gated.
    PRO      as Standard, plus Gated unlocks per action type via reliability.py.
    """
    plan = plan or plan_for(Layer.GUARD_MODE)
    if plan == FREE:
        return GuardMode(FREE, parallel=True, serial_gated=True,
                         reliability_gate=False)
    if plan == STANDARD:
        return GuardMode(STANDARD, parallel=True, serial_gated=True,
                         reliability_gate=_flag("AKIRA_RELIABILITY_GATE", False))
    # Pro: the gate is ON by default here and configurable, so the same bar can
    # be applied to Standard for testing without a code change.
    return GuardMode(PRO, parallel=True, serial_gated=True,
                     reliability_gate=_flag("AKIRA_RELIABILITY_GATE", True))


# ── The one composite decision ───────────────────────────────────────────────

def gated_available(action: str, *,
                    supervised: bool = False) -> Unavailable | None:
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

    `supervised` — THE BOOTSTRAP PROVISION, and why it has to exist
    --------------------------------------------------------------
    Without it this function is a deadlock, not a gate. Traced end to end:

        no history -> cleared() is False -> Unavailable
                   -> _guard_gated drops the step (`continue`)
                   -> the action never executes
                   -> reliability.record is never called
                   -> streak stays 0 -> no history ... forever

    Every Gated action on a fresh Pro install is therefore withheld
    permanently, with no reachable path to the runs it is being asked to
    produce. Verified live at RELIABILITY_RUNS=3 before this parameter existed:
    delete_files, shutdown_pc and write_file all reported "3 more successful
    runs needed" with no way to earn even one. It was invisible only because
    the gate is off by default on Free/Standard.

    The resolution is to notice WHAT the bar is actually protecting against.
    An unproven destructive action is dangerous when it runs UNATTENDED. It is
    not meaningfully dangerous when a human is shown the resolved plan and
    types yes first — that human IS the supervision, and it is the same
    supervision Standard relies on with no bar at all.

    So the bar governs autonomy, not existence. Under supervision an unproven
    action is offered ON PROBATION: it still requires confirmation, it still
    cannot run silently, and each confirmed outcome is recorded, so the streak
    can actually be earned. Unsupervised, the bar is enforced exactly as before.

    Default False so the strict reading stays the default and every existing
    caller keeps its current behaviour; only a caller that can prove a human is
    in the loop may pass True. The tier gate is NOT relaxed by supervision — a
    Free tier still has no Gated actions no matter who is watching.
    """
    seat = servant_gated()
    if not seat:
        return seat if isinstance(seat, Unavailable) else Unavailable(
            "Gated actions", plan_for(Layer.SERVANT_GATED), "not available")

    mode = guard_mode()
    if mode.reliability_gate and not reliability.cleared(action):
        if supervised:
            # Probation: offered, but only ever behind the confirmation flow.
            return None
        left = reliability.remaining(action)
        return Unavailable(
            action.replace("_", " "), mode.plan,
            f"it has not cleared the {reliability.THRESHOLD}-run reliability "
            f"protocol yet — {left} more successful run"
            f"{'s' if left != 1 else ''} needed.")
    return None


def on_probation(action: str) -> bool:
    """Is this action being offered only because a human is supervising it?

    True when the tier permits Gated, the reliability gate is live, and this
    action type has not cleared the bar yet. Drives the honest wording at the
    confirmation prompt — the user is told the action is still on probation
    rather than being handed a silent difference in enforcement.
    """
    if not servant_gated():
        return False
    return guard_mode().reliability_gate and not reliability.cleared(action)


def content_search_allowed(plan: str | None = None) -> tuple[bool, str]:
    """May the user perform document content search (PDF, DOCX, TXT)?

    Free tier: filename/metadata search only.
    Standard & Pro: full document content search allowed.
    Returns: (is_allowed, explanatory_message)
    """
    plan = plan or plan_for(Layer.HEAD)
    if plan == FREE:
        return (False, "Content search is available on Standard and Pro — I can still search filenames though.")
    return (True, "")


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
            "HEAD=free + SERVANT=%s: routing works (Groq Head), but the %s "
            "Servant may not escalate to hosted inference and has no local "
            "runtime, so any step needing servant inference cannot serve. "
            "Set AKIRA_SERVANT_TIER=pro for servant work." % (s, s))
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
        "servant": str(servant_allowed() or servant().hosted),
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