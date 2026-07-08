"""
netflix_selector_diagnostic.py — standalone diagnostic for Netflix player selectors.

Purpose: run against an already-authenticated CDP-attached browser session with a
Netflix watch page in Akira's tab. Prints every button[aria-label] and every
element carrying a data-uia attribute currently in the DOM, so that
netflix_control()'s menu_actions placeholder selectors can be replaced with
real, verified values.

Does NOT touch executor.py logic. Does NOT click anything. Read-only inspection.

Usage:
    python netflix_selector_diagnostic.py

Tip: for overlay items (episodes list, audio/subtitle menu), manually open the
overlay in the browser first, then run this script again while it's visible —
overlay contents are usually only in the DOM while the overlay is open.
"""

from executor import get_browser, _last_browser_name


def main() -> None:
    browser = get_browser(_last_browser_name)

    # Use Akira's working tab if it exists, otherwise stay on the current tab
    akira_tab = getattr(browser, "_akira_tab", None)
    if akira_tab and akira_tab in browser.window_handles:
        browser.switch_to.window(akira_tab)

    url = browser.current_url or ""
    print(f"[diagnostic] current URL: {url}")
    if "netflix.com" not in url:
        print("[diagnostic] WARNING: current tab is not netflix.com — "
              "output below may not be Netflix player elements.")

    # All data extracted in one JS pass; parameters passed via arguments[] only
    # (no string interpolation into JS — matches the codebase's known-good pattern).
    data = browser.execute_script("""
        function visible(el) {
            var r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        }
        function describe(el) {
            return {
                tag: el.tagName.toLowerCase(),
                ariaLabel: el.getAttribute('aria-label'),
                dataUia: el.getAttribute('data-uia'),
                role: el.getAttribute('role'),
                text: (el.textContent || '').trim().slice(0, 80),
                visible: visible(el)
            };
        }
        var buttons = Array.from(document.querySelectorAll('button[aria-label]')).map(describe);
        var uias = Array.from(document.querySelectorAll('[data-uia]')).map(describe);
        return { buttons: buttons, uias: uias };
    """)

    buttons = data.get("buttons", [])
    uias = data.get("uias", [])

    print(f"\n=== button[aria-label] elements ({len(buttons)}) ===")
    for b in buttons:
        vis = "VISIBLE" if b.get("visible") else "hidden "
        print(f"  [{vis}] aria-label={b.get('ariaLabel')!r}"
              f"  data-uia={b.get('dataUia')!r}"
              f"  text={b.get('text')!r}")

    print(f"\n=== elements with data-uia attribute ({len(uias)}) ===")
    for u in uias:
        vis = "VISIBLE" if u.get("visible") else "hidden "
        print(f"  [{vis}] <{u.get('tag')}> data-uia={u.get('dataUia')!r}"
              f"  aria-label={u.get('ariaLabel')!r}"
              f"  role={u.get('role')!r}"
              f"  text={u.get('text')!r}")

    print("\n[diagnostic] done. Paste this full output back so menu_actions "
          "selectors can be updated with verified values.")


if __name__ == "__main__":
    main()
