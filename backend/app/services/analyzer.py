"""End-to-end analysis pipelines for both YouTube links and screenshots.

Three entry points:

- `run_pipeline_for_url(url, hint_city)` — pure YouTube pipeline.
- `run_pipeline_for_screenshot(image_path, hint_city)` — pure screenshot pipeline.
- `run_analysis(db, search_id, ...)` — DB-bound wrapper that dispatches based
  on the SearchHistory.input_type and persists progress.

Both pure pipelines converge on `_run_extraction_and_search`, which performs
LLM extraction → Places search → ranking → explanation. Adding new input
types (Instagram in Phase 3, video frames in Phase 4) just means writing a
new clue-gathering function and calling _run_extraction_and_search.
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.extracted_clues import ExtractedClues
from app.models.place_result import PlaceResult
from app.models.search_history import SearchHistory
from app.schemas.llm import LLMExtraction
from app.services.explanation import build_explanation
from app.services.llm_extractor import extract_places
from app.services.ocr import OCRError, OCRResult, extract_text
from app.services.places_search import PlaceCandidate as GPCandidate, search_places
from app.services.ranking_engine import RankedResult, rank_places
from app.services.url_parser import ParsedURL, UnsupportedURLError, parse_url
from app.services.youtube_metadata import (
    YouTubeFetchError,
    YouTubeMetadata,
    fetch_youtube_metadata,
)
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class PipelineResult:
    """Pure pipeline output — no DB dependence. Used by both YouTube and
    screenshot pipelines, plus the eval harness.
    """
    parsed_url: ParsedURL | None = None
    metadata: YouTubeMetadata | None = None
    ocr_result: OCRResult | None = None
    extraction: LLMExtraction = field(default_factory=LLMExtraction)
    google_places: list[GPCandidate] = field(default_factory=list)
    ranked: list[RankedResult] = field(default_factory=list)
    confidence_level: str = "none"
    explanation: str = ""
    error: str | None = None
    error_kind: str | None = None  # "unsupported_url" | "youtube_fetch_failed" | "ocr_failed" | "internal"


# ─────────────────────────────────────────────────────────────────────────────
# YouTube pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def run_pipeline_for_url(url: str, user_hint_city: str | None = None) -> PipelineResult:
    """Pure YouTube pipeline. Never raises."""
    result = PipelineResult()

    try:
        result.parsed_url = parse_url(url)
        if result.parsed_url.platform != "youtube":
            raise UnsupportedURLError("Only YouTube is supported in MVP Phase 1/2")
    except UnsupportedURLError as e:
        result.error = str(e)
        result.error_kind = "unsupported_url"
        result.explanation = f"This link isn't supported yet. {e}"
        return result

    try:
        result.metadata = await fetch_youtube_metadata(result.parsed_url.content_id)
    except YouTubeFetchError as e:
        result.error = str(e)
        result.error_kind = "youtube_fetch_failed"
        result.explanation = "Couldn't fetch the video. Is the link public and valid?"
        return result

    llm_input = {
        "platform": "youtube",
        "title": result.metadata.title,
        "description": result.metadata.description,
        "hashtags": result.metadata.tags,
        "creator_name": result.metadata.channel_title,
        "ocr_text": [],
        "speech_text": "",
        "visual_clues": [],
        "user_hint_city": user_hint_city,
    }
    return await _run_extraction_and_search(llm_input, result)


# ─────────────────────────────────────────────────────────────────────────────
# Screenshot pipeline (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

async def run_pipeline_for_screenshot(
    image_path: str,
    user_hint_city: str | None = None,
) -> PipelineResult:
    """Pure screenshot pipeline. Caller is responsible for cleanup of image_path."""
    result = PipelineResult()

    try:
        result.ocr_result = await extract_text(image_path)
    except OCRError as e:
        result.error = str(e)
        result.error_kind = "ocr_failed"
        result.explanation = (
            "Couldn't read text from the screenshot. "
            "Try a clearer image showing the cafe signboard or menu."
        )
        return result

    if not result.ocr_result.text_lines:
        result.error = "no_text_detected"
        result.error_kind = "ocr_failed"
        result.explanation = (
            "No text was detected in the image. "
            "Try a screenshot that shows the cafe signboard, menu, or address."
        )
        return result

    llm_input = {
        "platform": "screenshot",
        "title": "",
        "description": "",
        "hashtags": [],
        "creator_name": "",
        "ocr_text": result.ocr_result.text_lines,
        "speech_text": "",
        "visual_clues": [],
        "user_hint_city": user_hint_city,
    }
    return await _run_extraction_and_search(llm_input, result)


# ─────────────────────────────────────────────────────────────────────────────
# Shared downstream stages
# ─────────────────────────────────────────────────────────────────────────────

async def _run_extraction_and_search(
    llm_input: dict, result: PipelineResult
) -> PipelineResult:
    """LLM → Places → ranking → explanation. Shared by both pipelines."""
    try:
        result.extraction = await extract_places(llm_input)
    except Exception as e:
        log.exception("LLM step crashed")
        result.error = f"llm_failed: {e}"
        result.error_kind = "internal"

    queries = result.extraction.search_queries or _fallback_queries(
        result.extraction, result.metadata, result.ocr_result
    )

    try:
        result.google_places = await search_places(queries, max_per_query=5)
    except Exception as e:
        log.exception("Places search crashed")
        result.error = f"places_failed: {e}"
        result.error_kind = "internal"

    try:
        result.ranked = rank_places(result.extraction, result.google_places, top_k=3)
    except Exception as e:
        log.exception("Ranking crashed")
        result.error = f"ranking_failed: {e}"
        result.error_kind = "internal"

    result.confidence_level = (
        confidence_level(result.ranked[0].confidence) if result.ranked else "none"
    )
    result.explanation = build_explanation(
        result.extraction, result.ranked, result.confidence_level
    )
    return result


def _fallback_queries(
    extraction: LLMExtraction,
    yt: YouTubeMetadata | None,
    ocr: OCRResult | None,
) -> list[str]:
    queries: list[str] = []
    for c in extraction.place_candidates:
        parts = [p for p in [c.name, c.area, c.city] if p]
        if parts:
            queries.append(" ".join(parts))
    if not queries and yt and yt.title:
        queries.append(yt.title)
    if not queries and ocr and ocr.text_lines:
        # Last-resort: use the longest OCR line as a search query
        longest = max(ocr.text_lines, key=len)
        if len(longest) >= 3:
            queries.append(longest)
    return queries


def confidence_level(score: float) -> str:
    if score >= settings.confidence_high:
        return "high"
    if score >= settings.confidence_medium:
        return "medium"
    return "low"


# ─────────────────────────────────────────────────────────────────────────────
# DB-bound dispatcher
# ─────────────────────────────────────────────────────────────────────────────

async def run_analysis(
    db: AsyncSession,
    search_id: UUID,
    *,
    input_url: str | None = None,
    image_path: str | None = None,
    user_hint_city: str | None = None,
) -> None:
    """Dispatch to the right pure pipeline based on what was provided.

    Persists progress to SearchHistory and the result tables. Caller is
    responsible for deleting image_path AFTER this returns (the storage
    layer's context manager handles this).
    """
    search: SearchHistory = (
        await db.execute(select(SearchHistory).where(SearchHistory.id == search_id))
    ).scalar_one()

    try:
        search.status = "running"
        await db.commit()

        if input_url:
            result = await run_pipeline_for_url(input_url, user_hint_city)
        elif image_path:
            result = await run_pipeline_for_screenshot(image_path, user_hint_city)
        else:
            raise ValueError("Either input_url or image_path must be provided")

        # Persist clues
        db.add(_make_clues_row(search_id, result))

        for r in result.ranked:
            db.add(
                PlaceResult(
                    search_id=search_id,
                    rank=r.rank,
                    google_place_id=r.place.google_place_id,
                    place_name=r.place.name,
                    address=r.place.address,
                    latitude=r.place.latitude,
                    longitude=r.place.longitude,
                    rating=r.place.rating,
                    review_count=r.place.review_count,
                    maps_url=r.place.maps_url,
                    confidence_score=r.confidence,
                    reason=r.reason,
                )
            )

        if result.error:
            search.status = "failed"
            search.error = f"{result.error_kind}: {result.error}"
        else:
            search.status = "completed"
        await db.commit()

    except Exception as e:
        log.exception("Analysis pipeline failed unexpectedly")
        search.status = "failed"
        search.error = f"internal: {e}"
        await db.commit()


def _make_clues_row(search_id: UUID, result: PipelineResult) -> ExtractedClues:
    """Build the ExtractedClues row, populating YouTube-side OR OCR-side fields."""
    row = ExtractedClues(
        search_id=search_id,
        llm_output=result.extraction.model_dump() if result.extraction else None,
    )
    if result.metadata:
        row.title = result.metadata.title
        row.description = result.metadata.description
        row.hashtags = result.metadata.tags
        row.raw_metadata = {
            "channel": result.metadata.channel_title,
            "published_at": result.metadata.published_at,
            "thumbnail": result.metadata.thumbnail_url,
        }
    if result.ocr_result:
        row.ocr_text = result.ocr_result.text_lines
        row.ocr_full_text = result.ocr_result.full_text
        row.ocr_confidence = result.ocr_result.avg_confidence
        row.ocr_backend = result.ocr_result.backend
    return row
