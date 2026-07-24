"""
Headless end-to-end verification of the image search -> picker -> pick ->
download flow, plus the chain guard and the O(1) click staleness probe.

Drives the REAL production modules (image_flow, action_guard,
element_matcher, dom_extract) against a REAL headless Chrome — no mocks of
any code under test. Only the platform hooks (browser navigation) are wired
to the harness driver, exactly as executor.py wires them to the user's
browser on Windows.

Run:  python tests/verify_headless.py
Exit code 0 = every check passed.
"""

import os
import sys
import glob
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import image_flow
import action_guard
from element_matcher import find_element_index
from dom_extract import extract_interactive_elements, probe_element

CHECKS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--disable-gpu")
    o.add_argument("--window-size=1400,900")
    return webdriver.Chrome(options=o)


def main() -> int:
    driver = make_driver()
    print(f"[harness] headless Chrome up: {driver.capabilities['browserVersion']}")

    # Wire the REAL platform hooks the way executor.py does on Windows.
    image_flow.configure(navigate=driver.get)

    # ── 1. search_image: candidates + visible picker navigation ─────────────
    print("\n=== 1. search_image('mountain sunset') ===")
    res = image_flow.search_image("mountain sunset")
    check("search_image succeeds", res.get("success") is True, res.get("message", "")[:100])
    n = len(image_flow._candidates)
    check("4-6 candidates stored", 4 <= n <= 6, f"{n} candidates")
    check("nothing downloaded by search",
          not res.get("path"), "no 'path' in search result")

    cur = driver.current_url
    check("browser visibly navigated to local picker page",
          cur.startswith("file://") and "akira_image_picker" in cur, cur)

    time.sleep(2)  # allow lazy thumbnails to fetch
    imgs = driver.execute_script(
        "return Array.from(document.images).map(i => "
        "({ok: i.complete && i.naturalWidth > 0, alt: i.alt}))")
    loaded = sum(1 for i in imgs if i["ok"])
    check("picker shows the same number of cards as candidates",
          len(imgs) == n, f"{len(imgs)} <img> tags")
    check("real thumbnails rendered (>=1 pixel-loaded image)",
          loaded >= 1, f"{loaded}/{len(imgs)} thumbnails fully loaded")
    nums = driver.execute_script(
        "return Array.from(document.querySelectorAll('.num')).map(e => e.textContent)")
    check("position numbers 1..N visible on screen",
          nums == [str(i + 1) for i in range(n)], str(nums))
    spoken = res.get("message", "")
    check("spoken list matches screen (every position number spoken)",
          all(f"number {i + 1}" in spoken for i in range(n)), spoken[:120] + "...")

    # ── 2. chain guard: the LLM cannot force a same-turn download ───────────
    print("\n=== 2. action_guard.sanitize_actions ===")
    bad_chain = [
        {"action": "search_image", "parameter": "mountain sunset"},
        {"action": "download_image", "parameter": "first"},
        {"action": "download_image", "parameter": "second"},
    ]
    cleaned, notes = action_guard.sanitize_actions(bad_chain)
    kept = [s["action"] for s in cleaned]
    check("search+download same chain: downloads dropped",
          kept == ["search_image"], f"kept={kept}, notes={notes}")

    dbl = [{"action": "download_image", "parameter": "first"},
           {"action": "download_image", "parameter": "second"}]
    cleaned2, notes2 = action_guard.sanitize_actions(dbl)
    check("double download in one chain: only first kept",
          [s["action"] for s in cleaned2] == ["download_image"]
          and cleaned2[0]["parameter"] == "first", f"notes={notes2}")

    ok_chain = [{"action": "open_website", "parameter": "youtube.com"},
                {"action": "download_image", "parameter": "third"}]
    cleaned3, _ = action_guard.sanitize_actions(ok_chain)
    check("legit later-turn download chain untouched",
          [s["action"] for s in cleaned3] == ["open_website", "download_image"])

    # ── 3. strict pick resolution ────────────────────────────────────────────
    print("\n=== 3. resolve_pick strictness ===")
    cands = image_flow._candidates
    third = image_flow.resolve_pick(cands, "the third one")
    check("'the third one' -> candidate #3", third is cands[2])
    check("'3' -> candidate #3", image_flow.resolve_pick(cands, "3") is cands[2])
    check("'last' -> final candidate", image_flow.resolve_pick(cands, "last") is cands[-1])
    check("out-of-range number -> None (no silent default)",
          image_flow.resolve_pick(cands, str(n + 5)) is None)
    check("garbage pick -> None (no silent default)",
          image_flow.resolve_pick(cands, "zzqx flurble") is None)

    # ── 4. download_image: user says 'the third one' -> ONE correct file ────
    print("\n=== 4. download_image('the third one') ===")
    pics = os.path.expanduser("~/Pictures")
    os.makedirs(pics, exist_ok=True)
    before = set(glob.glob(os.path.join(pics, "*")))

    dl = image_flow.download_image("the third one")
    check("download succeeds", dl.get("success") is True, dl.get("message", "")[:100])

    after = set(glob.glob(os.path.join(pics, "*")))
    new = sorted(after - before)
    check("EXACTLY one new file on disk", len(new) == 1, str(new))
    if new:
        size = os.path.getsize(new[0])
        check("file is a real image (>10KB, image magic bytes)",
              size > 10_000 and open(new[0], "rb").read(4)[:3] in
              (b"\xff\xd8\xff", b"\x89PN", b"GIF", b"RIF"),
              f"{new[0]} ({size} bytes)")
        check("returned path matches file on disk",
              dl.get("path") == new[0], dl.get("path", ""))

    # unique-name property: same pick again must NOT overwrite
    dl2 = image_flow.download_image("the third one")
    newer = sorted(set(glob.glob(os.path.join(pics, "*"))) - after)
    check("repeat download -> new unique filename, no overwrite",
          dl2.get("success") and len(newer) == 1 and newer[0] != new[0],
          str(newer))

    # ── 5. no-search-yet download is refused ────────────────────────────────
    print("\n=== 5. download without search ===")
    saved = image_flow._candidates
    image_flow._candidates = []
    refused = image_flow.download_image("a picture of a cat")
    check("download with no prior search -> refused, nothing downloaded",
          refused.get("success") is False and not refused.get("path"),
          refused.get("message", "")[:90])
    image_flow._candidates = saved

    # ── 6. DOM extraction + O(1) staleness probe + matcher (live page) ──────
    print("\n=== 6. dom_extract + probe_element + find_element_index ===")
    driver.get("https://example.com")
    els = extract_interactive_elements(driver)
    check("extracts elements from live page", len(els) >= 1,
          f"{len(els)} elements: {[e['text'][:30] for e in els[:3]]}")

    idx = find_element_index(els, "click the learn more link")
    check("matcher finds the 'Learn more' link", idx is not None and
          "learn more" in els[idx]["text"].lower(),
          f"idx={idx}, text={els[idx]['text'] if idx is not None else None!r}")

    if idx is not None:
        t0 = time.perf_counter()
        p = probe_element(driver, idx)
        probe_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        extract_interactive_elements(driver)
        full_ms = (time.perf_counter() - t0) * 1000
        check("O(1) probe agrees with extraction",
              p is not None and p["text"] == els[idx]["text"]
              and p["href"] == els[idx]["href"],
              f"probe={p}")
        check("probe is faster than full re-extract",
              probe_ms < full_ms, f"probe {probe_ms:.1f}ms vs full {full_ms:.1f}ms")
        stale = probe_element(driver, 9999)
        check("out-of-range probe -> None (triggers full re-extract path)",
              stale is None)

    driver.quit()

    passed, total = sum(CHECKS), len(CHECKS)
    print(f"\n{'=' * 60}\nRESULT: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
