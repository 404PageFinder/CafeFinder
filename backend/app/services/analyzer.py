"""End-to-end analysis pipeline orchestrator.

Synchronous-style for MVP (runs as a FastAPI BackgroundTask). Move to
Celery in Phase 4 when video frame extraction makes runs CPU-heavy.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.search_history import SearchHistory
from app.models.extracted_clues import ExtractedClues
from app.models.place_result import PlaceResult
from app.services.url_parser import parse_url, UnsupportedURLError
from app.services.youtube_metadata import fetch_youtube_metadata, YouTubeFetchError
from app.services.llm_extractor import extract_places
from app.services.places_search import search_places
from app.services.ranking_engine import rank_places
from app.utils.logger import get_logger

log = get_logger(__name__)


async def run_analysis(
    db: AsyncSession,
    search_id: UUID,
    input_url: str,
    user_hint_city: str | None = None,
) -> None:
    """Execute the full pipeline. Updates SearchHistory.status as it progresses."""
    search: SearchHistory = (
        await db.execute(select(SearchHistory).where(SearchHistory.id == search_id))
    ).scalar_one()

    try:
        # 1. Parse URL
        search.status = "extracting"
        await db.commit()
        parsed = parse_url(input_url)
        if parsed.platform != "youtube":
            raise UnsupportedURLError("Only YouTube is supported in MVP Phase 1")

        # 2. Fetch YouTube metadata
        yt = await fetch_youtube_metadata(parsed.content_id)

        # 3. Persist clues
        clues_row = ExtractedClues(
            search_id=search_id,
            title=yt.title,
            description=yt.description,
            hashtags=yt.tags,
            raw_metadata={
                "channel": yt.channel_title,
                "published_at": yt.published_at,
                "thumbnail": yt.thumbnail_url,
            },
        )
        db.add(clues_row)
        await db.commit()

        # 4. LLM extraction
        search.status = "llm"
        await db.commit()
        llm_input = {
            "platform": "youtube",
            "title": yt.title,
            "description": yt.description,
            "hashtags": yt.tags,
            "creator_name": yt.channel_title,
            "ocr_text": [],       # Phase 2
            "speech_text": "",    # Phase 4
            "visual_clues": [],   # Phase 4
            "user_hint_city": user_hint_city,
        }
        extraction = await extract_places(llm_input)
        clues_row.llm_output = extraction.model_dump()
        await db.commit()

        # 5. Google Places search
        search.status = "searching"
        await db.commit()
        queries = extraction.search_queries or _fallback_queries(extraction, yt)
        places = await search_places(queries, max_per_query=5)

        # 6. Rank
        search.status = "ranking"
        await db.commit()
        ranked = rank_places(extraction, places, top_k=3)

        # 7. Persist ranked results
        for r in ranked:
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

        search.status = "completed"
        await db.commit()

    except UnsupportedURLError as e:
        log.warning("Unsupported URL: %s", e)
        search.status = "failed"
        search.error = f"unsupported_url: {e}"
        await db.commit()
    except YouTubeFetchError as e:
        log.warning("YouTube fetch failed: %s", e)
        search.status = "failed"
        search.error = f"youtube_fetch_failed: {e}"
        await db.commit()
    except Exception as e:
        log.exception("Analysis pipeline failed")
        search.status = "failed"
        search.error = str(e)
        await db.commit()


def _fallback_queries(extraction, yt) -> list[str]:
    """If LLM didn't produce search_queries, use the title as a last resort."""
    queries: list[str] = []
    if extraction.place_candidates:
        for c in extraction.place_candidates:
            parts = [p for p in [c.name, c.area, c.city] if p]
            if parts:
                queries.append(" ".join(parts))
    if not queries and yt.title:
        queries.append(yt.title)
    return queries


def confidence_level(score: float) -> str:
    if score >= settings.confidence_high:
        return "high"
    if score >= settings.confidence_medium:
        return "medium"
    return "low"
