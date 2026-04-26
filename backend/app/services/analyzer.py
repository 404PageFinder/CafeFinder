"""End-to-end analysis pipeline.

Two entry points:

- `run_pipeline(url, hint_city)` — pure function, no DB writes. Used by
  the evaluation harness and any caller that wants raw results.

- `run_analysis(db, search_id, url, hint_city)` — wraps run_pipeline and
  persists progress to SearchHistory / ExtractedClues / PlaceResult.
  Called from the FastAPI background task.
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.search_history import SearchHistory
from app.models.extracted_clues import ExtractedClues
from app.models.place_result import PlaceResult
from app.schemas.llm import LLMExtraction
from app.services.explanation import build_explanation
from app.services.llm_extractor import extract_places
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
    """Pure pipeline output — no DB dependence."""
    parsed_url: ParsedURL | None = None
    metadata: YouTubeMetadata | None = None
    extraction: LLMExtraction = field(default_factory=LLMExtraction)
    google_places: list[GPCandidate] = field(default_factory=list)
    ranked: list[RankedResult] = field(default_factory=list)
    confidence_level: str = "none"
    explanation: str = ""
    error: str | None = None
    error_kind: str | None = None  # "unsupported_url" | "youtube_fetch_failed" | "internal"


async def run_pipeline(url: str, user_hint_city: str | None = None) -> PipelineResult:
    """Pure pipeline: URL → metadata → LLM → Places → ranked results.

    Never raises; all failures are reported via PipelineResult.error.
    """
    result = PipelineResult()

    # 1. Parse URL
    try:
        result.parsed_url = parse_url(url)
        if result.parsed_url.platform != "youtube":
            raise UnsupportedURLError("Only YouTube is supported in MVP Phase 1")
    except UnsupportedURLError as e:
        result.error = str(e)
        result.error_kind = "unsupported_url"
        result.explanation = f"This link isn't supported yet. {e}"
        return result

    # 2. Fetch YouTube metadata
    try:
        result.metadata = await fetch_youtube_metadata(result.parsed_url.content_id)
    except YouTubeFetchError as e:
        result.error = str(e)
        result.error_kind = "youtube_fetch_failed"
        result.explanation = "Couldn't fetch the video. Is the link public and valid?"
        return result

    # 3. LLM extraction
    llm_input = {
        "platform": "youtube",
        "title": result.metadata.title,
        "description": result.metadata.description,
        "hashtags": result.metadata.tags,
        "creator_name": result.metadata.channel_title,
        "ocr_text": [],       # Phase 2
        "speech_text": "",    # Phase 4
        "visual_clues": [],   # Phase 4
        "user_hint_city": user_hint_city,
    }
    try:
        result.extraction = await extract_places(llm_input)
    except Exception as e:
        log.exception("LLM step crashed")
        result.error = f"llm_failed: {e}"
        result.error_kind = "internal"

    # 4. Google Places
    queries = result.extraction.search_queries or _fallback_queries(
        result.extraction, result.metadata
    )
    try:
        result.google_places = await search_places(queries, max_per_query=5)
    except Exception as e:
        log.exception("Places search crashed")
        result.error = f"places_failed: {e}"
        result.error_kind = "internal"

    # 5. Rank
    try:
        result.ranked = rank_places(result.extraction, result.google_places, top_k=3)
    except Exception as e:
        log.exception("Ranking crashed")
        result.error = f"ranking_failed: {e}"
        result.error_kind = "internal"

    # 6. Confidence + explanation
    result.confidence_level = (
        confidence_level(result.ranked[0].confidence) if result.ranked else "none"
    )
    result.explanation = build_explanation(
        result.extraction, result.ranked, result.confidence_level
    )
    return result


async def run_analysis(
    db: AsyncSession,
    search_id: UUID,
    input_url: str,
    user_hint_city: str | None = None,
) -> None:
    """DB-bound wrapper. Updates SearchHistory.status as the pipeline runs."""
    search: SearchHistory = (
        await db.execute(select(SearchHistory).where(SearchHistory.id == search_id))
    ).scalar_one()

    try:
        # Mark as running and execute the pure pipeline
        search.status = "running"
        await db.commit()
        result = await run_pipeline(input_url, user_hint_city)

        # Persist clues if we got metadata
        if result.metadata:
            db.add(
                ExtractedClues(
                    search_id=search_id,
                    title=result.metadata.title,
                    description=result.metadata.description,
                    hashtags=result.metadata.tags,
                    raw_metadata={
                        "channel": result.metadata.channel_title,
                        "published_at": result.metadata.published_at,
                        "thumbnail": result.metadata.thumbnail_url,
                    },
                    llm_output=result.extraction.model_dump(),
                )
            )

        # Persist ranked results
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


def _fallback_queries(extraction: LLMExtraction, yt: YouTubeMetadata | None) -> list[str]:
    queries: list[str] = []
    for c in extraction.place_candidates:
        parts = [p for p in [c.name, c.area, c.city] if p]
        if parts:
            queries.append(" ".join(parts))
    if not queries and yt and yt.title:
        queries.append(yt.title)
    return queries


def confidence_level(score: float) -> str:
    if score >= settings.confidence_high:
        return "high"
    if score >= settings.confidence_medium:
        return "medium"
    return "low"
