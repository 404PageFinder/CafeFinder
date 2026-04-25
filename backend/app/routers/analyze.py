"""API endpoints for analyze-link and search results."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models.search_history import SearchHistory
from app.models.place_result import PlaceResult
from app.models.extracted_clues import ExtractedClues
from app.schemas.analyze import (
    AnalyzeLinkRequest,
    AnalyzeLinkResponse,
    SearchResultsResponse,
    PlaceResultOut,
)
from app.services.url_parser import parse_url, UnsupportedURLError
from app.services.analyzer import run_analysis, confidence_level

router = APIRouter(tags=["analyze"])


@router.post("/analyze-link", response_model=AnalyzeLinkResponse)
async def analyze_link(
    payload: AnalyzeLinkRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Pre-validate URL before creating a DB row
    try:
        parsed = parse_url(str(payload.url))
    except UnsupportedURLError as e:
        raise HTTPException(status_code=400, detail=str(e))

    row = SearchHistory(
        user_id=payload.user_id,
        input_url=str(payload.url),
        platform=parsed.platform,
        content_id=parsed.content_id,
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Kick off pipeline in background. In Phase 4 this becomes a Celery task.
    background.add_task(
        _run_in_new_session,
        row.id,
        str(payload.url),
        payload.user_hint_city,
    )
    return AnalyzeLinkResponse(search_id=row.id, status=row.status)


async def _run_in_new_session(search_id: UUID, url: str, hint_city: str | None):
    """Background tasks run after response is sent — they need a fresh session."""
    async with AsyncSessionLocal() as session:
        await run_analysis(session, search_id, url, hint_city)


@router.get("/search/{search_id}/results", response_model=SearchResultsResponse)
async def get_results(search_id: UUID, db: AsyncSession = Depends(get_db)):
    search = (
        await db.execute(select(SearchHistory).where(SearchHistory.id == search_id))
    ).scalar_one_or_none()

    if not search:
        raise HTTPException(status_code=404, detail="search_id not found")

    if search.status != "completed":
        return SearchResultsResponse(search_id=search_id, status=search.status)

    results = (
        await db.execute(
            select(PlaceResult)
            .where(PlaceResult.search_id == search_id)
            .order_by(PlaceResult.rank)
        )
    ).scalars().all()

    clues = (
        await db.execute(
            select(ExtractedClues).where(ExtractedClues.search_id == search_id)
        )
    ).scalar_one_or_none()

    llm_out = (clues.llm_output if clues else {}) or {}
    needs_input = llm_out.get("needs_user_input", False)
    question = llm_out.get("suggested_user_question")

    if not results:
        return SearchResultsResponse(
            search_id=search_id,
            status="completed",
            confidence_level="none",
            needs_user_input=True,
            suggested_user_question=question
            or "I couldn't find this place. Could you share the cafe name or city?",
            results=[],
        )

    top_confidence = results[0].confidence_score
    level = confidence_level(top_confidence)

    return SearchResultsResponse(
        search_id=search_id,
        status="completed",
        confidence_level=level,
        needs_user_input=needs_input,
        suggested_user_question=question,
        results=[
            PlaceResultOut(
                rank=r.rank,
                name=r.place_name,
                address=r.address,
                latitude=r.latitude,
                longitude=r.longitude,
                rating=r.rating,
                review_count=r.review_count,
                maps_url=r.maps_url,
                confidence=r.confidence_score,
                reason=r.reason or [],
            )
            for r in results
        ],
    )
