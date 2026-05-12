"""API endpoints: analyze-link, upload-screenshot, search results."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models.extracted_clues import ExtractedClues
from app.models.place_result import PlaceResult
from app.models.search_history import SearchHistory
from app.schemas.analyze import (
    AnalyzeLinkRequest,
    AnalyzeLinkResponse,
    PlaceResultOut,
    SearchResultsResponse,
)
from app.schemas.llm import LLMExtraction
from app.services.analyzer import confidence_level, run_analysis
from app.services.explanation import build_explanation
from app.services.places_search import PlaceCandidate as GPCandidate
from app.services.ranking_engine import RankedResult
from app.services.storage import UploadValidationError, delete_temp, save_temp_upload
from app.services.url_parser import UnsupportedURLError, parse_url

router = APIRouter(tags=["analyze"])


# ─────────────────────────────────────────────────────────────────────────────
# YouTube link
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/analyze-link", response_model=AnalyzeLinkResponse)
async def analyze_link(
    payload: AnalyzeLinkRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    try:
        parsed = parse_url(str(payload.url))
    except UnsupportedURLError as e:
        raise HTTPException(status_code=400, detail=str(e))

    row = SearchHistory(
        user_id=payload.user_id,
        input_type="youtube",
        input_url=str(payload.url),
        platform=parsed.platform,
        content_id=parsed.content_id,
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    background.add_task(
        _run_url_in_new_session, row.id, str(payload.url), payload.user_hint_city
    )
    return AnalyzeLinkResponse(search_id=row.id, status=row.status)


async def _run_url_in_new_session(search_id: UUID, url: str, hint_city: str | None):
    async with AsyncSessionLocal() as session:
        await run_analysis(session, search_id, input_url=url, user_hint_city=hint_city)


# ─────────────────────────────────────────────────────────────────────────────
# Screenshot upload (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/upload-screenshot", response_model=AnalyzeLinkResponse)
async def upload_screenshot(
    background: BackgroundTasks,
    image: UploadFile = File(...),
    user_id: str | None = Form(None),
    user_hint_city: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Accept a screenshot, save to /tmp, schedule OCR + downstream pipeline.

    The original image is deleted as soon as OCR completes (or fails).
    Only OCR text and downstream results persist.
    """
    # Validate + save to temp BEFORE creating the DB row, so a bad upload
    # doesn't leave an orphan SearchHistory record.
    try:
        temp_path = await save_temp_upload(image)
    except UploadValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    row = SearchHistory(
        user_id=user_id,
        input_type="screenshot",
        platform="screenshot",
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    background.add_task(
        _run_screenshot_in_new_session, row.id, temp_path, user_hint_city
    )
    return AnalyzeLinkResponse(search_id=row.id, status=row.status)


async def _run_screenshot_in_new_session(
    search_id: UUID, temp_path: str, hint_city: str | None
):
    """Background task: run pipeline, then GUARANTEE deletion of the temp file."""
    try:
        async with AsyncSessionLocal() as session:
            await run_analysis(
                session,
                search_id,
                image_path=temp_path,
                user_hint_city=hint_city,
            )
    finally:
        delete_temp(temp_path)


# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────

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

    llm_out_dict = (clues.llm_output if clues else {}) or {}
    needs_input = llm_out_dict.get("needs_user_input", False)
    question = llm_out_dict.get("suggested_user_question")

    if not results:
        try:
            extraction = LLMExtraction.model_validate(llm_out_dict) if llm_out_dict else LLMExtraction()
        except Exception:
            extraction = LLMExtraction()
        explanation = build_explanation(extraction, [], "none")

        return SearchResultsResponse(
            search_id=search_id,
            status="completed",
            confidence_level="none",
            explanation=explanation,
            needs_user_input=True,
            suggested_user_question=question
            or "I couldn't find this place. Could you share the cafe name or city?",
            results=[],
        )

    top_confidence = results[0].confidence_score
    level = confidence_level(top_confidence)

    try:
        extraction = LLMExtraction.model_validate(llm_out_dict) if llm_out_dict else LLMExtraction()
    except Exception:
        extraction = LLMExtraction()
    ranked_for_explanation = [
        RankedResult(
            rank=r.rank,
            place=GPCandidate(
                google_place_id=r.google_place_id,
                name=r.place_name,
                address=r.address,
                latitude=r.latitude,
                longitude=r.longitude,
                rating=r.rating,
                review_count=r.review_count,
            ),
            confidence=r.confidence_score,
            reason=r.reason or [],
        )
        for r in results
    ]
    explanation = build_explanation(extraction, ranked_for_explanation, level)

    return SearchResultsResponse(
        search_id=search_id,
        status="completed",
        confidence_level=level,
        explanation=explanation,
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
                google_place_id=r.google_place_id,
            )
            for r in results
        ],
    )
