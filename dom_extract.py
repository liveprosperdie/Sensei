"""
dom_extract.py — extract interactive elements from a live page.

Moved out of executor.py (which imports winreg/win32 and only loads on
Windows) so the extraction used in production is byte-for-byte the same
one exercised by the headless verification harness. Only needs a selenium
driver-like object exposing execute_script/current_url.
"""

from __future__ import annotations

_EXTRACT_SCRIPT = """
    try {
        const items = [];
        let idx = 0;
        const maxItems = arguments[0];

        // Clear indices from any previous scan — indices go stale between
        // scans, and a leftover data-akira-index would make the dedupe
        // check below skip every element on a re-scan.
        document.querySelectorAll('[data-akira-index]').forEach(el =>
            el.removeAttribute('data-akira-index'));

        function getText(el) {
            try {
                return (el.innerText || el.textContent || el.value || el.placeholder ||
                        el.getAttribute('aria-label') || el.getAttribute('title') ||
                        el.getAttribute('alt') || el.getAttribute('name') || '')
                       .replace(/\\s+/g,' ').trim().slice(0, 200);
            } catch(e) {
                return '';
            }
        }

        function isVisible(el) {
            try {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                if (r.width < 5 || r.height < 5) return false;
                const s = window.getComputedStyle(el);
                return s.visibility !== 'hidden' && s.display !== 'none';
            } catch(e) {
                return false;
            }
        }

        function addElement(el, role, text, href = null) {
            try {
                if (idx >= maxItems) return false;
                // Dedupe: passes overlap (image/video anchors are also
                // a[href]) — double-adds corrupted ordinal counting.
                if (el.hasAttribute('data-akira-index')) return true;
                if (!text && role !== 'input' && role !== 'textbox' && role !== 'image') return true;
                el.setAttribute('data-akira-index', String(idx));
                const r = el.getBoundingClientRect();
                items.push({index: idx, role: role, text: text, href: href,
                            x: Math.round(r.left + window.scrollX),
                            y: Math.round(r.top + window.scrollY),
                            w: Math.round(r.width), h: Math.round(r.height)});
                idx++;
                return true;
            } catch(e) {
                return true;
            }
        }

        // 0. PRIORITY: image search results. An anchor whose content is
        // dominated by a real <img> is an image result, NOT a nav link —
        // this is the role distinction whose absence caused ordinal/fuzzy
        // matching to click page chrome on Google Images.
        try {
            document.querySelectorAll('a[href]').forEach(el => {
                if (!isVisible(el)) return;
                const img = el.querySelector('img');
                if (!img) return;
                const ir = img.getBoundingClientRect();
                const ar = el.getBoundingClientRect();
                // real thumbnail: >=50px each way and fills >=50% of anchor
                if (ir.width < 50 || ir.height < 50) return;
                if ((ir.width * ir.height) < 0.5 * (ar.width * ar.height)) return;
                const text = (img.getAttribute('alt') || getText(el) || '')
                             .replace(/\\s+/g,' ').trim().slice(0, 200);
                addElement(el, 'image', text || 'image result', el.href);
            });
        } catch(e) {}

        // 1. PRIORITY: YouTube video thumbnails (most common miss)
        try {
            document.querySelectorAll('ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer').forEach(el => {
                if (!isVisible(el)) return;
                const titleEl = el.querySelector('#video-title, .title');
                const thumbnailEl = el.querySelector('a#thumbnail');
                if (titleEl && thumbnailEl) {
                    const text = getText(titleEl);
                    const href = thumbnailEl.href;
                    if (text) addElement(thumbnailEl, 'video', text, href);
                }
            });
        } catch(e) {}

        // 2. Address bar (omnibox) - critical for URL editing
        try {
            const omnibox = document.querySelector('input[type="text"][role="combobox"]') ||
                            document.querySelector('input.omnibox') ||
                            document.querySelector('#searchInput');
            if (omnibox && isVisible(omnibox)) {
                addElement(omnibox, 'addressbar', 'address bar', null);
            }
        } catch(e) {}

        // 3. All standard links
        try {
            document.querySelectorAll('a[href]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el);
                if (text) addElement(el, 'link', text, el.href);
            });
        } catch(e) {}

        // 4. Buttons (explicit and implicit)
        try {
            document.querySelectorAll('button, [role="button"], [onclick], input[type="button"], input[type="submit"]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el);
                addElement(el, 'button', text || 'button', null);
            });
        } catch(e) {}

        // 5. Form inputs
        try {
            document.querySelectorAll('input:not([type="hidden"]), textarea, select').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el) || el.type || 'input';
                addElement(el, 'input', text, null);
            });
        } catch(e) {}

        // 6. Video controls (play/pause buttons)
        try {
            document.querySelectorAll('video, [class*="play"], [class*="pause"], [aria-label*="play"], [aria-label*="pause"]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el) || el.className.split(' ').find(c => c.includes('play') || c.includes('pause')) || 'media control';
                if (text) addElement(el, 'media', text, null);
            });
        } catch(e) {}

        // 7. Clickable divs with role or aria-label (common in modern web apps)
        try {
            document.querySelectorAll('[role="menuitem"], [role="tab"], [role="option"], [role="checkbox"], [role="radio"], [aria-label][onclick]').forEach(el => {
                if (!isVisible(el)) return;
                const text = getText(el);
                if (text) addElement(el, el.getAttribute('role') || 'clickable', text, null);
            });
        } catch(e) {}

        return items;
    } catch(e) {
        console.error('Element extraction failed:', e);
        return [];
    }
"""

# Cheap single-node probe used for staleness checks BETWEEN clicks —
# re-running the full extraction just to verify one element added a full
# page re-scan of latency to every click.
_PROBE_SCRIPT = """
    const el = document.querySelector('[data-akira-index="' + arguments[0] + '"]');
    if (!el) return null;
    const text = (el.innerText || el.textContent || el.value || el.placeholder ||
                  el.getAttribute('aria-label') || el.getAttribute('title') ||
                  el.getAttribute('alt') || el.getAttribute('name') || '')
                 .replace(/\\s+/g,' ').trim().slice(0, 200);
    return {text: text, href: el.href || null};
"""


def extract_interactive_elements(driver, max_elements: int = 150) -> list[dict]:
    """Extract interactive elements using aggressive DOM approach (no CDP
    tree overhead). Captures image results, YouTube thumbnails, the address
    bar, and all clickable elements."""
    try:
        elements = driver.execute_script(_EXTRACT_SCRIPT, max_elements)
    except Exception as e:
        print(f"[EXTRACT] Script execution failed: {e}")
        return []

    current_url = driver.current_url if hasattr(driver, 'current_url') else 'page'
    if not elements:
        print(f"[EXTRACT] No elements found on {current_url[:50] if current_url else 'page'}")
        return []
    print(f"[EXTRACT] Found {len(elements)} elements on {current_url[:50] if current_url else 'page'}")
    return elements


def probe_element(driver, index: int) -> dict | None:
    """O(1) staleness probe: current text/href of the node still stamped
    with data-akira-index=`index`, or None if the stamp is gone. Lets
    click paths skip a full re-extraction when nothing changed."""
    try:
        return driver.execute_script(_PROBE_SCRIPT, index)
    except Exception as e:
        print(f"[EXTRACT] probe failed: {e}")
        return None
