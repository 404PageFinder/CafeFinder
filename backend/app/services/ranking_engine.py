"""Ranking engine v1.5 — branch-aware scoring + category filtering.

Improvements over v1.0:
1. Hard food-category filter (with safety fallback): drop non-food places
   like hardware stores when we have enough food-tagged candidates.
2. Chain detection: when multiple candidates share the same name, name
   match weight drops and location match weight rises (since name alone
   can't disambiguate Starbucks branches).
3. Branch penalty: when LLM specified an area and a candidate's address
   doesn't contain it, that candidate is demoted — a same-name place in
   the WRONG area is more misleading than a different-name place.
4. Soft city/area scoring respects partial matches.
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
    "dessert",
    "ice_cream_shop",
}

FOOD_NAME_KEYWORDS = (
    "cafe", "café", "coffee", "restaurant", "kitchen", "bistro",
    "diner", "bar", "bakery", "eatery", "pizzeria", "grill",
    "tea", "chai", "roastery", "deli", "patisserie",
)

# Tunable weights — chain mode shifts emphasis to location
W_NORMAL = {"name": 0.35, "loc": 0.20, "cat": 0.15, "ev": 0.15, "qual": 0.10, "meta": 0.05}
W_CHAIN = {"name": 0.20, "loc": 0.40, "cat": 0.10, "ev": 0.15, "qual": 0.10, "meta": 0.05}


def filter_food_places(places: list[GPCandidate], min_keep: int = 3) -> list[GPCandidate]:
    """Soft filter: drop non-food places only if we still have enough candidates."""
    food = [p for p in places if _is_food_place(p)]
    if len(food) >= min_keep:
        return food
    return places


def _is_food_place(p: GPCandidate) -> bool:
    types = {t.lower() for t in (p.types or [])}
    cat = (p.category or "").lower()
    name_lower = (p.name or "").lower()

    if types & CAFE_LIKE:
        return True
    if any(t in cat for t in CAFE_LIKE):
        return True
    if any(kw in name_lower for kw in FOOD_NAME_KEYWORDS):
        return True
    return False


def _is_chain_situation(candidates: list[GPCandidate]) -> bool:
    """Detect chain/branch situation: 2+ candidates with very similar names."""
    if len(candidates) < 2:
        return False
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            score = fuzz.token_set_ratio(
                (candidates[i].name or "").lower(),
                (candidates[j].name or "").lower(),
            )
            if score >= 85:
                return True
    return False


def rank_places(
    llm_extraction: LLMExtraction,
    google_places: list[GPCandidate],
    top_k: int = 3,
) -> list[RankedResult]:
    if not google_places:
        return []

    # 1. Category filter
    candidates = filter_food_places(google_places, min_keep=3)
    if not candidates:
        candidates = google_places

    # 2. Detect chain situation, pick weights
    is_chain = _is_chain_situation(candidates)
    weights = W_CHAIN if is_chain else W_NORMAL

    primary_llm: LLMCandidate | None = (
        llm_extraction.place_candidates[0] if llm_extraction.place_candidates else None
    )
    clues = llm_extraction.location_clues
    has_area_hint = bool((primary_llm.area if primary_llm else "") or clues.area)

    # 3. Score each candidate
    scored: list[tuple[float, list[str], GPCandidate]] = []
    for gp in candidates:
        name_score, name_reason = _name_score(primary_llm, gp)
        loc_score, loc_reason, area_matched = _location_score(primary_llm, clues, gp)
        cat_score, cat_reason = _category_score(primary_llm, gp)
        ev_score = _evidence_strength(primary_llm)
        qual_score = _places_quality(gp)
        meta_score = primary_llm.confidence if primary_llm else 0.3

        final = (
            weights["name"] * name_score
            + weights["loc"] * loc_score
            + weights["cat"] * cat_score
            + weights["ev"] * ev_score
            + weights["qual"] * qual_score
            + weights["meta"] * meta_score
        )

        # Branch penalty: same-name place in wrong area is misleading
        if is_chain and has_area_hint and not area_matched:
            final *= 0.7

        reasons = [r for r in [name_reason, loc_reason, cat_reason] if r]
        if is_chain:
            reasons.append("Chain detected — location match prioritized")
        scored.append((round(final, 3), reasons, gp))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        RankedResult(rank=i + 1, place=gp, confidence=score, reason=reasons)
        for i, (score, reasons, gp) in enumerate(scored[:top_k])
    ]


def _name_score(llm: LLMCandidate | None, gp: GPCandidate) -> tuple[float, str | None]:
    if not llm or not llm.name:
        return 0.3, None
    score = fuzz.token_set_ratio(llm.name.lower(), (gp.name or "").lower()) / 100.0
    if score >= 0.9:
        return score, f"Exact name match: '{gp.name}'"
    if score >= 0.7:
        return score, f"Strong name similarity to '{llm.name}'"
    return score, None


def _location_score(
    llm: LLMCandidate | None,
    clues,
    gp: GPCandidate,
) -> tuple[float, str | None, bool]:
    """Returns (score, reason, area_matched_flag)."""
    addr = (gp.address or "").lower()
    score = 0.0
    reasons: list[str] = []
    area_matched = False

    city = (llm.city if llm and llm.city else clues.city).lower().strip()
    area = (llm.area if llm and llm.area else clues.area).lower().strip()
    state = (llm.state if llm and llm.state else clues.state).lower().strip()

    if city and city in addr:
        score += 0.5
        reasons.append(f"City '{city.title()}' matched")
    if area and area in addr:
        score += 0.4
        area_matched = True
        reasons.append(f"Area '{area.title()}' matched")
    if state and state in addr:
        score += 0.1

    reason = "; ".join(reasons) if reasons else None
    return min(score, 1.0), reason, area_matched


def _category_score(llm: LLMCandidate | None, gp: GPCandidate) -> tuple[float, str | None]:
    gp_cat = (gp.category or "").lower()
    gp_types = {t.lower() for t in (gp.types or [])}

    is_food = any(token in gp_cat for token in CAFE_LIKE) or bool(gp_types & CAFE_LIKE)
    if not is_food:
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
    rating_part = min(max((rating - 3.0) / 2.0, 0), 1.0)
    review_part = min(reviews / 500.0, 1.0)
    return 0.6 * rating_part + 0.4 * review_part
