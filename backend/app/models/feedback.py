import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_history.id", ondelete="CASCADE"), index=True
    )
    # action: "correct" | "not_correct" | "show_more"
    action: Mapped[str] = mapped_column(String(32))
    # google_place_id of the place the user picked / marked (null for "show_more")
    selected_google_place_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
