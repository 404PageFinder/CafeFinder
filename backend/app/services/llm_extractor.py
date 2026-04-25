"""LLM-based place extraction.

Sends merged metadata to OpenAI or Anthropic and parses strict JSON
that conforms to the LLMExtraction schema. On parse failure, returns
a graceful empty extraction with `needs_user_input=True` so the
pipeline can continue rather than crash.
"""

import json
import httpx

from app.config import settings
from app.schemas.llm import LLMExtraction
from app.prompts.extraction_prompt import SYSTEM_PROMPT
from app.utils.logger import get_logger

log = get_logger(__name__)


class LLMError(Exception):
    pass


async def extract_places(metadata: dict) -> LLMExtraction:
    """metadata example:
    {
        "platform": "youtube",
        "title": "...",
        "description": "...",
        "hashtags": ["...", "..."],
        "creator_name": "...",
        "ocr_text": [],          # Phase 2
        "speech_text": "",       # Phase 4
        "visual_clues": [],      # Phase 4
        "user_hint_city": null
    }
    """
    user_payload = json.dumps(metadata, ensure_ascii=False)

    try:
        if settings.llm_provider == "openai":
            raw_json = await _call_openai(user_payload)
        elif settings.llm_provider == "anthropic":
            raw_json = await _call_anthropic(user_payload)
        else:
            raise LLMError(f"Unknown LLM provider: {settings.llm_provider}")
    except Exception as e:
        log.exception("LLM call failed")
        return LLMExtraction(
            uncertainties=[f"LLM call failed: {e}"],
            needs_user_input=True,
            suggested_user_question="Could you share the cafe name or city?",
        )

    try:
        parsed = json.loads(raw_json)
        return LLMExtraction.model_validate(parsed)
    except Exception as e:
        log.warning("LLM JSON parse failed: %s | raw=%s", e, raw_json[:500])
        return LLMExtraction(
            uncertainties=[f"LLM output invalid: {e}"],
            needs_user_input=True,
            suggested_user_question="Could you share the cafe name or city?",
        )


async def _call_openai(user_payload: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


async def _call_anthropic(user_payload: str) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": settings.llm_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.llm_model,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT + "\n\nRespond ONLY with valid JSON. No prose, no markdown fences.",
        "messages": [{"role": "user", "content": user_payload}],
        "temperature": 0.1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    raise LLMError("No text content in Anthropic response")
