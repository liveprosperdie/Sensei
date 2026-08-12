"""Verification gate for the Gemini Head adapter (Prompt 6).

Run: python3 verify_gemini_head.py

WHAT THIS CAN AND CANNOT PROVE
==============================
CAN, with no API key and no network:
  - translation of ROUTING_SCHEMA into what Gemini accepts, including the two
    constructs the OpenAPI-subset `responseSchema` rejects outright
    (additionalProperties, union "type" lists) — against BOTH a hostile fixture
    and the real ROUTING_SCHEMA, since those can drift apart
  - FAIL-CLOSED parsing: every malformed, blocked or truncated Gemini response
    becomes a spoken refusal, never {"mode": "command", "actions": []}, which
    would be indistinguishable from deciding to do nothing
  - the shared daily counter is genuinely shared, and attributes by purpose
  - every `gemini_quota.<attr>` call site in the tree resolves against the real
    module, so the record()/bump() mismatch class of bug cannot reappear
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

import ast
import json
import os
import sys

# Isolate the counter file BEFORE importing anything that reads it, so a real
# day's quota on the dev machine is never touched by a verification run.
os.environ["SENSEI_GEMINI_QUOTA_FILE"] = "/tmp/verify_gemini_quota.json"
for _stale in (os.environ["SENSEI_GEMINI_QUOTA_FILE"],
               os.environ["SENSEI_GEMINI_QUOTA_FILE"] + ".tmp"):
    try:
        os.remove(_stale)
    except OSError:
        pass

import gemini_quota                                              # noqa: E402
import gemini_head                                               # noqa: E402

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


def test_real_routing_schema() -> None:
    """The hand-written fixture above proves the sanitiser's rules. This proves
    it against the ACTUAL ROUTING_SCHEMA the adapter will be handed — the two
    can diverge the moment someone edits the real schema, and a fixture-only
    test would keep passing while production broke."""
    try:
        import claude_handler as ch
    except ModuleNotFoundError as e:
        skip("real-schema/translates", f"{e} (third-party dep)")
        return

    real = ch.ROUTING_SCHEMA

    def walk(node, found):
        if isinstance(node, dict):
            if "additionalProperties" in node:
                found["addl"] = True
            if isinstance(node.get("type"), list):
                found["union"] = True
            for v in node.values():
                walk(v, found)
        elif isinstance(node, list):
            for v in node:
                walk(v, found)
        return found

    before = walk(real, {})
    # If this ever fails, the premise of the whole responseJsonSchema decision
    # has changed and the fallback path needs revisiting, not silently trusting.
    check("real-schema/uses-constructs-openapi-rejects",
          before.get("addl") or before.get("union"),
          "ROUTING_SCHEMA is why responseJsonSchema is the primary path; if it "
          "no longer uses these, re-evaluate that choice deliberately")

    after = walk(gemini_head._sanitise_for_openapi(real), {})
    check("real-schema/translates",
          not after.get("addl") and not after.get("union"),
          "the OpenAPI fallback must accept the real schema, not just a fixture")

    # responseJsonSchema is sent verbatim, so it must at least be JSON-encodable.
    try:
        json.dumps(gemini_head._generation_config(real))
        check("real-schema/generation-config-serialises", True)
    except (TypeError, ValueError) as e:
        check("real-schema/generation-config-serialises", False, repr(e))

    cfg = gemini_head._generation_config(real)
    check("real-schema/primary-path-is-responseJsonSchema",
          "responseJsonSchema" in cfg and "responseSchema" not in cfg,
          "responseSchema would reject this schema outright — it is the "
          "fallback, never the default")
    check("real-schema/requests-json-mimetype",
          cfg.get("responseMimeType") == "application/json")


# --------------------------------------------------------------------------
# Shared quota. Two private counters would each think they owned the whole
# allowance and together permit ~2x the real cap.
# --------------------------------------------------------------------------
def test_shared_quota() -> None:
    start = gemini_quota.used_today()
    gemini_quota.record("routing")
    gemini_quota.record("content_generation")
    check("quota/one-counter-both-purposes",
          gemini_quota.used_today() == start + 2,
          "routing and content must increment the SAME counter")

    snap = gemini_quota.snapshot()
    check("quota/attributes-by-purpose",
          snap["by_purpose"].get("routing", 0) >= 1
          and snap["by_purpose"].get("content_generation", 0) >= 1,
          "'quota gone, no idea what spent it' is not debuggable")

    check("quota/stops-below-google-limit",
          gemini_quota.STOP_AT < gemini_quota.DAILY_LIMIT,
          "must brake before Google's hard 429, not at it")

    try:
        import gemini_content
        check("quota/content-module-shares-limit",
              gemini_content._STOP_AT == gemini_quota.STOP_AT,
              "gemini_content must not keep a private limit")
    except ModuleNotFoundError as e:
        skip("quota/content-module-shares-limit", f"{e} (third-party dep)")

    check("quota/corrupt-file-reads-as-zero",
          _corrupt_reads_zero(),
          "a corrupt counter must never be the reason a turn dies")


def test_quota_call_sites_exist() -> None:
    """A `gemini_quota.bump()` call against a module that only defines
    `record()` shipped once and was caught only by running the code. Compiling
    cannot catch it: an attribute error on a module is a RUNTIME error, and the
    call site sits behind a network round trip that never executes offline.

    So: parse every module for `gemini_quota.<attr>` references and assert each
    one actually exists. This is cheap, and it fails at verification time
    instead of on the user's first quota-consuming turn.
    """
    api = set(dir(gemini_quota))
    bad: list[str] = []
    seen = 0
    for fname in sorted(f for f in os.listdir(".") if f.endswith(".py")):
        try:
            with open(fname, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=fname)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "gemini_quota"):
                seen += 1
                if node.attr not in api:
                    bad.append(f"{fname}:{node.lineno} gemini_quota.{node.attr}")

    check("quota/every-call-site-resolves", not bad,
          "; ".join(bad) or f"{seen} references checked against the real module")
    check("quota/call-sites-actually-found", seen > 0,
          "if this finds nothing the check is vacuous and would pass forever")


def _corrupt_reads_zero() -> bool:
    path = os.environ["SENSEI_GEMINI_QUOTA_FILE"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json at all")
    try:
        return gemini_quota.used_today() == 0
    finally:
        os.remove(path)


# --------------------------------------------------------------------------
# THE CENTRAL GUARANTEE: no silent escalation to paid Claude.
# --------------------------------------------------------------------------
def test_no_silent_escalation() -> None:
    import claude_handler as ch

    saved_tier = os.environ.get("SENSEI_HEAD_TIER")
    saved_key = os.environ.get("GEMINI_API_KEY")
    saved_esc = os.environ.get("SENSEI_HEAD_ESCALATE_ON_CAP")
    try:
        # Free tier selected, key missing -> must REFUSE, not become Claude.
        os.environ["SENSEI_HEAD_TIER"] = "free"
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("SENSEI_HEAD_ESCALATE_ON_CAP", None)
        provider, payload = ch._head_dispatch()
        check("escalation/free-without-key-refuses",
              provider == "refuse",
              f"got provider={provider!r} — 'claude' here would silently bill "
              f"a user who explicitly chose the free tier")
        check("escalation/refusal-explains-how-to-fix",
              provider == "refuse" and "GEMINI_API_KEY" in str(payload),
              "a refusal the user cannot act on is just a dead end")

        # Free tier + key present -> gemini, still never claude.
        os.environ["GEMINI_API_KEY"] = "test-key-not-used-offline"
        provider, _ = ch._head_dispatch()
        check("escalation/free-with-key-uses-gemini",
              provider == "gemini", f"got {provider!r}")

        # Paid tier -> claude, as configured.
        os.environ["SENSEI_HEAD_TIER"] = "standard"
        provider, _ = ch._head_dispatch()
        check("escalation/standard-uses-claude",
              provider == "claude", f"got {provider!r}")
    finally:
        for k, v in (("SENSEI_HEAD_TIER", saved_tier),
                     ("GEMINI_API_KEY", saved_key),
                     ("SENSEI_HEAD_ESCALATE_ON_CAP", saved_esc)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_cap_refuses_by_default() -> None:
    """An exhausted cap must speak, not silently spend money."""
    saved = os.environ.get("SENSEI_HEAD_ESCALATE_ON_CAP")
    os.environ.pop("SENSEI_HEAD_ESCALATE_ON_CAP", None)
    try:
        check("cap/escalation-is-opt-in",
              gemini_head._escalate_on_cap() is False,
              "default must be refuse-and-explain, never auto-upgrade to paid")
        os.environ["SENSEI_HEAD_ESCALATE_ON_CAP"] = "1"
        check("cap/escalation-opt-in-works",
              gemini_head._escalate_on_cap() is True,
              "an operator who explicitly opts in must get it")
    finally:
        if saved is None:
            os.environ.pop("SENSEI_HEAD_ESCALATE_ON_CAP", None)
        else:
            os.environ["SENSEI_HEAD_ESCALATE_ON_CAP"] = saved


# --------------------------------------------------------------------------
# Reply shape: ask_akira must not learn which provider answered.
# --------------------------------------------------------------------------
def test_reply_duck_type() -> None:
    reply = gemini_head._refuse("test refusal text")
    check("shape/has-content-list",
          isinstance(getattr(reply, "content", None), list) and reply.content,
          "ask_akira reads reply.content[0].text")
    block = reply.content[0]
    check("shape/block-has-text", isinstance(getattr(block, "text", None), str))
    check("shape/block-type-is-text", getattr(block, "type", None) == "text")
    check("shape/has-stop-reason",
          hasattr(reply, "stop_reason"),
          "the caller inspects stop_reason")

    try:
        payload = json.loads(block.text)
    except ValueError as e:
        check("shape/refusal-is-valid-json", False, f"{e}")
        return
    check("shape/refusal-is-valid-json", True)
    check("shape/refusal-is-conversation-mode",
          payload.get("mode") == "conversation",
          "action mode would let a refusal EXECUTE something")
    check("shape/refusal-has-no-actions",
          not payload.get("actions") and not payload.get("action"),
          "a refusal must carry no executable action")
    check("shape/refusal-speaks",
          bool(payload.get("response")),
          "silent failure on a voice assistant is indistinguishable from a hang")
    check("shape/refusal-does-not-end-session",
          payload.get("end_session") is False,
          "quota exhaustion must not hang up on the user")

    # The Claude-side refusal shim must match the same contract.
    try:
        import claude_handler as ch
        shim = ch._refusal_reply("claude-side refusal")
        sp = json.loads(shim.content[0].text)
        check("shape/claude-shim-matches",
              sp.get("mode") == "conversation" and bool(sp.get("response"))
              and hasattr(shim, "stop_reason"),
              "both refusal paths must be indistinguishable downstream")
    except ModuleNotFoundError as e:
        skip("shape/claude-shim-matches", f"{e} (third-party dep)")


class _FakeResp:
    """The narrow slice of requests.Response that _parse touches.

    Deliberately NOT a mocked HTTP 200 with a valid body — that would only prove
    the mock. These are the MALFORMED shapes Google really returns (safety
    blocks, truncation, empty candidates), where the dangerous outcome is an
    empty plan being read as 'correctly decided to do nothing'.
    """

    def __init__(self, payload, *, raw: str | None = None):
        self._payload = payload
        self.status_code = 200
        self.text = raw if raw is not None else json.dumps(payload)

    def json(self):
        if self._payload is _INVALID:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


_INVALID = object()


def _refused(reply) -> bool:
    """True if this reply is a spoken, non-executable refusal."""
    try:
        payload = json.loads(reply.content[0].text)
    except (AttributeError, IndexError, ValueError):
        return False
    return (payload.get("mode") == "conversation"
            and bool(payload.get("response"))
            and not payload.get("actions")
            and not payload.get("action"))


def test_parse_fails_closed() -> None:
    """Every malformed response must become a refusal, never an empty plan.

    {"mode": "command", "actions": []} reaching the executor is indistinguishable
    from a correct decision to do nothing — that is the silent failure this whole
    layer exists to prevent.
    """
    cases = [
        ("non-json-body", _FakeResp(_INVALID, raw="<html>502</html>")),
        ("prompt-blocked", _FakeResp({"promptFeedback": {"blockReason": "SAFETY"}})),
        ("no-candidates", _FakeResp({"candidates": []})),
        ("missing-candidates-key", _FakeResp({})),
        ("empty-parts", _FakeResp(
            {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]})),
        ("whitespace-only-text", _FakeResp(
            {"candidates": [{"content": {"parts": [{"text": "   \n"}]},
                             "finishReason": "STOP"}]})),
        ("safety-finish", _FakeResp(
            {"candidates": [{"content": {"parts": [{"text": "{}"}]},
                             "finishReason": "SAFETY"}]})),
        ("recitation-finish", _FakeResp(
            {"candidates": [{"content": {"parts": [{"text": "{}"}]},
                             "finishReason": "RECITATION"}]})),
        ("truncated-before-any-text", _FakeResp(
            {"candidates": [{"content": {"parts": []},
                             "finishReason": "MAX_TOKENS"}]})),
        ("candidate-not-a-dict-shaped-content", _FakeResp(
            {"candidates": [{"content": None, "finishReason": "STOP"}]})),
    ]
    for name, resp in cases:
        try:
            reply = gemini_head._parse(resp, used=1)
        except Exception as e:                                    # noqa: BLE001
            check(f"failclosed/{name}", False,
                  f"raised {e!r} into the voice loop instead of refusing")
            continue
        check(f"failclosed/{name}", _refused(reply),
              "a malformed response must refuse, not become an empty plan")

    # Truncation WITH partial text is the one case that passes text through —
    # but it must be flagged as max_tokens so downstream refuses to execute it.
    trunc = gemini_head._parse(_FakeResp(
        {"candidates": [{"content": {"parts": [{"text": '{"mode": "comm'}]},
                         "finishReason": "MAX_TOKENS"}]}), used=1)
    check("failclosed/truncated-marks-max-tokens",
          trunc.stop_reason == "max_tokens",
          "ask_akira keys on this exact string to reject a cut-off envelope; "
          "'end_turn' here would hand a half-parsed plan to the executor")

    # And a genuinely well-formed response must NOT be refused, or the gate
    # above would pass trivially by refusing everything.
    good = gemini_head._parse(_FakeResp(
        {"candidates": [{"content": {"parts": [{"text": '{"mode": "conversation",'
                                                        ' "response": "hi"}'}]},
                         "finishReason": "STOP"}]}), used=1)
    check("failclosed/valid-response-passes-through",
          good.stop_reason == "end_turn",
          "if this fails the fail-closed checks are vacuous — everything refuses")


def test_capped_head_refuses_end_to_end() -> None:
    """Cap exhaustion driven through route(), not just the policy helper.

    The pre-flight cap check sits before the HTTP call, so this runs fully
    offline with a bogus key: if it ever reached the network the test would fail
    loudly rather than quietly passing.
    """
    saved_key = os.environ.get("GEMINI_API_KEY")
    saved_esc = os.environ.get("SENSEI_HEAD_ESCALATE_ON_CAP")
    path = os.environ["SENSEI_GEMINI_QUOTA_FILE"]
    try:
        os.environ["GEMINI_API_KEY"] = "bogus-key-must-not-be-used"
        os.environ.pop("SENSEI_HEAD_ESCALATE_ON_CAP", None)
        # Exhaust the counter directly rather than making STOP_AT real calls.
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"date": __import__("datetime").date.today().isoformat(),
                       "count": gemini_quota.STOP_AT + 5,
                       "by_purpose": {"head_routing": gemini_quota.STOP_AT + 5}}, f)
        check("cap/exhausted-precondition", gemini_quota.exhausted(),
              "the rest of this test is meaningless if the cap isn't reached")

        reply = gemini_head.route([{"role": "user", "content": "open notepad"}],
                                  [{"text": "system"}], None)
        check("cap/capped-route-refuses", _refused(reply),
              "a capped Free Head must speak a refusal, not execute or raise")
        spoken = json.loads(reply.content[0].text)["response"].lower()
        check("cap/refusal-mentions-the-cap",
              "limit" in spoken or "allowance" in spoken or "used up" in spoken,
              f"user must hear WHY: {spoken[:70]}")
        check("cap/refusal-does-not-auto-upgrade",
              "won't do that on my own" in spoken or "switch to the paid" in spoken,
              "the refusal must state that it is NOT silently upgrading")

        # Opted in -> raises the explicit escalation signal, never a silent switch.
        os.environ["SENSEI_HEAD_ESCALATE_ON_CAP"] = "1"
        try:
            gemini_head.route([{"role": "user", "content": "x"}],
                              [{"text": "s"}], None)
            check("cap/optin-raises-explicit-signal", False,
                  "escalation must be an exception a caller opts into catching")
        except gemini_head.CapReachedEscalate:
            check("cap/optin-raises-explicit-signal", True,
                  "loud, catchable, and impossible to reach by accident")
    finally:
        for k, v in (("GEMINI_API_KEY", saved_key),
                     ("SENSEI_HEAD_ESCALATE_ON_CAP", saved_esc)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            os.remove(path)
        except OSError:
            pass


def test_no_key_route_refuses_offline() -> None:
    """No key -> refuse before any network attempt."""
    saved = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ.pop("GEMINI_API_KEY", None)
        reply = gemini_head.route([{"role": "user", "content": "x"}],
                                  [{"text": "s"}], None)
        check("failclosed/no-key-refuses-without-network", _refused(reply),
              "must not attempt a request it knows cannot succeed")
    finally:
        if saved is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = saved


def test_readiness_is_offline() -> None:
    saved = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ.pop("GEMINI_API_KEY", None)
        ok, reason = gemini_head.readiness()
        check("readiness/no-key-not-ready", not ok)
        check("readiness/no-key-names-the-var",
              "GEMINI_API_KEY" in reason, reason[:70])
        os.environ["GEMINI_API_KEY"] = "x"
        ok, _ = gemini_head.readiness()
        check("readiness/with-key-ready", ok,
              "readiness is a CONFIG check — it must not require a network call, "
              "because a startup banner calls it")
    finally:
        if saved is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = saved


def test_tiers_integration() -> None:
    try:
        import tiers
    except ModuleNotFoundError as e:
        skip("tiers/free-head-live", f"{e} (tiers' own dep)")
        return

    saved = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GEMINI_API_KEY"] = "x"
        spec = tiers.head(tiers.FREE)
        check("tiers/free-head-live", bool(spec),
              "Free Head must resolve once the adapter and key exist")
        check("tiers/free-head-is-gemini",
              getattr(spec, "provider", None) == "gemini")
        check("tiers/free-budget-is-zero-not-none",
              getattr(spec, "daily_budget_usd", None) == 0.0,
              "None means UNMETERED in this dataclass — the free tier is the "
              "opposite of unmetered")

        os.environ.pop("GEMINI_API_KEY", None)
        spec = tiers.head(tiers.FREE)
        check("tiers/free-head-unavailable-without-key",
              not spec, "missing config must report Unavailable, not a live spec")
    finally:
        if saved is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = saved


def main() -> int:
    print("=" * 68)
    print("Gemini Head adapter verification (Prompt 6)")
    print("=" * 68)
    for fn in (test_schema_translation, test_real_routing_schema,
               test_shared_quota, test_quota_call_sites_exist,
               test_no_silent_escalation, test_cap_refuses_by_default,
               test_parse_fails_closed, test_capped_head_refuses_end_to_end,
               test_no_key_route_refuses_offline,
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
