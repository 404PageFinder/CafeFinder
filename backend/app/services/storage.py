"""Temporary screenshot storage.

Per Phase 2 architecture: screenshots are NEVER persisted. They live in
/tmp long enough for OCR to run, then they're deleted. The original image
is not retained — only the OCR text and downstream extracted clues persist.

The save / delete pair is wrapped in a context manager so cleanup is
guaranteed even when OCR raises or the pipeline crashes.
"""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import UploadFile

from app.utils.logger import get_logger

log = get_logger(__name__)

# Where temp files live. /tmp is fine for single-host MVP. For Phase 4+
# Celery deployment, this needs to be a shared volume or a distinct path
# resolved per worker.
TEMP_DIR = Path(os.environ.get("SCREENSHOT_TEMP_DIR", "/tmp/cafefinder_uploads"))

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


class UploadValidationError(ValueError):
    pass


def _ensure_dir() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def _ext_for(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(content_type, ".bin")


async def save_temp_upload(upload: UploadFile) -> str:
    """Validate and save an UploadFile to a temp path. Returns the path."""
    if upload.content_type not in ALLOWED_CONTENT_TYPES:
        raise UploadValidationError(
            f"Unsupported image type: {upload.content_type}. "
            f"Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
        )

    _ensure_dir()
    file_id = uuid.uuid4().hex
    ext = _ext_for(upload.content_type or "")
    path = TEMP_DIR / f"{file_id}{ext}"

    # Stream-copy with a hard size cap to avoid memory blowup on huge uploads
    bytes_written = 0
    with open(path, "wb") as out:
        while chunk := await upload.read(1024 * 64):
            bytes_written += len(chunk)
            if bytes_written > MAX_BYTES:
                out.close()
                try:
                    path.unlink()
                except OSError:
                    pass
                raise UploadValidationError(
                    f"File exceeds {MAX_BYTES // (1024 * 1024)}MB limit"
                )
            out.write(chunk)

    if bytes_written == 0:
        try:
            path.unlink()
        except OSError:
            pass
        raise UploadValidationError("Empty file")

    log.info("Saved temp upload: %s (%d bytes)", path, bytes_written)
    return str(path)


def delete_temp(path: str) -> None:
    """Best-effort delete. Never raises."""
    try:
        Path(path).unlink(missing_ok=True)
        log.info("Deleted temp file: %s", path)
    except OSError as e:
        log.warning("Failed to delete temp file %s: %s", path, e)


@asynccontextmanager
async def temp_upload(upload: UploadFile):
    """Async context manager: save upload, yield path, delete on exit.

    Usage:
        async with temp_upload(file) as path:
            ocr_result = await extract_text(path)
        # File is gone here, even if extract_text raised
    """
    path = await save_temp_upload(upload)
    try:
        yield path
    finally:
        delete_temp(path)
