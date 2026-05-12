import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExtractedClues(Base):
    __tablename__ = "extracted_clues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_history.id", ondelete="CASCADE"), index=True
    )

    # YouTube-side metadata (null for screenshot inputs)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Phase 2: OCR results from screenshot uploads
    ocr_text: Mapped[list | None] = mapped_column(JSON, nullable=True)  # text_lines list
    ocr_full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)

    raw_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    llm_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
