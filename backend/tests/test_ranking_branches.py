"""Tests for the v1.5 ranking improvements:
- Chain detection
- Branch penalty (right name, wrong area)
- Category filtering
"""

from app.schemas.llm import LLMExtraction, LocationClues, PlaceCandidate as LLMCandidate
from app.services.places_search import PlaceCandidate as GPCandidate
from app.services.ranking_engine import (
    _is_chain_situation,
    filter_food_places,
    rank_places,
)


def make_llm(name="Starbucks", city="Mumbai", area="Bandra"):
    return LLMExtraction(
        place_candidates=[
            LLMCandidate(
                name=name,
                city=city,
                area=area,
                state="Maharashtra",
                country="India",
                category="cafe",
                confidence=0.85,
                evidence=["Name in title", f"Area '{area}' in description", f"City '{city}' in hashtag"],
            )
        ],
        location_clues=LocationClues(city=city, area=area, state="Maharashtra", country="India"),
    )


def gp(name, address, types=None, category="cafe", rating=4.3, reviews=500, place_id=None):
    return GPCandidate(
        google_place_id=place_id or f"id_{name}_{address}".replace(" ", "_"),
        name=name,
        address=address,
        latitude=19.0,
        longitude=72.8,
        rating=rating,
        review_count=reviews,
        category=category,
        types=types or ["cafe", "food"],
        maps_url="https://maps.google.com/x",
    )


class TestChainDetection:
    def test_two_starbucks_branches_is_chain(self):
        places = [
            gp("Starbucks", "Bandra, Mumbai"),
            gp("Starbucks", "Andheri, Mumbai"),
        ]
        assert _is_chain_situation(places) is True

    def test_two_unrelated_cafes_not_chain(self):
        places = [
            gp("Roastery Coffee", "Banjara Hills, Hyderabad"),
            gp("Driftwood Cafe", "Jubilee Hills, Hyderabad"),
        ]
        assert _is_chain_situation(places) is False

    def test_single_place_not_chain(self):
        assert _is_chain_situation([gp("Solo Cafe", "Anywhere")]) is False

    def test_empty_not_chain(self):
        assert _is_chain_situation([]) is False


class TestBranchDisambiguation:
    def test_correct_branch_ranks_first(self):
        """When LLM says Bandra, the Bandra Starbucks must outrank Andheri."""
        llm = make_llm(name="Starbucks", city="Mumbai", area="Bandra")
        places = [
            # Same quality on both branches — only area differentiates
            gp("Starbucks", "Andheri West, Mumbai, Maharashtra", rating=4.3, reviews=800, place_id="id_andheri"),
            gp("Starbucks", "Bandra West, Mumbai, Maharashtra", rating=4.3, reviews=800, place_id="id_bandra"),
        ]
        ranked = rank_places(llm, places, top_k=2)
        assert ranked[0].place.google_place_id == "id_bandra"
        # Wrong-branch confidence should be visibly lower
        assert ranked[0].confidence > ranked[1].confidence

    def test_branch_penalty_demotes_wrong_area(self):
        """Wrong-area branch loses ~30% of its score under chain-mode penalty."""
        llm = make_llm(name="Third Wave Coffee", city="Bengaluru", area="Indiranagar")
        places = [
            gp("Third Wave Coffee", "Indiranagar, Bengaluru", place_id="id_correct"),
            gp("Third Wave Coffee", "HSR Layout, Bengaluru", place_id="id_wrong1"),
            gp("Third Wave Coffee", "Koramangala, Bengaluru", place_id="id_wrong2"),
        ]
        ranked = rank_places(llm, places, top_k=3)
        assert ranked[0].place.google_place_id == "id_correct"
        # Confidence gap between correct and wrong should be meaningful
        assert ranked[0].confidence - ranked[1].confidence > 0.05


class TestCategoryFilter:
    def test_filter_drops_hardware_store_when_enough_cafes(self):
        places = [
            gp("Roastery Coffee", "Hyderabad", types=["cafe", "coffee_shop"]),
            gp("Roastery Coffee", "Mumbai", types=["cafe"]),
            gp("Roastery Coffee", "Delhi", types=["cafe"]),
            gp("The Roastery Hardware", "Pune", types=["hardware_store"], category="hardware_store"),
        ]
        filtered = filter_food_places(places, min_keep=3)
        names_addresses = [(p.name, p.address) for p in filtered]
        assert ("The Roastery Hardware", "Pune") not in names_addresses
        assert len(filtered) == 3

    def test_filter_keeps_all_when_too_few_food_places(self):
        """Safety net — never drop everything if food-tagged candidates are scarce."""
        places = [
            gp("Some Place", "X", types=["store"], category="store"),
            gp("Roastery Coffee", "Y", types=["cafe"]),
        ]
        filtered = filter_food_places(places, min_keep=3)
        # We have only 1 food place, less than min_keep, so don't filter
        assert len(filtered) == 2

    def test_food_keyword_in_name_qualifies(self):
        """A place with 'cafe' in the name passes even without food types."""
        places = [
            gp("Mystery Cafe", "X", types=["point_of_interest"], category="point_of_interest"),
            gp("Real Cafe A", "Y", types=["cafe"]),
            gp("Real Cafe B", "Z", types=["cafe"]),
            gp("Real Cafe C", "W", types=["cafe"]),
        ]
        filtered = filter_food_places(places, min_keep=3)
        # 3 food-typed + 1 keyword-matched = all 4 qualify
        assert len(filtered) == 4


class TestEndToEndChainScenario:
    def test_starbucks_bandra_full_pipeline(self):
        """The headline Phase 1.5 use case."""
        llm = make_llm(name="Starbucks", city="Mumbai", area="Bandra")
        places = [
            gp("Starbucks", "Andheri West, Mumbai", place_id="A"),
            gp("Starbucks", "Bandra West, Mumbai", place_id="B"),
            gp("Starbucks", "Powai, Mumbai", place_id="C"),
            gp("Starbucks Reserve", "BKC, Mumbai", place_id="D"),
        ]
        ranked = rank_places(llm, places, top_k=3)
        assert ranked[0].place.google_place_id == "B"
        # Chain detection should have added an explanatory reason
        assert any("Chain" in r for r in ranked[0].reason)

    def test_no_area_hint_falls_back_gracefully(self):
        """Without area hint, can't disambiguate — but pipeline still ranks."""
        llm = LLMExtraction(
            place_candidates=[
                LLMCandidate(name="Starbucks", city="Mumbai", confidence=0.7, evidence=["name"])
            ],
            location_clues=LocationClues(city="Mumbai"),
        )
        places = [
            gp("Starbucks", "Andheri, Mumbai", reviews=2000, rating=4.5),
            gp("Starbucks", "Bandra, Mumbai", reviews=500, rating=4.0),
        ]
        ranked = rank_places(llm, places, top_k=2)
        # Both should be returned, no crash, top-1 picked by quality
        assert len(ranked) == 2
        assert ranked[0].place.review_count >= ranked[1].place.review_count
