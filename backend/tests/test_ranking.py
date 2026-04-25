"""Unit tests for the ranking engine.

These run without external API calls — pure in-memory scoring.
"""

from app.schemas.llm import LLMExtraction, PlaceCandidate as LLMCandidate, LocationClues
from app.services.places_search import PlaceCandidate as GPCandidate
from app.services.ranking_engine import rank_places, _name_score, _places_quality


def make_llm_extraction(name="Roastery Coffee House", city="Hyderabad", area="Banjara Hills"):
    return LLMExtraction(
        place_candidates=[
            LLMCandidate(
                name=name,
                city=city,
                area=area,
                state="Telangana",
                country="India",
                category="cafe",
                confidence=0.9,
                evidence=["Name in OCR", "Area in description", "City in title"],
            )
        ],
        location_clues=LocationClues(
            city=city, area=area, state="Telangana", country="India"
        ),
        search_queries=[f"{name} {area} {city}"],
    )


def make_gp(name, address, rating=4.5, reviews=1000, category="cafe", types=None):
    return GPCandidate(
        google_place_id=f"id_{name.lower().replace(' ', '_')}",
        name=name,
        address=address,
        latitude=17.4,
        longitude=78.4,
        rating=rating,
        review_count=reviews,
        category=category,
        types=types or [category],
        maps_url="https://maps.google.com/x",
    )


class TestRanking:
    def test_perfect_match_ranks_first(self):
        llm = make_llm_extraction()
        places = [
            make_gp("Roastery Coffee House", "Banjara Hills, Hyderabad, Telangana"),
            make_gp("Random Cafe", "Mumbai, Maharashtra", rating=3.5, reviews=50),
        ]
        ranked = rank_places(llm, places, top_k=2)
        assert ranked[0].place.name == "Roastery Coffee House"
        assert ranked[0].confidence > 0.85

    def test_empty_places_returns_empty(self):
        llm = make_llm_extraction()
        assert rank_places(llm, [], top_k=3) == []

    def test_no_llm_candidate_still_ranks(self):
        # When LLM fails, we should still surface places by quality
        empty_llm = LLMExtraction()
        places = [make_gp("Some Cafe", "Somewhere", rating=4.5, reviews=2000)]
        ranked = rank_places(empty_llm, places, top_k=1)
        assert len(ranked) == 1

    def test_top_k_limit(self):
        llm = make_llm_extraction()
        places = [make_gp(f"Cafe {i}", f"Addr {i}") for i in range(10)]
        ranked = rank_places(llm, places, top_k=3)
        assert len(ranked) == 3
        assert [r.rank for r in ranked] == [1, 2, 3]


class TestNameScore:
    def test_exact_match_scores_high(self):
        llm = LLMCandidate(name="Starbucks")
        gp = make_gp("Starbucks", "addr")
        score, reason = _name_score(llm, gp)
        assert score >= 0.9
        assert reason and "Exact" in reason

    def test_no_llm_returns_baseline(self):
        gp = make_gp("Anything", "addr")
        score, reason = _name_score(None, gp)
        assert score == 0.3
        assert reason is None


class TestPlacesQuality:
    def test_high_quality(self):
        gp = make_gp("X", "Y", rating=4.8, reviews=2000)
        assert _places_quality(gp) > 0.8

    def test_low_quality(self):
        gp = make_gp("X", "Y", rating=3.0, reviews=5)
        assert _places_quality(gp) < 0.1

    def test_no_data(self):
        gp = make_gp("X", "Y", rating=None, reviews=None)
        assert _places_quality(gp) == 0.0
