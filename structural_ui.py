"""
structural_ui.py — resolve STRUCTURAL page controls (tabs, profile pickers,
nav menus) and history navigation, separately from content matching.

Why this is its own pipeline instead of more rules in element_matcher:

  A filter tab, a profile avatar and a browser back button are not "content".
  Routing them through the content matcher actively broke them:

    * "the Images tab" set role_intent='image' in element_matcher, which hard-
      filtered the pool down to actual image RESULTS — guaranteeing the tab
      itself was excluded and a photo got clicked instead.
    * Netflix profile avatars were extracted as role='image' with the text
      'image result' (the profile NAME lives in a sibling span), so a spoken
      name could never match them.
    * "go back" has no page element at all — the back button lives in browser
      chrome, outside the DOM. Searching the DOM for it was unwinnable, and the
      failure fell through to a full-screen vision guess that clicked whatever
      app happened to be in front.

  So: classify the instruction FIRST. If it names a structural control, resolve
  it with site-aware selectors. Only genuine content requests reach the content
  matcher. Nav intents never touch the DOM.

Deliberately free of Windows/TTS imports so it can be exercised headlessly.
"""

from __future__ import annotations

import difflib
import re

# ── Intent classification ─────────────────────────────────────────────────────

# History navigation. Kept deliberately specific: "next page" is EXCLUDED
# because on search results that means a pagination link (real content), not
# history.forward(). Hijacking it would break paging.
_NAV_PATTERNS: list[tuple[str, str]] = [
    (r'\b(?:go|navigate|take\s+me|move)\s+back\b', 'back'),
    (r'\bback\s+(?:button|arrow)\b', 'back'),
    (r'\b(?:previous|last)\s+page\b', 'back'),
    (r'^\s*back\s*$', 'back'),
    (r'\b(?:go|navigate|move)\s+forward\b', 'forward'),
    (r'\bforward\s+(?:button|arrow)\b', 'forward'),
    (r'^\s*forward\s*$', 'forward'),
    (r'\b(?:reload|refresh)\b(?:\s+(?:the\s+)?page)?', 'reload'),
]

# Words that are never a real tab/profile NAME — guards against classifying
# "switch tab", "new tab", "close tab" (which are separate browser actions)
# as a structural in-page tab click.
_NOT_A_NAME = {
    '', 'a', 'an', 'the', 'this', 'that', 'next', 'previous', 'prev', 'new',
    'other', 'another', 'last', 'first', 'current', 'open', 'close', 'switch',
    'my', 'to', 'on', 'in', 'of', 'and', 'or', 'browser', 'chrome', 'edge',
}


def _clean_name(raw: str | None) -> str:
    """Strip filler words a spoken instruction wraps a name in."""
    if not raw:
        return ''
    name = re.sub(r'\b(?:please|click|on|the|go|to|switch|open|select|change)\b',
                  ' ', raw.lower())
    return re.sub(r'\s+', ' ', name).strip(' .,')


def classify_structural_intent(instruction: str) -> tuple[str, str] | None:
    """Return ('nav', 'back'|'forward'|'reload'), ('tab', name),
    ('profile', name), ('nav_menu', name), or None when the instruction is a
    normal content request that should go to element_matcher.

    Order matters: nav is checked first because "go back" must never be
    interpreted as a hunt for an element whose text says "back"."""
    if not instruction:
        return None
    text = instruction.lower().strip()

    for pattern, direction in _NAV_PATTERNS:
        if re.search(pattern, text):
            print(f"[STRUCT] intent=nav/{direction} from {instruction!r}")
            return ('nav', direction)

    # Profile: "switch to Shrey profile", "Shrey's profile", "profile Shrey"
    for pattern in (r'\b([\w\s\'-]+?)(?:\'s)?\s+profile\b',
                    r'\bprofile\s+(?:of\s+|for\s+|to\s+)?([\w\s\'-]+)$'):
        m = re.search(pattern, text)
        if m:
            name = _clean_name(m.group(1))
            if name not in _NOT_A_NAME:
                print(f"[STRUCT] intent=profile name={name!r}")
                return ('profile', name)
    # Bare "switch profile" — no name, let the resolver list the options.
    if re.search(r'\b(?:switch|change)\s+profile\b', text):
        print("[STRUCT] intent=profile name='' (no name given)")
        return ('profile', '')

    # Tab: "the Images tab", "switch to Videos tab", "News tab"
    m = re.search(r'\b([\w\s\'-]+?)\s+tabs?\b', text)
    if m:
        name = _clean_name(m.group(1))
        if name and name not in _NOT_A_NAME:
            print(f"[STRUCT] intent=tab name={name!r}")
            return ('tab', name)

    # Google's filter chips are often spoken without the word "tab" at all
    # ("click images", "show me videos") — but ONLY treat as a tab when the
    # instruction is just that bare word, otherwise "click the third image"
    # would be stolen from the content matcher.
    if re.fullmatch(r'(?:click\s+|open\s+|show\s+me\s+|go\s+to\s+)?'
                    r'(images|videos|news|shopping|maps|books|web|short\s+videos|forums)',
                    text):
        name = _clean_name(re.sub(r'^(?:click|open|show\s+me|go\s+to)\s+', '', text))
        print(f"[STRUCT] intent=tab name={name!r} (bare filter word)")
        return ('tab', name)

    return None


# ── Fuzzy name matching ───────────────────────────────────────────────────────

def fuzzy_name_match(spoken: str, names: list[str], cutoff: float = 0.6) -> int | None:
    """Index of the best match for `spoken` in `names`, or None.

    Speech recognition truncates and mangles proper nouns ("Shre" for
    "Shrey", "Twich" for "Twitch"), so exact comparison is not enough.
    Tiered: exact -> prefix -> substring -> difflib ratio."""
    if not names:
        return None
    want = (spoken or '').lower().strip()
    if not want:
        return None
    lowered = [(n or '').lower().strip() for n in names]

    for i, n in enumerate(lowered):
        if n == want:
            print(f"[STRUCT] name exact match {names[i]!r}")
            return i
    for i, n in enumerate(lowered):
        if n.startswith(want) or want.startswith(n):
            print(f"[STRUCT] name prefix match {want!r} -> {names[i]!r}")
            return i
    for i, n in enumerate(lowered):
        if want in n or n in want:
            print(f"[STRUCT] name substring match {want!r} -> {names[i]!r}")
            return i
    close = difflib.get_close_matches(want, lowered, n=1, cutoff=cutoff)
    if close:
        i = lowered.index(close[0])
        print(f"[STRUCT] name fuzzy match {want!r} -> {names[i]!r}")
        return i
    return None


# ── Structural collection ─────────────────────────────────────────────────────

# Site-aware selectors first, generic ARIA last. Google moved image search from
# `tbm=isch` to `udm=2`, so both are matched — a single hardcoded form would
# silently stop working.
_TAB_SELECTORS = [
    '#hdtb-msb a[href]',                      # Google filter bar (classic)
    '#hdtb-msb [role="listitem"] a[href]',
    'div[role="navigation"] a[href*="udm="]',  # Google (current)
    'div[role="navigation"] a[href*="tbm="]',  # Google (legacy)
    'a[href*="udm="]',
    'a[href*="tbm="]',
    '[role="tablist"] [role="tab"]',           # generic ARIA
    '[role="tab"]',
    'nav [aria-selected]',
]

_PROFILE_SELECTORS = [
    '[data-uia*="action-select-profile"]',
    '[data-uia*="profile-link"]',
    'a[href*="switchProfile"]',
    '.profile-link',
    '.choose-profile .profile',
    'li.profile a',
    '.profile-icon',
]

# Where a control's human-readable NAME lives when it is not the element's own
# text. This is the fix for profiles extracting as 'image result': the avatar
# is an <img>, the name is a sibling span.
_LABEL_SUBSELECTORS = [
    '.profile-name', '[data-uia*="profile-name"]', '.profile-title',
    'span', 'div',
]

_NAV_MENU_SELECTORS = [
    'nav a[href]', 'header a[href]', '[role="navigation"] a[href]',
    '[role="menuitem"]',
]

_COLLECT_SCRIPT = r"""
    const sels = arguments[0], labelSels = arguments[1];
    const out = [];
    let n = 0;
    document.querySelectorAll('[data-akira-struct]').forEach(
        e => e.removeAttribute('data-akira-struct'));

    function visible(el) {
        try {
            const r = el.getBoundingClientRect();
            if (r.width < 5 || r.height < 5) return false;
            const s = window.getComputedStyle(el);
            return s.visibility !== 'hidden' && s.display !== 'none' &&
                   s.opacity !== '0';
        } catch (e) { return false; }
    }

    const clean = s => (s || '').replace(/\s+/g, ' ').trim();

    // A profile avatar keeps its NAME in a span that is a SIBLING of the
    // link, OUTSIDE it — so querySelector on the link can never reach it.
    // That is precisely how names came back as 'image result'.
    function siblingLabel(el) {
        try {
            const p = el.parentElement;
            if (!p) return '';
            for (const sp of p.querySelectorAll('span, .profile-name')) {
                if (el.contains(sp)) continue;
                const s = clean(sp.innerText || sp.textContent);
                if (s) return s;
            }
        } catch (e) {}
        return '';
    }

    function labelOf(el) {
        // Order: known name sub-elements -> sibling span -> own text ->
        // aria-label -> img alt. Own text comes before aria-label so a real
        // tab keeps its visible word ('Images') rather than a verbose
        // aria-label like 'Search for Images instead'.
        for (const q of labelSels) {
            try {
                const t = el.querySelector(q);
                if (t) {
                    const s = clean(t.innerText || t.textContent);
                    if (s) return s;
                }
            } catch (e) {}
        }
        const sib = siblingLabel(el);
        if (sib) return sib;
        const own = clean(el.innerText || el.textContent);
        if (own) return own;
        const aria = clean(el.getAttribute('aria-label'));
        if (aria) return aria;
        const img = el.querySelector('img');
        return img ? clean(img.getAttribute('alt')) : '';
    }

    for (const sel of sels) {
        let nodes;
        try { nodes = document.querySelectorAll(sel); } catch (e) { continue; }
        for (const el of nodes) {
            if (el.hasAttribute('data-akira-struct')) continue;
            if (!visible(el)) continue;
            let label = labelOf(el).replace(/\s+/g, ' ').slice(0, 80);
            if (!label) continue;
            el.setAttribute('data-akira-struct', String(n));
            out.push({
                n: n,
                label: label,
                href: el.getAttribute('href') || null,
                selected: el.getAttribute('aria-selected') === 'true' ||
                          (el.className || '').toString().indexOf('selected') >= 0,
                matched: sel
            });
            n++;
        }
    }
    return out;
"""

_CLICK_STRUCT_SCRIPT = r"""
    const el = document.querySelector('[data-akira-struct="' + arguments[0] + '"]');
    if (!el) return 'gone';
    try { el.scrollIntoView({block: 'center'}); } catch (e) {}
    el.click();
    return 'clicked';
"""


def _collect(browser, selectors: list[str]) -> list[dict]:
    try:
        found = browser.execute_script(_COLLECT_SCRIPT, selectors, _LABEL_SUBSELECTORS)
    except Exception as e:
        print(f"[STRUCT] collect failed: {e}")
        return []
    return found or []


def collect_tabs(browser) -> list[dict]:
    return _collect(browser, _TAB_SELECTORS)


def collect_profiles(browser) -> list[dict]:
    return _collect(browser, _PROFILE_SELECTORS)


def resolve_structural(browser, intent: tuple[str, str]) -> dict:
    """Click the structural control named by `intent`.

    Returns {'success': bool, 'message': str, 'candidates': [labels]} so the
    caller can report honestly (and name what it DID see) instead of guessing
    at pixels when nothing matches."""
    kind, name = intent

    if kind == 'profile':
        items = collect_profiles(browser)
        what = 'profile'
    elif kind == 'tab':
        items = collect_tabs(browser)
        what = 'tab'
    else:
        items = _collect(browser, _NAV_MENU_SELECTORS)
        what = 'menu item'

    labels = [it['label'] for it in items]
    print(f"[STRUCT] {what} candidates ({len(labels)}): {labels[:12]}")

    if not items:
        return {'success': False, 'candidates': [],
                'message': f"I couldn't find any {what} on this page."}

    if not name:
        return {'success': False, 'candidates': labels,
                'message': f"Which one? I can see: {', '.join(labels[:6])}."}

    pos = fuzzy_name_match(name, labels)
    if pos is None:
        return {'success': False, 'candidates': labels,
                'message': (f"I couldn't find a {what} called '{name}'. "
                            f"I can see: {', '.join(labels[:6])}.")}

    chosen = items[pos]
    if chosen.get('selected'):
        print(f"[STRUCT] {chosen['label']!r} already selected")

    try:
        state = browser.execute_script(_CLICK_STRUCT_SCRIPT, chosen['n'])
    except Exception as e:
        print(f"[STRUCT] click failed: {e}")
        return {'success': False, 'candidates': labels,
                'message': f"I found the {chosen['label']} {what} but couldn't click it."}

    if state != 'clicked':
        return {'success': False, 'candidates': labels,
                'message': f"The {chosen['label']} {what} disappeared before I could click it."}

    print(f"[STRUCT] clicked {what}={chosen['label']!r} via {chosen.get('matched')}")
    return {'success': True, 'candidates': labels,
            'message': f"Opened {chosen['label']}."}
