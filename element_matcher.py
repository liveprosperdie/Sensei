"""
element_matcher.py — match a spoken instruction to an extracted DOM element.

Moved out of claude_handler.py: matching is DOM logic, not LLM plumbing,
and this module must be importable without TTS/audio (claude_handler
initializes pyttsx3 at import time, which is Windows-only).

Phase order — cheapest first, LLM strictly last:
  0. ROLE+ORDINAL / ROLE+POSITION  — "third image", "left video"
  0b. ROLE+CONTENT                 — "the image from iStock" (no ordinal)
  1. FUZZY substring               — longest-match-wins with ambiguity tie-out
  2. WORD OVERLAP                  — content words only, min 2
  3. BARE ORDINAL                  — visual order over content roles
  4. LLM (Haiku)                   — COSTS TOKENS; phases 0-3 should resolve
                                     virtually all "Nth image/link/video"
                                     requests before ever reaching this.
"""

from __future__ import annotations

import re

# Meta-words describe WHERE/WHAT KIND, never element content. Counting them
# in word-overlap matched "third image in Google search results" to the
# "Google apps" nav button (live failure). Strip before scoring.
_META_WORDS = {
    'image', 'images', 'photo', 'photos', 'picture', 'pictures',
    'thumbnail', 'google', 'bing', 'search', 'result', 'results',
    'page', 'one', 'the', 'a', 'an', 'in', 'on', 'of', 'from', 'at',
    'click', 'select', 'open', 'first', 'second', 'third', 'fourth',
    'fifth', 'sixth', 'top', 'left', 'right', 'middle', 'bottom',
    # Element-KIND words. "first link mangafreak.me" scored 'link' as
    # content, so any element whose text merely contained "link" competed
    # with the real target.
    'link', 'links', 'tab', 'tabs', 'button', 'buttons', 'profile',
    'profiles', 'video', 'videos', 'item', 'items', 'option', 'options',
}

# Role intent: "image"/"photo" etc. means role='image' elements ONLY —
# never nav chrome. Same for video/button/link.
_ROLE_KEYWORDS = {
    'image': 'image', 'photo': 'image', 'picture': 'image',
    'thumbnail': 'image', 'video': 'video', 'button': 'button',
    'link': 'link',
}

_ORDINALS = {
    'first': 0, '1st': 0, 'second': 1, '2nd': 1, 'third': 2, '3rd': 2,
    'fourth': 3, '4th': 3, 'fifth': 4, '5th': 4, 'sixth': 5, '6th': 5,
    'top': 0,
}

# Bare site NAMES (no TLD spoken) — a soft hint only, since "youtube" can
# legitimately appear in link text. Explicit domains go through
# _domain_tokens() below and are treated as a HARD constraint instead.
_DOMAIN_FILTERS = {
    'imdb': 'imdb.com', 'youtube': 'youtube.com', 'wikipedia': 'wikipedia.org',
    'reddit': 'reddit.com', 'github': 'github.com',
}

# An explicitly spoken domain ("mangafreak.me", "imdb.com"). Matched as an
# ATOMIC unit and removed from the string before word tokenization: splitting
# "mangafreak.me" on \w+ produced the junk token 'me', which substring-matched
# "Home", "Games" and "menu", so narrowing became a no-op and 'first' picked
# whatever happened to be first ("AI Mode").
_DOMAIN_RE = re.compile(
    r'\b([a-z0-9][a-z0-9-]{1,})\.'
    r'(com|me|net|org|io|tv|co|in|ai|gg|to|xyz|us|uk|dev|app|info|biz|site|online)'
    r'\b')


def _domain_tokens(instruction_lower: str) -> list[str]:
    """Explicit domains named in the instruction, as full 'name.tld' strings."""
    return [f"{m.group(1)}.{m.group(2)}"
            for m in _DOMAIN_RE.finditer(instruction_lower)]


def _source_tokens(instruction_lower: str) -> list[str]:
    """Tokens after 'from' that name a SOURCE ("from iStock", "from getty
    images") — generalizes the hardcoded domain dict so 'the image from
    [any site]' filters by href/text without ever reaching the LLM."""
    tokens = []
    for m in re.finditer(r'\bfrom\s+(?:the\s+)?([a-z0-9][\w.-]*)', instruction_lower):
        tok = m.group(1)
        if tok not in _META_WORDS and len(tok) >= 3:
            tokens.append(tok)
    return tokens


def _visual_sort(els: list[dict]) -> list[dict]:
    # Reading order: rows of ~40px tolerance top->bottom, then left->right.
    # DOM order lied on Google Images (nav/chrome interleaves results).
    return sorted(els, key=lambda e: ((e.get('y') or 0) // 40, e.get('x') or 0))


def _matches_words(el: dict, words: set[str]) -> bool:
    """Bare substring containment, but only for tokens long enough to be
    meaningful. 1-2 char tokens ('me', 'go', 'x') match almost any page text,
    which silently turned narrowing into a pass-through."""
    hay = f"{el.get('text') or ''} {el.get('href') or ''}".lower()
    return any(w in hay for w in words if len(w) >= 3)


def find_element_index(elements: list[dict], instruction: str) -> int | None:
    """Match instruction to element list using deterministic phases first,
    LLM strictly as the last resort (reduces API calls by 80%+)."""
    if not elements:
        return None

    instruction_lower = instruction.lower()
    # Strip explicit domains BEFORE \w+ tokenizing so they contribute as one
    # atomic constraint instead of leaking junk fragments into content words.
    domains = _domain_tokens(instruction_lower)
    tokenizable = _DOMAIN_RE.sub(' ', instruction_lower)
    instruction_words = set(re.findall(r'\w+', tokenizable))
    content_words = {w for w in (instruction_words - _META_WORDS) if len(w) >= 3}

    role_intent = next((r for kw, r in _ROLE_KEYWORDS.items()
                        if re.search(r'\b' + kw + r's?\b', instruction_lower)), None)

    # A structural request ("the Images tab", "Shrey profile") is NOT a request
    # for an image/video element. Without this, "Images tab" set
    # role_intent='image' and hard-filtered the pool to image RESULTS —
    # guaranteeing the tab was excluded and a photo was clicked. structural_ui
    # normally intercepts these before we are called; this is the backstop.
    if role_intent in ('image', 'video') and \
            re.search(r'\b(tabs?|profiles?|buttons?)\b', instruction_lower):
        print(f"[FILTER] suppressing role='{role_intent}' — structural request")
        role_intent = None

    # Apply filters: role intent first (strongest signal), then source/domain
    filtered = elements
    if role_intent:
        role_matches = [el for el in filtered if el.get('role') == role_intent]
        if role_matches:
            filtered = role_matches
            print(f"[FILTER] role='{role_intent}': {len(filtered)} candidates")

    # HARD constraint: an explicitly named domain must appear in the href. If
    # nothing on the page is from that domain, the honest answer is "not here"
    # — falling through to ordinal counting is what clicked "AI Mode" when the
    # user asked for the first mangafreak.me link.
    if domains:
        narrowed = [el for el in filtered
                    if any(d in (el.get('href') or '').lower() for d in domains)]
        print(f"[FILTER] named domain(s) {domains}: {len(narrowed)} matches")
        if not narrowed:
            print(f"[FILTER] no element on this page links to {domains} — "
                  f"refusing to guess")
            return None
        filtered = narrowed
    else:
        for keyword, domain in _DOMAIN_FILTERS.items():
            if re.search(r'\b' + keyword + r'\b', instruction_lower):
                narrowed = [el for el in filtered if domain in (el.get('href') or '')]
                if narrowed:
                    filtered = narrowed
                    print(f"[FILTER] Applied '{keyword}' filter, {len(filtered)} matches")
                    break

    src_tokens = _source_tokens(instruction_lower)
    if src_tokens:
        narrowed = [el for el in filtered if _matches_words(el, set(src_tokens))]
        if narrowed:
            filtered = narrowed
            print(f"[FILTER] source tokens {src_tokens}: {len(filtered)} matches")

    if not filtered:
        filtered = elements  # Fallback to all if filter removed everything

    ordinal_word = next((w for w in _ORDINALS
                         if re.search(r'\b' + w + r'\b', instruction_lower)), None)

    # Phase 0: role + ordinal/position — a POSITIONAL request; text phases
    # would only mis-match on meta-words. Visual-order selection over the
    # role-filtered set, with content words narrowing BEFORE counting
    # ('third image from iStock' counts within iStock results only).
    if role_intent and (ordinal_word or re.search(r'\b(left|right|middle)\b', instruction_lower)):
        cands = _visual_sort([el for el in filtered if el.get('role') == role_intent]
                             or filtered)
        if content_words:
            narrowed = [e for e in cands if _matches_words(e, content_words)]
            if narrowed:
                cands = narrowed
        if cands:
            if ordinal_word is not None:
                offset = _ORDINALS[ordinal_word]
                if offset < len(cands):
                    match = cands[offset]
                    print(f"[MATCH] ROLE+ORDINAL role={role_intent} #{offset + 1} "
                          f"index={match['index']} text='{match['text'][:40]}'")
                    return match['index']
            # left/right/middle among the first visual row
            row_y = (cands[0].get('y') or 0)
            row = [e for e in cands if abs((e.get('y') or 0) - row_y) <= 60] or cands
            row.sort(key=lambda e: e.get('x') or 0)
            pos = 'right' if 'right' in instruction_lower else \
                  'middle' if 'middle' in instruction_lower else 'left'
            match = row[-1] if pos == 'right' else row[len(row) // 2] if pos == 'middle' else row[0]
            print(f"[MATCH] ROLE+POSITION role={role_intent} pos={pos} "
                  f"index={match['index']} text='{match['text'][:40]}'")
            return match['index']

    # Phase 0b: role + content, NO ordinal ("the image from iStock", "the
    # photo of Denali"). Previously fell through to word-overlap/LLM; the
    # first visual-order element matching the content words is the answer.
    if role_intent and content_words and ordinal_word is None:
        cands = [e for e in _visual_sort(filtered)
                 if e.get('role') == role_intent and _matches_words(e, content_words)]
        if len(cands) >= 1:
            match = cands[0]
            print(f"[MATCH] ROLE+CONTENT role={role_intent} "
                  f"index={match['index']} text='{match['text'][:40]}'")
            return match['index']

    # Phase 1: Substring match on filtered elements. Collect ALL matches,
    # prefer the LONGEST matched element text — most specific wins. Tie in
    # length = genuine ambiguity -> defer to later phases instead of a
    # confident wrong click.
    phase1_matches = []
    for el in filtered:
        text_lower = el['text'].lower().strip()
        if not text_lower:
            continue
        if instruction_lower in text_lower:
            phase1_matches.append(el)
        elif re.search(r'\b' + re.escape(text_lower) + r'\b', instruction_lower):
            phase1_matches.append(el)
    if phase1_matches:
        phase1_matches.sort(key=lambda el: len(el['text'].strip()), reverse=True)
        top = phase1_matches[0]
        if len(phase1_matches) > 1 and len(phase1_matches[1]['text'].strip()) == len(top['text'].strip()):
            print(f"[MATCH] FUZZY ambiguous tie: "
                  f"'{top['text'][:30]}' vs '{phase1_matches[1]['text'][:30]}' — deferring")
        else:
            print(f"[MATCH] FUZZY index={top['index']} text='{top['text'][:50]}' "
                  f"(longest of {len(phase1_matches)} matches)")
            return top['index']

    # Phase 2: Word overlap — CONTENT words only, min 2 (a 1-word accidental
    # collision like "iStock" in a footer link scored 2.38 live).
    if content_words and len(content_words) >= 2:
        best_match = None
        best_score = 0.0
        pool = filtered[:50]
        for pos, el in enumerate(pool):
            text_words = set(re.findall(r'\w+', el['text'].lower()))
            overlap = len(content_words & text_words)
            overlap_ratio = overlap / len(content_words)
            if overlap >= 2 or (overlap >= 1 and overlap_ratio >= 0.5):
                score = overlap + (50 - pos) / 50.0  # early-position bonus
                if score > best_score:
                    best_score = score
                    best_match = el['index']
        if best_match is not None:
            print(f"[MATCH] WORD OVERLAP index={best_match} score={best_score:.2f}")
            return best_match

    # Phase 3: bare ordinal, no role keyword — visual order over content
    # roles (image results included; page chrome excluded).
    if ordinal_word is not None:
        ordinal_candidates = _visual_sort(
            [el for el in filtered if el.get('role') in {'link', 'video', 'image', 'button'}])
        offset = _ORDINALS[ordinal_word]
        if offset < len(ordinal_candidates):
            match = ordinal_candidates[offset]
            print(f"[MATCH] ORDINAL index={match['index']} text='{match['text'][:40]}'")
            return match['index']

    # Phase 4: LLM matching (COSTS TOKENS) — lazy import so this module
    # never needs claude_handler (TTS init) unless we actually get here.
    print(f"[LLM] Calling Haiku for '{instruction}'")
    subset = filtered[:40] if len(filtered) < len(elements) else elements[:40]
    elements_text = "\n".join(
        f"{el['index']}: [{el.get('role', '?')}] \"{el['text'][:100]}\""
        + (f" (url:{el['href'][:50]})" if el.get("href") else "")
        for el in subset)
    try:
        from claude_handler import client
        message = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=20,
            system=("Match instruction to element index. Reply ONLY with the number. "
                    "If no match, reply: NONE"),
            messages=[{"role": "user",
                       "content": f"Elements:\n{elements_text}\n\nFind: {instruction}"}],
        )
        result = message.content[0].text.strip()
        print(f"[LLM] Returned: {result}")
        if "NONE" in result.upper():
            return None
        numbers = re.findall(r'\d+', result)
        return int(numbers[0]) if numbers else None
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return None
