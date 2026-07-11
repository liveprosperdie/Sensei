"""Investigation-only reproduction for Bug 1 (prompt contents) and Bug 2
(wrong-element fuzzy match). Prints real values; changes nothing."""
import re
import sys

# ── Bug 1: what would a fresh process load? ──────────────────────────────────
print("=" * 60)
print("BUG 1: in-memory AKIRA_PROMPT check (fresh import)")
print("=" * 60)
try:
    import claude_handler
    prompt = claude_handler.AKIRA_PROMPT
    print("[BOOT] claude_handler loaded from:", claude_handler.__file__)
    for needle in ("github_control", "clone repo", "amazon_control", "NEVER use click for GitHub"):
        print(f"  contains {needle!r}: {needle in prompt}")
    HAVE_MODULE = True
except Exception as e:
    print(f"  import failed in this sandbox ({e!r}) — falling back to disk parse")
    src = open("claude_handler.py").read()
    m = re.search(r'AKIRA_PROMPT\s*=\s*(?:f?""")(.*?)"""', src, re.DOTALL)
    prompt = m.group(1) if m else ""
    for needle in ("github_control", "clone repo", "amazon_control", "NEVER use click for GitHub"):
        print(f"  contains {needle!r} (disk): {needle in prompt}")
    HAVE_MODULE = False

# ── Bug 2: exact reproduction of the failing match ───────────────────────────
print()
print("=" * 60)
print("BUG 2: reproduce 'Profile' beating 'Repositories'")
print("=" * 60)

candidates = ["Create new repository", "Profile", "Repositories", "Stars", "Gists"]
elements = [{"index": i, "text": t, "role": "link", "href": "https://github.com/x"}
            for i, t in enumerate(candidates)]
instruction = "Repositories in the top navigation or profile menu"
instruction_lower = instruction.lower()
instruction_words = set(re.findall(r"\w+", instruction_lower))
print(f"instruction: {instruction!r}")
print(f"instruction words: {sorted(instruction_words)}")
print()

# Phase 1 trace: bidirectional substring, FIRST match returns immediately
print("--- Phase 1 (substring, first-match-wins) trace ---")
phase1_winner = None
for el in elements:
    text_lower = el["text"].lower()
    fwd = instruction_lower in text_lower
    rev = text_lower in instruction_lower
    hit = fwd or rev
    print(f"  idx={el['index']} {el['text']!r:26} instr-in-text={fwd}  text-in-instr={rev}  -> {'MATCH (returns here)' if hit and phase1_winner is None else ('would also match' if hit else 'no')}")
    if hit and phase1_winner is None:
        phase1_winner = el["index"]
print(f"Phase 1 result: index={phase1_winner} text={candidates[phase1_winner]!r}")
print()

# Phase 2 scores (what WOULD have happened if Phase 1 didn't exist)
print("--- Phase 2 (word overlap) scores, for comparison ---")
for pos, el in enumerate(elements):
    text_words = set(re.findall(r"\w+", el["text"].lower()))
    overlap = len(instruction_words & text_words)
    ratio = overlap / len(instruction_words)
    qualifies = overlap >= 2 or ratio >= 0.5
    bonus = (50 - pos) / 50.0
    score = overlap + bonus
    print(f"  idx={el['index']} {el['text']!r:26} overlap={overlap} ratio={ratio:.2f} "
          f"qualifies={qualifies} score={score:.2f}")

# Confirm against the real function if importable
if HAVE_MODULE:
    print()
    print("--- Real find_element_index() on the same input ---")
    result = claude_handler.find_element_index(elements, instruction)
    print(f"REAL RESULT: index={result} text={candidates[result]!r}")
