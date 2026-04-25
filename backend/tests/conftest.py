"""Pytest config — provides dummy env vars so config.Settings can load
in tests that don't actually hit external APIs.
"""

import os


def _set_default(key: str, value: str):
    os.environ.setdefault(key, value)


# Set BEFORE any app imports
_set_default("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
_set_default("YOUTUBE_API_KEY", "test_yt_key")
_set_default("GOOGLE_PLACES_API_KEY", "test_places_key")
_set_default("LLM_API_KEY", "test_llm_key")
_set_default("LLM_PROVIDER", "openai")
_set_default("LLM_MODEL", "gpt-4o-mini")
