"""Integration tests for the screenshot pipeline.

OCR, LLM, and Places are all mocked. We verify the wiring:
- screenshot path → OCR text → LLM input → Places search → ranked results
- LLM input includes ocr_text
- Cleanup is the caller's responsibility (verified separately in test_storage)
"""

import pytest
from unittest.mock import patch

from app.schemas.llm import LLMExtraction, LocationClues, PlaceCandidate as LLMCandidate
from app.services.analyzer import run_pipeline_for_screenshot
from app.services.ocr import OCRError, OCRResult
from app.services.places_search import PlaceCandidate as GPCandidate


def fake_ocr_result():
    return OCRResult(
        text_lines=["Roastery Coffee House", "Banjara Hills", "Coffee | Brunch"],
        full_text="Roastery Coffee House\nBanjara Hills\nCoffee | Brunch",
        avg_confidence=0.92,
        backend="paddleocr",
    )


def fake_llm_result():
    return LLMExtraction(
        place_candidates=[
            LLMCandidate(
                name="Roastery Coffee House",
                city="Hyderabad",
                area="Banjara Hills",
                state="Telangana",
                country="India",
                category="cafe",
                confidence=0.93,
                evidence=["Name in OCR signboard", "Area in OCR text"],
            )
        ],
        location_clues=LocationClues(
            city="Hyderabad", area="Banjara Hills", state="Telangana", country="India"
        ),
        search_queries=["Roastery Coffee House Banjara Hills Hyderabad"],
    )


def fake_places():
    return [
        GPCandidate(
            google_place_id="ChIJ_roastery_bh",
            name="Roastery Coffee House",
            address="Road No. 36, Jubilee Hills, Hyderabad, Telangana",
            latitude=17.4,
            longitude=78.4,
            rating=4.5,
            review_count=8000,
            category="cafe",
            types=["cafe", "coffee_shop"],
            maps_url="https://maps.google.com/?cid=x",
        )
    ]


class TestScreenshotPipelineHappyPath:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_mocks(self):
        with (
            patch("app.services.analyzer.extract_text") as mock_ocr,
            patch("app.services.analyzer.extract_places") as mock_llm,
            patch("app.services.analyzer.search_places") as mock_search,
        ):
            mock_ocr.return_value = fake_ocr_result()
            mock_llm.return_value = fake_llm_result()
            mock_search.return_value = fake_places()

            result = await run_pipeline_for_screenshot("/fake/img.png")

            assert result.error is None
            assert result.ocr_result.text_lines == [
                "Roastery Coffee House", "Banjara Hills", "Coffee | Brunch",
            ]
            assert len(result.ranked) == 1
            assert result.ranked[0].place.name == "Roastery Coffee House"
            assert result.confidence_level in ("high", "medium")

    @pytest.mark.asyncio
    async def test_ocr_text_passed_to_llm(self):
        captured = {}

        async def capture_llm(payload):
            captured["payload"] = payload
            return fake_llm_result()

        with (
            patch("app.services.analyzer.extract_text") as mock_ocr,
            patch("app.services.analyzer.extract_places", side_effect=capture_llm),
            patch("app.services.analyzer.search_places", return_value=fake_places()),
        ):
            mock_ocr.return_value = fake_ocr_result()
            await run_pipeline_for_screenshot("/fake/img.png")

        assert captured["payload"]["platform"] == "screenshot"
        assert captured["payload"]["ocr_text"] == [
            "Roastery Coffee House", "Banjara Hills", "Coffee | Brunch",
        ]
        # YouTube-only fields should be empty
        assert captured["payload"]["title"] == ""
        assert captured["payload"]["description"] == ""

    @pytest.mark.asyncio
    async def test_user_hint_city_propagates(self):
        captured = {}

        async def capture_llm(payload):
            captured["payload"] = payload
            return fake_llm_result()

        with (
            patch("app.services.analyzer.extract_text", return_value=fake_ocr_result()),
            patch("app.services.analyzer.extract_places", side_effect=capture_llm),
            patch("app.services.analyzer.search_places", return_value=fake_places()),
        ):
            await run_pipeline_for_screenshot("/fake/img.png", user_hint_city="Mumbai")

        assert captured["payload"]["user_hint_city"] == "Mumbai"


class TestScreenshotPipelineErrorPaths:
    @pytest.mark.asyncio
    async def test_ocr_failure_returns_helpful_error(self):
        with patch(
            "app.services.analyzer.extract_text",
            side_effect=OCRError("Image corrupt"),
        ):
            result = await run_pipeline_for_screenshot("/fake/img.png")

        assert result.error_kind == "ocr_failed"
        assert "screenshot" in result.explanation.lower() or "image" in result.explanation.lower()
        assert result.ranked == []

    @pytest.mark.asyncio
    async def test_empty_ocr_returns_helpful_error(self):
        empty = OCRResult(text_lines=[], full_text="", avg_confidence=0.0, backend="paddleocr")
        with patch("app.services.analyzer.extract_text", return_value=empty):
            result = await run_pipeline_for_screenshot("/fake/img.png")

        assert result.error_kind == "ocr_failed"
        assert result.error == "no_text_detected"

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_crash_pipeline(self):
        """Even if LLM fails, the pipeline should return a PipelineResult."""
        with (
            patch("app.services.analyzer.extract_text", return_value=fake_ocr_result()),
            patch("app.services.analyzer.extract_places", side_effect=Exception("LLM down")),
            patch("app.services.analyzer.search_places", return_value=[]),
        ):
            result = await run_pipeline_for_screenshot("/fake/img.png")

        # Pipeline completed but flagged the error
        assert result.error_kind == "internal"
        assert "llm_failed" in result.error
        assert result.ranked == []


class TestUnifiedSearchIdContract:
    """The screenshot path must produce a PipelineResult shape compatible
    with the YouTube path so /search/{id}/results works for both.
    """

    @pytest.mark.asyncio
    async def test_pipeline_result_has_same_shape_as_youtube(self):
        with (
            patch("app.services.analyzer.extract_text", return_value=fake_ocr_result()),
            patch("app.services.analyzer.extract_places", return_value=fake_llm_result()),
            patch("app.services.analyzer.search_places", return_value=fake_places()),
        ):
            result = await run_pipeline_for_screenshot("/fake/img.png")

        # All fields the results endpoint reads from must be present
        assert hasattr(result, "extraction")
        assert hasattr(result, "ranked")
        assert hasattr(result, "confidence_level")
        assert hasattr(result, "explanation")
        # And screenshot-specific fields populated
        assert result.ocr_result is not None
        # YouTube-specific fields should be None for a screenshot input
        assert result.metadata is None
        assert result.parsed_url is None
