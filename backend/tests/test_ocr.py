"""Tests for OCR service abstraction.

These tests use a mock backend so they run without PaddleOCR installed.
PaddleOCR-specific behavior is tested via the _parse_paddle_result helper
on synthetic PaddleOCR output shapes.
"""

import pytest

from app.services.ocr import (
    OCRBackend,
    OCRError,
    OCRResult,
    PaddleOCRBackend,
    _parse_paddle_result,
    extract_text,
)


class MockBackend:
    name = "mock"

    def __init__(self, result: OCRResult | None = None, raise_with: Exception | None = None):
        self._result = result
        self._raise = raise_with

    async def extract(self, image_path: str) -> OCRResult:
        if self._raise:
            raise self._raise
        return self._result or OCRResult(
            text_lines=["Mock Cafe", "Banjara Hills"],
            full_text="Mock Cafe\nBanjara Hills",
            avg_confidence=0.95,
            backend=self.name,
        )


class TestExtractText:
    @pytest.mark.asyncio
    async def test_returns_result_from_backend(self):
        backend = MockBackend()
        result = await extract_text("/fake/path.jpg", backend=backend)
        assert result.text_lines == ["Mock Cafe", "Banjara Hills"]
        assert result.avg_confidence == 0.95

    @pytest.mark.asyncio
    async def test_backend_crash_wrapped_as_ocr_error(self):
        backend = MockBackend(raise_with=RuntimeError("boom"))
        with pytest.raises(OCRError, match="OCR failed"):
            await extract_text("/fake/path.jpg", backend=backend)

    @pytest.mark.asyncio
    async def test_ocr_error_passes_through(self):
        backend = MockBackend(raise_with=OCRError("explicit"))
        with pytest.raises(OCRError, match="explicit"):
            await extract_text("/fake/path.jpg", backend=backend)


class TestOCRResultLowConfidence:
    def test_high_confidence_not_flagged(self):
        r = OCRResult(text_lines=["Hello"], full_text="Hello world", avg_confidence=0.9)
        assert not r.is_low_confidence

    def test_low_confidence_flagged(self):
        r = OCRResult(text_lines=["Hi"], full_text="Hi", avg_confidence=0.4)
        assert r.is_low_confidence

    def test_very_short_text_flagged(self):
        # Even high confidence on 2 chars is suspicious
        r = OCRResult(text_lines=["Hi"], full_text="Hi", avg_confidence=0.95)
        assert r.is_low_confidence


class TestPaddleResultParsing:
    """Test the parser against synthetic PaddleOCR output shapes."""

    def test_v2_format(self):
        # PaddleOCR v2.x: [[ [box, (text, conf)], ... ]]
        raw = [
            [
                [[[0, 0], [10, 0], [10, 10], [0, 10]], ("Roastery Coffee", 0.95)],
                [[[0, 20], [10, 20], [10, 30], [0, 30]], ("Banjara Hills", 0.88)],
            ]
        ]
        result = _parse_paddle_result(raw, backend="paddleocr")
        assert result.text_lines == ["Roastery Coffee", "Banjara Hills"]
        assert result.full_text == "Roastery Coffee\nBanjara Hills"
        assert 0.91 < result.avg_confidence < 0.92  # average of 0.95 and 0.88
        assert result.backend == "paddleocr"

    def test_v3_format(self):
        # PaddleOCR v3.x flattened: [[ [box, text, conf], ... ]]
        raw = [
            [
                [[[0, 0], [10, 0], [10, 10], [0, 10]], "Cafe Niloufer", 0.92],
            ]
        ]
        result = _parse_paddle_result(raw, backend="paddleocr")
        assert result.text_lines == ["Cafe Niloufer"]
        assert result.avg_confidence == 0.92

    def test_empty_result(self):
        result = _parse_paddle_result([None], backend="paddleocr")
        assert result.text_lines == []
        assert result.full_text == ""
        assert result.avg_confidence == 0.0

    def test_completely_empty(self):
        result = _parse_paddle_result([], backend="paddleocr")
        assert result.text_lines == []

    def test_malformed_lines_skipped_gracefully(self):
        raw = [
            [
                [[[0, 0]], ("Good text", 0.9)],
                "this is not a valid line",
                [[[0, 0]], None],  # malformed
                [[[0, 0]], ("Another good", 0.85)],
            ]
        ]
        result = _parse_paddle_result(raw, backend="paddleocr")
        # Only well-formed lines kept
        assert "Good text" in result.text_lines
        assert "Another good" in result.text_lines
        assert len(result.text_lines) == 2


class TestPaddleBackendLazyInit:
    def test_engine_not_loaded_until_use(self):
        backend = PaddleOCRBackend()
        assert backend._engine is None

    def test_missing_paddleocr_raises_clear_error(self, monkeypatch):
        backend = PaddleOCRBackend()

        # Simulate paddleocr not installed
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "paddleocr":
                raise ImportError("No module named 'paddleocr'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(OCRError, match="paddleocr is not installed"):
            backend._get_engine()
