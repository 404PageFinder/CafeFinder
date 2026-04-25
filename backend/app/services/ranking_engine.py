"""Ranking engine.

Weighted score across:
- Name similarity (rapidfuzz token_set_ratio)
- Location match (city/area/state appear in formatted address)
- Category match (Google primary type vs LLM category)
- Evidence strength (count of LLM-cited evidence items)
- Places quality (rating + review count)
- Metadata confidence (LLM self-confidence)
"""

from dataclasses import dataclass

from rapidfuzz import fuzz

from app.schemas.llm import LLMExtraction, PlaceCandidate as LLMCandidate
from app.services.places_search import PlaceCandidate as GPCandidate


@dataclass
class RankedResult:
    rank: int
    place: GPCandidate
    confidence: float
    reason: list[str]


# Google Places "types" we consider valid food/drink venues
CAFE_LIKE = {
    "cafe",
    "coffee_shop",
    "bakery",
    "restaurant",
    "bar",
    "meal_takeaway",
    "meal_delivery",
    "food",
}


def rank_places(
    llm_extraction: LLMExtraction,
    google_places: list[GPCandidate],
    top_k: int = 3,
) -> list[RankedResult]:
    if not google_places:
        return []

    primary_llm: LLMCandidate | None = (
        llm_extraction.place_candidates[0] if llm_extraction.place_candidates else None
    )
    clues = llm_extraction.location_clues

    scored: list[tuple[float, list[str], GPCandidate]] = []

    for gp in google_places:
        name_score, name_reason = _name_score(primary_llm, gp)
        loc_score, loc_reason = _location_score(primary_llm, clues, gp)
        cat_score, cat_reason = _category_score(primary_llm, gp)
        ev_score = _evidence_strength(primary_llm)
        gp_score = _places_quality(gp)
        meta_score = primary_llm.confidence if primary_llm else 0.3

        final = (
            0.35 * name_score
            + 0.20 * loc_score
            + 0.15 * cat_score
            + 0.15 * ev_score
            + 0.10 * gp_score
            + 0.05 * meta_score
        )

        reasons = [r for r in [name_reason, loc_reason, cat_reason] if r]
        scored.append((round(final, 3), reasons, gp))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        RankedResult(rank=i + 1, place=gp, confidence=score, reason=reasons)
        for i, (score, reasons, gp) in enumerate(scored[:top_k])
    ]


def _name_score(llm: LLMCandidate | None, gp: GPCandidate) -> tuple[float, str | None]:
    if not llm or not llm.name:
        return 0.3, None
    score = fuzz.token_set_ratio(llm.name.lower(), gp.name.lower()) / 100.0
    if score >= 0.9:
        return score, f"Exact name match: '{gp.name}'"
    if score >= 0.7:
        return score, f"Strong name similarity to '{llm.name}'"
    return score, None


def _location_score(
    llm: LLMCandidate | None,
    clues,
    gp: GPCandidate,
) -> tuple[float, str | None]:
    addr = (gp.address or "").lower()
    score = 0.0
    reasons: list[str] = []

    city = (llm.city if llm and llm.city else clues.city).lower()
    area = (llm.area if llm and llm.area else clues.area).lower()
    state = (llm.state if llm and llm.state else clues.state).lower()

    if city and city in addr:
        score += 0.5
        reasons.append(f"City '{city.title()}' matched")
    if area and area in addr:
        score += 0.4
        reasons.append(f"Area '{area.title()}' matched")
    if state and state in addr:
        score += 0.1

    reason = "; ".join(reasons) if reasons else None
    return min(score, 1.0), reason


def _category_score(llm: LLMCandidate | None, gp: GPCandidate) -> tuple[float, str | None]:
    gp_cat = (gp.category or "").lower()
    gp_types = {t.lower() for t in (gp.types or [])}

    is_food_place = (
        any(token in gp_cat for token in CAFE_LIKE) or bool(gp_types & CAFE_LIKE)
    )
    if not is_food_place:
        return 0.2, None

    if llm and llm.category:
        llm_cat = llm.category.lower()
        if llm_cat in gp_cat or gp_cat in llm_cat or llm_cat in gp_types:
            return 1.0, f"Category match: {gp_cat or next(iter(gp_types), 'food')}"

    return 0.7, f"Food category: {gp_cat or next(iter(gp_types), 'food')}"


def _evidence_strength(llm: LLMCandidate | None) -> float:
    if not llm:
        return 0.0
    n = len(llm.evidence)
    if n >= 3:
        return 1.0
    if n == 2:
        return 0.7
    if n == 1:
        return 0.4
    return 0.1


def _places_quality(gp: GPCandidate) -> float:
    rating = gp.rating or 0
    reviews = gp.review_count or 0
    # Normalize: 3.0 rating -> 0, 5.0 -> 1.0
    rating_part = min(max((rating - 3.0) / 2.0, 0), 1.0)
    # 500+ reviews saturates to 1.0
    review_part = min(reviews / 500.0, 1.0)
    return 0.6 * rating_part + 0.4 * review_part
