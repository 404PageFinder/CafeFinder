"""Expected vs actual matching for evaluation.

Two modes:
1. Place ID exact match (gold standard)
2. Name fuzzy match (>=0.85) + city substring in actual address
"""

from dataclasses import dataclass

from rapidfuzz import fuzz


NAME_FUZZY_THRESHOLD = 85  # 0-100 scale from rapidfuzz


@dataclass
class Expected:
    place_name: str | None
    google_place_id: str | None
    city: str | None
    area: str | None = None
    country: str | None = None


@dataclass
class ActualResult:
    """Subset of fields needed for matching."""
    google_place_id: str | None
    name: str
    address: str
    confidence: float


def matches(expected: Expected, actual: ActualResult) -> bool:
    """Return True if actual is the place we expected."""
    # Mode 1: place_id exact match
    if expected.google_place_id and actual.google_place_id:
        return expected.google_place_id == actual.google_place_id

    # Mode 2: fuzzy name + city
    if not expected.place_name:
        return False
    name_score = fuzz.token_set_ratio(
        expected.place_name.lower(), (actual.name or "").lower()
    )
    if name_score < NAME_FUZZY_THRESHOLD:
        return False
    if expected.city:
        if expected.city.lower() not in (actual.address or "").lower():
            return False
    return True


def expected_in_top_n(expected: Expected, results: list[ActualResult], n: int) -> bool:
    return any(matches(expected, r) for r in results[:n])
