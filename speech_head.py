"""speech_head.py — Free speech head generation engine for simple turns.

Serves:
1. mode=conversation, complexity=simple -> plain spoken response text
2. mode=document_generation, complexity=simple -> drafted document text content

Fail-safe: Any timeout or exception immediately returns None to fail open to Claude.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger("akira.speech_head")


def generate_conversation_reply(user_text: str, timeout: float = 4.0) -> str | None:
    """Generate a quick conversational reply via the free speech head (Groq).
    
    Returns plain spoken prose string, or None if generation failed/timed out.
    """
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not groq_key:
        logger.warning("[speech_head] GROQ_API_KEY not set — failing open to Claude")
        return None

    try:
        from groq import Groq
        client = Groq(api_key=groq_key, timeout=timeout)

        model = (
            os.environ.get("AKIRA_SPEECH_HEAD_MODEL")
            or "openai/gpt-oss-120b"
        )

        system_prompt = (
            "You are Akira, a fast and friendly desktop voice assistant. "
            "Respond to the user in 1 to 3 short, natural spoken sentences. "
            "Plain conversational English only — no markdown, no asterisks, no bullet points, no code. "
            "Never output <think> tags or internal thoughts; speak directly to the user."
        )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.7,
            max_tokens=500,
        )

        text = response.choices[0].message.content or ""
        text = text.strip()
        if not text:
            return None

        import re
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        elif "<think>" in text:
            # Model truncated inside reasoning block without producing spoken answer
            return None

        # Clean out any stray formatting
        text = text.replace("**", "").replace("*", "").replace("`", "").strip()
        return text or None

    except Exception as err:
        logger.warning("[speech_head] Conversation generation failed/timed out: %s — failing open to Claude", err)
        print(f"[speech_head] Conversation generation error: {err!r} — failing open to Claude")
        return None


def generate_document_content(brief: str, length: str = "short", timeout: float = 8.0) -> str | None:
    """Generate drafted document content directly via the free speech head (Groq).
    
    Zero dependency on Claude Sonnet 5 or repo-notes 900-word length enforcement.
    Returns raw drafted text string, or None if generation failed/timed out.
    """
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not groq_key:
        logger.warning("[speech_head] GROQ_API_KEY not set — failing open to Claude")
        return None

    try:
        from groq import Groq
        client = Groq(api_key=groq_key, timeout=timeout)
        model = os.environ.get("AKIRA_SPEECH_HEAD_MODEL") or "openai/gpt-oss-120b"

        system_prompt = (
            "You are Akira, a fast and helpful document writer. "
            "Draft the requested document content clearly, cleanly, and concisely based strictly on the user brief. "
            "No conversational preambles, no meta-commentary, no markdown codeblocks — just the clean document text."
        )

        max_tokens = 500 if length == "short" else 1500

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Brief: {brief}"},
            ],
            temperature=0.5,
            max_tokens=max_tokens,
        )

        text = response.choices[0].message.content or ""
        text = text.strip()
        if not text:
            return None

        # Clean out thinking tags if present
        import re
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        elif "<think>" in text:
            return None

        return text or None

    except Exception as err:
        logger.warning("[speech_head] Document content generation error: %s — failing open to Claude", err)
        print(f"[speech_head] Document generation error: {err!r} — failing open to Claude")
        return None
