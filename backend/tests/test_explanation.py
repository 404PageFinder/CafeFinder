"""Tests for the human-readable explanation generator."""

from app.schemas.llm import LLMExtraction, LocationClues, PlaceCandidate as LLMCandidate
from app.services.explanation import build_explanation
from app.services.places_search import PlaceCandidate as GPCandidate
from app.services.ranking_engine import RankedResult


def make_ranked(name="Roastery Coffee House", address="Banjara Hills, Hyderabad",
                rating=4.5, reviews=1200, confidence=0.91, reasons=None):
    return [
        RankedResult(
            rank=1,
            place=GPCandidate(
                google_place_id="id_x",
                name=name,
                address=address,
                rating=rating,
                review_count=reviews,
                maps_url="https://maps.google.com/x",
            ),
            confidence=confidence,
            reason=reasons or ["Exact name match", "City matched"],
        )
    ]


def make_extraction(name="Roastery Coffee House", evidence=None, question=None):
    return LLMExtraction(
        place_candidates=[
            LLMCandidate(
                name=name,
                city="Hyderabad",
                area="Banjara Hills",
                category="cafe",
                confidence=0.9,
                evidence=evidence or ["Name found in OCR", "Area in description"],
            )
        ],
        location_clues=LocationClues(city="Hyderabad", area="Banjara Hills"),
        suggested_user_question=question,
    )


class TestExplanationContent:
    def test_high_confidence_uses_confident_prefix(self):
        text = build_explanation(make_extraction(), make_ranked(), "high")
        assert "Most likely:" in text
        assert "Roastery Coffee House" in text

    def test_medium_confidence_uses_hedging_prefix(self):
        text = build_explanation(make_extraction(), make_ranked(confidence=0.7), "medium")
        assert "Best guess:" in text

    def test_low_confidence_recommends_screenshot(self):
        text = build_explanation(make_extraction(), make_ranked(confidence=0.4), "low")
        assert "Uncertain" in text
        assert "screenshot" in text.lower()

    def test_includes_rating_and_review_count(self):
        text = build_explanation(
            make_extraction(),
            make_ranked(rating=4.5, reviews=1200),
            "high",
        )
        assert "4.5" in text
        # Reviews of 1200 should render as "1k reviews"
        assert "k reviews" in text or "1200" in text

    def test_handles_review_count_under_1000(self):
        text = build_explanation(
            make_extraction(), make_ranked(rating=4.2, reviews=350), "high"
        )
        assert "350" in text

    def test_handles_no_rating(self):
        text = build_explanation(
            make_extraction(), make_ranked(rating=None, reviews=None), "high"
        )
        assert "Roastery Coffee House" in text  # No crash, no rating mentioned


class TestExplanationEmptyCases:
    def test_no_results_with_question(self):
        ext = make_extraction(question="Could you tell me the city?")
        text = build_explanation(ext, [], "none")
        assert "Could you tell me the city?" in text

    def test_no_results_no_question_uses_default(self):
        text = build_explanation(LLMExtraction(), [], "none")
        assert "screenshot" in text.lower() or "couldn't" in text.lower()


class TestExplanationReasons:
    def test_includes_top_reasons(self):
        text = build_explanation(
            make_extraction(),
            make_ranked(reasons=["Exact name match: 'Roastery'", "City 'Hyderabad' matched"]),
            "high",
        )
        assert "Exact name match" in text or "City" in text

    def test_medium_includes_evidence_basis(self):
        ext = make_extraction(evidence=["name in description", "area in hashtag"])
        text = build_explanation(ext, make_ranked(confidence=0.7), "medium")
        assert "Based on" in text or "name in description" in text.lower()
