"""Verification gate for the Gemini Head adapter (Prompt 6).

Run: python3 verify_akira_head.py

WHAT THIS CAN AND CANNOT PROVE
==============================
CAN, with no API key and no network:
  - translation of ROUTING_SCHEMA into what Gemini accepts, including the two
    constructs the OpenAPI-subset `responseSchema` rejects outright
    (additionalProperties, union "type" lists)
  - the shared daily counter is genuinely shared, and attributes by purpose
  - every refusal path returns a SPOKEN, conversation-mode envelope rather than
    raising into the voice loop or executing actions
  - NO SILENT ESCALATION: a misconfigured/exhausted Free Head never quietly
    becomes paid Claude
  - the reply object duck-types what ask_akira already consumes

CANNOT, without a real GEMINI_API_KEY:
  - that Google accepts the request and returns schema-valid routing JSON
  - real latency on the voice hot path
  - whether implicit prefix caching actually hits
Those need `python3 gemini_head.py --live` and are stated as unverified rather
than mocked into a false pass. A mocked HTTP 200 would only prove the mock.
"""

from __future__ import annotations

import json
import os
import sys

# Isolate the counter file BEFORE importing anything that reads it, so a real
# day's quota on the dev machine is never touched by a verification run.
os.environ["AKIRA_QUOTA_FILE"] = "/tmp/verify_akira_quota.json"
for _stale in (os.environ["AKIRA_QUOTA_FILE"],
               os.environ["AKIRA_QUOTA_FILE"] + ".tmp"):
    try:
        os.remove(_stale)
    except OSError:
        pass

import akira_quota                                               # noqa: E402
import gemini_head                                               # noqa: E402
import tiers                                                     # noqa: E402

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(("PASS" if ok else "FAIL", name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, detail: str) -> None:
    RESULTS.append(("SKIP", name, detail))
    print(f"[SKIP] {name} — {detail}")


# --------------------------------------------------------------------------
# Schema translation. This is where a naive port breaks: Gemini's
# `responseSchema` is an OpenAPI 3.0 subset that rejects both
# additionalProperties and union type lists, and ROUTING_SCHEMA uses both.
# --------------------------------------------------------------------------
def test_schema_translation() -> None:
    hostile = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["a", "b"]},
            "maybe": {"type": ["string", "null"]},
            "nested": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"deep": {"type": ["integer", "null"]}},
            },
            "arr": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": False,
                          "properties": {"x": {"type": "string"}}},
            },
        },
        "required": ["action"],
    }

    san = gemini_head._sanitise_for_openapi(hostile)

    def walk(node, found):
        if isinstance(node, dict):
            if "additionalProperties" in node:
                found["addl"] = True
            if isinstance(node.get("type"), list):
                found["union"] = True
            if node.get("nullable") is True:
                found["nullable"] = True
            for v in node.values():
                walk(v, found)
        elif isinstance(node, list):
            for v in node:
                walk(v, found)
        return found

    found = walk(san, {})
    check("schema/strips-additionalProperties",
          not found.get("addl"),
          "responseSchema rejects additionalProperties at any depth")
    check("schema/strips-union-types",
          not found.get("union"),
          'responseSchema rejects {"type": ["string", "null"]}')
    check("schema/union-becomes-nullable",
          found.get("nullable") is True,
          "a nullable union must survive as nullable, not be dropped — "
          "dropping it would forbid the null the router legitimately emits")
    check("schema/preserves-enum",
          san["properties"]["action"]["enum"] == ["a", "b"],
          "the action-name grammar is the point of the schema")
    check("schema/preserves-required",
          san.get("required") == ["action"], "required must survive")
    check("schema/does-not-mutate-input",
          hostile["additionalProperties"] is False,
          "sanitising must not corrupt the caller's shared schema dict")

    # propertyOrdering: Gemini honours declaration order; without it the model
    # may emit keys in an order that reads as a different intent.
    check("schema/sets-propertyOrdering",
          isinstance(san.get("propertyOrdering"), list)
          and "action" in san["propertyOrdering"],
          "propertyOrdering keeps generated key order deterministic")


# --------------------------------------------------------------------------
# Shared quota. Two private counters would each think they owned the whole
# allowance and together permit ~2x the real cap.
# --------------------------------------------------------------------------
def test_shared_quota() -> None:
    start = akira_quota.used_today()
    akira_quota.record("routing")
    akira_quota.record("content_generation")
    check("quota/one-counter-both-purposes",
          akira_quota.used_today() == start + 2,
          "routing and content must increment the SAME counter")

    snap = akira_quota.snapshot()
    check("quota/attributes-by-purpose",
          snap["by_purpose"].get("routing", 0) >= 1
          and snap["by_purpose"].get("content_generation", 0) >= 1,
          "'quota gone, no idea what spent it' is not debuggable")

    check("quota/stops-below-google-limit",
          akira_quota.STOP_AT < akira_quota.DAILY_LIMIT,
          "must brake before Google's hard 429, not at it")

    try:
        import gemini_content
        check("quota/content-module-shares-limit",
              gemini_content._STOP_AT == akira_quota.STOP_AT,
              "gemini_content must not keep a private limit")
    except ModuleNotFoundError as e:
        skip("quota/content-module-shares-limit", f"{e} (third-party dep)")

    check("quota/corrupt-file-reads-as-zero",
          _corrupt_reads_zero(),
          "a corrupt counter must never be the reason a turn dies")


def _corrupt_reads_zero() -> bool:
    path = os.environ["AKIRA_QUOTA_FILE"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json at all")
    try:
        return akira_quota.used_today() == 0
    finally:
        os.remove(path)


# --------------------------------------------------------------------------
# THE CENTRAL GUARANTEE: no silent escalation to paid Claude.
# --------------------------------------------------------------------------
def test_no_silent_escalation() -> None:
    import claude_handler as ch
    saved_tier = os.environ.get("AKIRA_HEAD_TIER")
    saved_key = os.environ.get("GROQ_API_KEY")
    saved_esc = os.environ.get("AKIRA_HEAD_ESCALATE_ON_CAP")
    try:
        # Free tier selected, key missing -> must REFUSE, not become Claude.
        os.environ["AKIRA_HEAD_TIER"] = "free"
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("AKIRA_HEAD_ESCALATE_ON_CAP", None)
        provider, payload = ch._head_dispatch()
        check("escalation/free-without-key-refuses",
              provider == "refuse",
              f"got provider={provider!r} — 'claude' here would silently bill "
              f"a user who explicitly chose the free tier")
        check("escalation/refusal-explains-how-to-fix",
              provider == "refuse" and "GROQ_API_KEY" in str(payload),
              "a refusal the user cannot act on is just a dead end")

        # Free tier + key present -> groq, still never claude.
        os.environ["GROQ_API_KEY"] = "test-key-not-used-offline"
        provider, _ = ch._head_dispatch()
        check("escalation/free-with-key-uses-groq",
              provider == "groq", f"got {provider!r}")

        # Paid tier -> claude, as configured.
        os.environ["AKIRA_HEAD_TIER"] = "standard"
        provider, _ = ch._head_dispatch()
        check("escalation/standard-uses-claude",
              provider == "claude", f"got {provider!r}")
    finally:
        for k, v in (("AKIRA_HEAD_TIER", saved_tier),
                     ("GROQ_API_KEY", saved_key),
                     ("AKIRA_HEAD_ESCALATE_ON_CAP", saved_esc)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_cap_refuses_by_default() -> None:
    """An exhausted cap must speak, not silently spend money."""
    saved = os.environ.get("AKIRA_HEAD_ESCALATE_ON_CAP")
    try:
        os.environ.pop("AKIRA_HEAD_ESCALATE_ON_CAP", None)
        check("cap/escalation-is-opt-in",
              gemini_head._escalate_on_cap() is False,
              "default must be refuse-and-explain, never auto-upgrade to paid")
        os.environ["AKIRA_HEAD_ESCALATE_ON_CAP"] = "1"
        check("cap/escalation-opt-in-works",
              gemini_head._escalate_on_cap() is True,
              "an operator who explicitly opts in must get it")
    finally:
        if saved is None:
            os.environ.pop("AKIRA_HEAD_ESCALATE_ON_CAP", None)
        else:
            os.environ["AKIRA_HEAD_ESCALATE_ON_CAP"] = saved


# --------------------------------------------------------------------------
# Reply shape: ask_akira must not learn which provider answered.
# --------------------------------------------------------------------------
def test_reply_duck_type() -> None:
    """HeadReply must provide the attributes claude_handler expects."""
    reply = gemini_head._refuse("test refusal text")

    # .content is a list of text-bearing blocks (same as Anthropic Messages).
    check("shape/has-content-list",
          isinstance(getattr(reply, "content", None), list))
    check("shape/block-has-text",
          all(hasattr(b, "text") for b in reply.content))
    check("shape/block-type-is-text",
          all(getattr(b, "type", None) == "text" for b in reply.content))
    check("shape/has-stop-reason", hasattr(reply, "stop_reason"))

    # Parse what response_text would see: must be valid JSON with conversation
    # envelope, never action mode.
    raw = "".join(b.text for b in reply.content)
    try:
        parsed = json.loads(raw)
        check("shape/refusal-is-valid-json", True)
    except json.JSONDecodeError as e:
        check("shape/refusal-is-valid-json", False, str(e))
        return

    check("shape/refusal-is-conversation-mode",
          parsed.get("mode") == "conversation")
    check("shape/refusal-has-no-actions",
          "actions" not in parsed or not parsed["actions"])
    check("shape/refusal-speaks",
          bool(parsed.get("response")),
          "silent failure on a voice assistant is indistinguishable from a hang")
    check("shape/refusal-does-not-end-session",
          parsed.get("end_session") is False,
          "quota exhaustion must not hang up on the user")

    # claude_handler has an internal refusal reply builder; verify its shape
    # matches gemini_head's so callers can't tell them apart.
    try:
        import claude_handler as ch
        shim = ch._refusal_reply("claude-side refusal")
        check("shape/claude-shim-matches",
              isinstance(shim.content, list)
              and getattr(shim.content[0], "type", None) == "text"
              and hasattr(shim, "stop_reason"))
    except ModuleNotFoundError as e:
        skip("shape/claude-shim-matches", f"{e} (third-party dep)")


def test_readiness_is_offline() -> None:
    saved = os.environ.get("GROQ_API_KEY")
    try:
        os.environ.pop("GROQ_API_KEY", None)
        ok, reason = gemini_head.readiness()
        check("readiness/no-key-not-ready", not ok)
        check("readiness/no-key-names-the-var",
              "GROQ_API_KEY" in reason, reason[:70])
        os.environ["GROQ_API_KEY"] = "x"
        ok, _ = gemini_head.readiness()
        check("readiness/with-key-ready", ok,
              "readiness is a CONFIG check — it must not require a network call, "
              "because a startup banner calls it")
    finally:
        if saved is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = saved


def test_tiers_integration() -> None:
    try:
        import tiers
    except ModuleNotFoundError as e:
        skip("tiers/free-head-live", f"{e} (tiers' own dep)")
        return

    saved = os.environ.get("GROQ_API_KEY")
    try:
        os.environ["GROQ_API_KEY"] = "x"
        spec = tiers.head(tiers.FREE)
        check("tiers/free-head-live", bool(spec),
              "Free Head must resolve once the adapter and key exist")
        check("tiers/free-head-is-groq",
              getattr(spec, "provider", None) == "groq")
        check("tiers/free-budget-is-zero-not-none",
              getattr(spec, "daily_budget_usd", None) == 0.0,
              "None means UNMETERED in this dataclass — the free tier is the "
              "opposite of unmetered")

        os.environ.pop("GROQ_API_KEY", None)
        spec = tiers.head(tiers.FREE)
        check("tiers/free-head-unavailable-without-key",
              not spec, "missing config must report Unavailable, not a live spec")
    finally:
        if saved is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = saved


def main() -> int:
    print("=" * 68)
    print("Gemini Head adapter verification (Prompt 6)")
    print("=" * 68)
    for fn in (test_schema_translation, test_shared_quota,
               test_no_silent_escalation, test_cap_refuses_by_default,
               test_reply_duck_type, test_readiness_is_offline,
               test_tiers_integration):
        print(f"\n--- {fn.__name__} ---")
        try:
            fn()
        except Exception as e:                                    # noqa: BLE001
            check(f"{fn.__name__}/raised", False, repr(e))

    failed = [r for r in RESULTS if r[0] == "FAIL"]
    skipped = [r for r in RESULTS if r[0] == "SKIP"]
    print("\n" + "=" * 68)
    print(f"{len(RESULTS) - len(failed) - len(skipped)} passed, "
          f"{len(failed)} failed, {len(skipped)} skipped")
    for _, n, d in skipped:
        print(f"  SKIP {n} — {d}")
    for _, n, d in failed:
        print(f"  FAIL {n} — {d}")
    print("\nNOTE: no Gemini request was made. Schema ACCEPTANCE by Google, "
          "real routing quality, hot-path latency and whether implicit prefix "
          "caching actually hits remain UNVERIFIED without a live key — run "
          "`python3 gemini_head.py --live` with GEMINI_API_KEY set.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
