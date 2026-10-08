"""Optional, provider-pluggable LLM classification.

Returns ``(category, difficulty, summary)`` or ``None`` on any problem so the
caller falls back to the deterministic heuristic. Providers are imported lazily
so the package is never required unless actually used.
"""
from __future__ import annotations

import json
import logging

from ..config import settings
from ..models import CATEGORIES, Difficulty

logger = logging.getLogger("veloxi.llm")

_DIFFICULTIES = [d.value for d in Difficulty]

_SYSTEM = (
    "You classify learning/career opportunities. Respond with ONLY a JSON object "
    '{"category": <one of CATEGORIES>, "difficulty": "Beginner"|"Intermediate"|"Advanced", '
    '"summary": <one concise sentence, <=160 chars>}. '
    f"CATEGORIES = {CATEGORIES}."
)


def _prompt(title: str, description: str | None, h_cat: str, h_diff: str) -> str:
    return (
        f"Title: {title}\n"
        f"Description: {description or '(none)'}\n"
        f"Heuristic guess: category={h_cat}, difficulty={h_diff}.\n"
        "Return the corrected JSON."
    )


def _parse(text: str) -> tuple[str, str, str] | None:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    cat = str(data.get("category", "")).strip()
    diff = str(data.get("difficulty", "")).strip()
    summ = str(data.get("summary", "")).strip()
    if cat not in CATEGORIES or diff not in _DIFFICULTIES:
        return None
    return cat, diff, summ


def classify_with_llm(
    title: str, description: str | None, h_cat: str, h_diff: str
) -> tuple[str, str, str] | None:
    provider = (settings.llm_provider or "").strip().lower()
    user = _prompt(title, description, h_cat, h_diff)
    try:
        if provider == "anthropic":
            return _anthropic(user)
        if provider == "openai":
            return _openai(user)
        if provider == "gemini":
            return _gemini(user)
    except Exception as exc:
        logger.warning("LLM provider %s error: %s", provider, exc)
        return None
    return None


def _anthropic(user: str) -> tuple[str, str, str] | None:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=300,
        temperature=0,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
    return _parse(text)


def _openai(user: str) -> tuple[str, str, str] | None:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
    )
    return _parse(resp.choices[0].message.content or "")


def _gemini(user: str) -> tuple[str, str, str] | None:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model, system_instruction=_SYSTEM)
    resp = model.generate_content(user, generation_config={"temperature": 0})
    return _parse(resp.text or "")


# --------------------------------------------------------------------------- #
# Career Agent: optional CV profile extraction (Anthropic only for now).
# The deterministic skills-graph engine works without this; it only enriches
# the extracted skills and adds a short narrative when a key is configured.
# --------------------------------------------------------------------------- #
_CV_SYSTEM = (
    "You extract a candidate profile from CV / resume text. Respond with ONLY a JSON "
    'object: {"skills": [string], "targetRole": string, "summary": string}. '
    '"skills" = concrete technical or professional skills the person already has '
    "(e.g. Python, SQL, Project Management). "
    '"targetRole" = the role they appear to be aiming for (or "" if unclear). '
    '"summary" = one sentence, <=200 chars. Output JSON only, no prose.'
)


def extract_profile_with_llm(cv_text: str) -> dict | None:
    """Extract {skills, targetRole, summary} from CV text, or None if unavailable.

    Returns None when no LLM is configured or on any error, so the caller falls
    back to the deterministic skills-graph extraction.
    """
    if not settings.llm_enabled:
        return None
    if (settings.llm_provider or "").strip().lower() != "anthropic":
        return None  # prototype supports Anthropic; other providers can be added later
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        # No temperature: forward-compatible with models that reject sampling params.
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=700,
            system=_CV_SYSTEM,
            messages=[{"role": "user", "content": (cv_text or "")[:12000]}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return _parse_profile(text)
    except Exception as exc:  # noqa: BLE001 - LLM is best-effort
        logger.warning("CV profile extraction error: %s", exc)
        return None


def _parse_profile(text: str) -> dict | None:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    skills = data.get("skills")
    skills = [str(s).strip() for s in skills if str(s).strip()] if isinstance(skills, list) else []
    return {
        "skills": skills[:60],
        "targetRole": str(data.get("targetRole", "")).strip(),
        "summary": str(data.get("summary", "")).strip()[:200],
    }


def transcribe_pdf_with_llm(data: bytes) -> str | None:
    """Read a PDF via Claude's native PDF support (handles scanned/image PDFs).

    Returns the transcribed text, or None when no LLM is configured / on error,
    so the caller falls back to whatever the local extractor produced.
    """
    if not settings.llm_enabled:
        return None
    if (settings.llm_provider or "").strip().lower() != "anthropic":
        return None
    try:
        import base64

        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        b64 = base64.standard_b64encode(data).decode("ascii")
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Transcribe this CV/resume to plain text. Output only the text.",
                        },
                    ],
                }
            ],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.warning("PDF transcription error: %s", exc)
        return None
