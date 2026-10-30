"""
teaching/llm_json.py — tolerant parsing of the JSON envelope that LLMs return.
Vendored locally inside teaching/ so the teaching module is 100% self-contained
and can run as a standalone repository or web app without root dependencies.
"""

from __future__ import annotations

import json
import re

_VALID_ESCAPES = '"\\/bfnrtu'
_AFTER_STRING = ',:}]'


def _strip_wrapper(raw: str) -> str:
    """Drop code fences and any prose around the JSON object."""
    text = (raw or "").replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    if start > 0:
        text = text[start:]
    return text.strip()


def _repair(text: str) -> tuple[str, bool]:
    out: list[str] = []
    stack: list[str] = []
    in_str = False
    escaped = False
    truncated = False
    i, n = 0, len(text)

    while i < n:
        c = text[i]

        if in_str:
            if escaped:
                out.append(c)
                escaped = False
                i += 1
                continue
            if c == "\\":
                nxt = text[i + 1] if i + 1 < n else ""
                if nxt in _VALID_ESCAPES and nxt != "":
                    out.append(c)
                    escaped = True
                else:
                    out.append("\\\\")
                i += 1
                continue
            if c == '"':
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j >= n or text[j] in _AFTER_STRING:
                    in_str = False
                    out.append(c)
                else:
                    out.append('\\"')
                i += 1
                continue
            if c == "\n":
                out.append("\\n")
            elif c == "\r":
                out.append("\\r")
            elif c == "\t":
                out.append("\\t")
            elif ord(c) < 0x20:
                out.append("\\u%04x" % ord(c))
            else:
                out.append(c)
            i += 1
            continue

        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
        out.append(c)
        i += 1

    if in_str:
        truncated = True
        if escaped:
            out.pop()
        out.append('"')

    if stack:
        truncated = True

    repaired = "".join(out) + "".join(reversed(stack))
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired, truncated


def _candidates(repaired: str) -> list[str]:
    forms = [repaired]
    m = re.search(r'("(?:[^"\\]|\\.)*")\s*([}\]]*)$', repaired)
    if m:
        forms.append(repaired[:m.start(1)] + m.group(1) + ': ""' + m.group(2))
        dropped = re.sub(r',\s*"(?:[^"\\]|\\.)*"\s*([}\]]*)$', r"\1", repaired)
        if dropped != repaired:
            forms.append(dropped)
    forms.append(re.sub(r':\s*([}\]]*)$', r': ""\1', repaired))
    return forms


def parse(raw: str) -> tuple[dict | None, dict]:
    info = {"repaired": False, "truncated": False}
    text = _strip_wrapper(raw)
    if not text:
        return None, info

    try:
        obj = json.loads(text)
        return (obj if isinstance(obj, dict) else None), info
    except json.JSONDecodeError:
        pass

    try:
        obj, end = json.JSONDecoder().raw_decode(text)
        if isinstance(obj, dict):
            return obj, info
    except json.JSONDecodeError:
        pass

    cleaned_text = re.sub(r'([}\]])\s*"\s*([}\]])', r'\1\2', text)
    cleaned_text = re.sub(r'([}\]])\s*"\s*$', r'\1', cleaned_text)
    if cleaned_text != text:
        try:
            obj = json.loads(cleaned_text)
            if isinstance(obj, dict):
                info["repaired"] = True
                return obj, info
        except json.JSONDecodeError:
            text = cleaned_text

    repaired, truncated = _repair(text)
    info["truncated"] = truncated
    for candidate in _candidates(repaired):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            cand_clean = re.sub(r'([}\]])\s*"\s*([}\]])', r'\1\2', candidate)
            cand_clean = re.sub(r'([}\]])\s*"\s*$', r'\1', cand_clean)
            try:
                obj = json.loads(cand_clean)
            except json.JSONDecodeError:
                continue
        if isinstance(obj, dict):
            info["repaired"] = True
            return obj, info

    return None, info
