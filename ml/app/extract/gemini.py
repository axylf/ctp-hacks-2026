"""Stage 4: the one non-deterministic step.

Everything here is defensive. The model is a dependency that can be slow,
rate-limited, absent (no key), or wrong — and the pipeline has to keep working
in all four cases, because a demo that dies when a quota runs out is not a demo.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass

from ..config import settings
from ..schemas import RawExtraction
from . import prompts

log = logging.getLogger(__name__)

_RETRYABLE = (429, 500, 502, 503, 504)


class GeminiUnavailable(RuntimeError):
    """No key configured, SDK missing, or the API failed every retry.
    Always caught by the pipeline, which then falls back to the regex extractor."""


@dataclass
class GeminiResult:
    extraction: RawExtraction
    model: str


def _status_code(exc: Exception) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    match = re.search(r"\b(4\d{2}|5\d{2})\b", str(exc))
    return int(match.group(1)) if match else None


def is_retryable(exc: Exception) -> bool:
    code = _status_code(exc)
    if code is not None:
        return code in _RETRYABLE
    return bool(re.search(r"timeout|temporarily|unavailable|deadline", str(exc), re.I))


def parse_response_text(text: str) -> RawExtraction:
    """Parse the model's JSON. `response_schema` should make fences impossible,
    but strip them anyway — costs one regex, saves a demo."""
    if not text or not text.strip():
        raise ValueError("empty response from model")
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1)
    return RawExtraction.model_validate(json.loads(cleaned))


def _build_client():
    if not settings.gemini_enabled:
        raise GeminiUnavailable("no GEMINI_API_KEY set — copy .env.example to .env")
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise GeminiUnavailable(f"google-genai not installed: {exc}") from exc
    return genai.Client(api_key=settings.gemini_api_key)


def _config():
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=prompts.SYSTEM_PROMPT,
        temperature=0.0,              # reproducibility: same syllabus, same JSON
        response_mime_type="application/json",
        response_schema=RawExtraction,  # the model cannot return a bad shape
    )


def _generate_with_retry(client, contents) -> str:
    """Exponential backoff with jitter on 429/5xx. Non-retryable errors raise
    immediately rather than burning the retry budget on a bad request."""
    last: Exception | None = None
    for attempt in range(settings.gemini_max_retries):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model, contents=contents, config=_config()
            )
            return response.text
        except Exception as exc:  # SDK raises a family of provider errors
            last = exc
            if not is_retryable(exc) or attempt == settings.gemini_max_retries - 1:
                break
            delay = (2**attempt) + random.uniform(0, 0.3)
            log.warning("Gemini call failed (%s), retrying in %.1fs", exc, delay)
            time.sleep(delay)
    raise GeminiUnavailable(f"Gemini call failed: {last}") from last


def extract_from_text(text: str) -> GeminiResult:
    client = _build_client()
    contents = [
        prompts.FEW_SHOT_INPUT,
        prompts.FEW_SHOT_OUTPUT,
        prompts.user_prompt_for_text(text),
    ]
    raw = _generate_with_retry(client, contents)
    return GeminiResult(extraction=parse_response_text(raw), model=settings.gemini_model)


def extract_from_images(images: list[bytes], mime_type: str = "image/png") -> GeminiResult:
    """All pages go into ONE call so cross-page context survives — a course name
    on page 1 and a deadline on page 3 belong to the same course."""
    from google.genai import types

    client = _build_client()
    contents: list = [prompts.VISION_PROMPT]
    contents += [types.Part.from_bytes(data=img, mime_type=mime_type) for img in images]
    raw = _generate_with_retry(client, contents)
    return GeminiResult(extraction=parse_response_text(raw), model=settings.gemini_model)
