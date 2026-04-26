from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


FeedbackAction = Literal["correct", "not_correct", "show_more"]


class FeedbackRequest(BaseModel):
    user_id: str | None = None
    search_id: UUID
    action: FeedbackAction
    selected_google_place_id: str | None = Field(
        default=None,
        description="Required for 'correct' and 'not_correct'. Optional for 'show_more'.",
    )
    feedback_text: str | None = None

    @model_validator(mode="after")
    def _validate_action(self):
        if self.action in ("correct", "not_correct") and not self.selected_google_place_id:
            raise ValueError(
                f"selected_google_place_id is required for action='{self.action}'"
            )
        return self


class FeedbackResponse(BaseModel):
    feedback_id: UUID
    status: str
    next_action: str | None = None  # e.g., "rerun_with_relaxed_filters" for show_more
