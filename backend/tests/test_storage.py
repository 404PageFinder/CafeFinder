"""Tests for screenshot storage service.

Verifies:
- Validation of content-type and file size
- Temp file is deleted on context-manager exit (success path)
- Temp file is deleted on context-manager exit (exception path)
- Cleanup is best-effort and never raises
"""

import io
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from app.services import storage
from app.services.storage import (
    UploadValidationError,
    delete_temp,
    save_temp_upload,
    temp_upload,
)


def _make_upload(content: bytes, content_type: str = "image/png") -> UploadFile:
    """Build a minimal UploadFile-like for tests."""
    f = io.BytesIO(content)
    upload = UploadFile(filename="test.png", file=f, headers=MagicMock())
    # FastAPI's UploadFile reads content_type from headers; we mock it directly
    upload.__dict__["headers"] = {"content-type": content_type}
    upload.__dict__["_content_type"] = content_type
    # Override the property
    type(upload).content_type = property(lambda self: self.__dict__.get("_content_type"))
    return upload


@pytest.fixture
def tmp_storage_dir(tmp_path, monkeypatch):
    """Redirect storage to a pytest-managed tmp directory."""
    monkeypatch.setattr(storage, "TEMP_DIR", tmp_path)
    return tmp_path


class TestSaveTempUpload:
    @pytest.mark.asyncio
    async def test_saves_valid_png(self, tmp_storage_dir):
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        upload = _make_upload(png_bytes, "image/png")
        path = await save_temp_upload(upload)
        assert Path(path).exists()
        assert Path(path).suffix == ".png"
        assert Path(path).read_bytes() == png_bytes

    @pytest.mark.asyncio
    async def test_saves_valid_jpeg(self, tmp_storage_dir):
        jpg_bytes = b"\xff\xd8\xff" + b"x" * 100
        upload = _make_upload(jpg_bytes, "image/jpeg")
        path = await save_temp_upload(upload)
        assert Path(path).suffix == ".jpg"

    @pytest.mark.asyncio
    async def test_rejects_invalid_content_type(self, tmp_storage_dir):
        upload = _make_upload(b"hello", "application/pdf")
        with pytest.raises(UploadValidationError, match="Unsupported image type"):
            await save_temp_upload(upload)

    @pytest.mark.asyncio
    async def test_rejects_empty_file(self, tmp_storage_dir):
        upload = _make_upload(b"", "image/png")
        with pytest.raises(UploadValidationError, match="Empty file"):
            await save_temp_upload(upload)

    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self, tmp_storage_dir, monkeypatch):
        # Drop the limit to make the test fast
        monkeypatch.setattr(storage, "MAX_BYTES", 100)
        upload = _make_upload(b"x" * 500, "image/png")
        with pytest.raises(UploadValidationError, match="exceeds"):
            await save_temp_upload(upload)
        # Make sure the partial file was cleaned up
        assert len(list(tmp_storage_dir.iterdir())) == 0


class TestDeleteTemp:
    def test_deletes_existing_file(self, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("hi")
        delete_temp(str(target))
        assert not target.exists()

    def test_missing_file_no_raise(self, tmp_path):
        # Must NOT raise on missing file
        delete_temp(str(tmp_path / "does_not_exist.txt"))


class TestTempUploadContextManager:
    @pytest.mark.asyncio
    async def test_cleans_up_on_success(self, tmp_storage_dir):
        upload = _make_upload(b"\x89PNG" + b"x" * 100, "image/png")
        captured_path = None
        async with temp_upload(upload) as path:
            captured_path = path
            assert Path(path).exists()
        # After exit, file should be gone
        assert not Path(captured_path).exists()

    @pytest.mark.asyncio
    async def test_cleans_up_on_exception(self, tmp_storage_dir):
        upload = _make_upload(b"\x89PNG" + b"x" * 100, "image/png")
        captured_path = None
        with pytest.raises(RuntimeError, match="boom"):
            async with temp_upload(upload) as path:
                captured_path = path
                assert Path(path).exists()
                raise RuntimeError("boom")
        assert not Path(captured_path).exists()
