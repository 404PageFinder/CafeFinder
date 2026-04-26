"""Feedback endpoint.

Three actions:
- correct       — user confirms the selected place
- not_correct   — user rejects a place
- show_more     — user wants more alternatives (Phase 2 will trigger
                  a relaxed re-query; for now we just record the signal)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.feedback import Feedback
from app.models.search_history import SearchHistory
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    # Verify the search exists
    search = (
        await db.execute(
            select(SearchHistory).where(SearchHistory.id == payload.search_id)
        )
    ).scalar_one_or_none()
    if not search:
        raise HTTPException(status_code=404, detail="search_id not found")

    is_correct: bool | None = None
    if payload.action == "correct":
        is_correct = True
    elif payload.action == "not_correct":
        is_correct = False

    fb = Feedback(
        user_id=payload.user_id,
        search_id=payload.search_id,
        action=payload.action,
        selected_google_place_id=payload.selected_google_place_id,
        is_correct=is_correct,
        feedback_text=payload.feedback_text,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)

    next_action = None
    if payload.action == "show_more":
        # Phase 2 hook: trigger a relaxed re-query (more queries, wider radius)
        next_action = "rerun_with_relaxed_filters"

    return FeedbackResponse(
        feedback_id=fb.id,
        status="recorded",
        next_action=next_action,
    )
