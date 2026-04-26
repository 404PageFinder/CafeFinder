"""Builds human-readable explanation strings for analysis results.

The `reason` array on each ranked result is structured data; this module
produces a short prose summary for the API and the mobile UI.
"""

from app.schemas.llm import LLMExtraction
from app.services.ranking_engine import RankedResult


def build_explanation(
    extraction: LLMExtraction,
    ranked: list[RankedResult],
    confidence_level: str,
) -> str:
    """Single-string summary of why a place was selected (or why we're unsure)."""
    if not ranked:
        if extraction.suggested_user_question:
            return f"I couldn't identify the place. {extraction.suggested_user_question}"
        return (
            "I couldn't identify a cafe or restaurant from this video. "
            "Try uploading a screenshot showing the signboard or menu."
        )

    top = ranked[0]
    place = top.place
    reasons = top.reason or []
    evidence = (
        extraction.place_candidates[0].evidence
        if extraction.place_candidates
        else []
    )

    # Build location phrase from address
    location = place.address.split(",")[0:2]
    where = ", ".join(s.strip() for s in location) if location else place.address

    quality_bits = []
    if place.rating:
        quality_bits.append(f"{place.rating}★")
    if place.review_count:
        if place.review_count >= 1000:
            quality_bits.append(f"{place.review_count // 1000}k reviews")
        else:
            quality_bits.append(f"{place.review_count} reviews")
    quality_str = f" ({', '.join(quality_bits)})" if quality_bits else ""

    prefix = {
        "high": "Most likely:",
        "medium": "Best guess:",
        "low": "Uncertain match:",
        "none": "Could not identify:",
    }.get(confidence_level, "Result:")

    summary = f"{prefix} {place.name} in {where}{quality_str}."

    # Add up to 2 strongest reasons
    if reasons:
        top_reasons = reasons[:2]
        summary += " " + " · ".join(top_reasons) + "."

    # If evidence array adds new info, append briefly
    if evidence and confidence_level in ("medium", "low"):
        summary += f" Based on: {', '.join(evidence[:2]).lower()}."

    if confidence_level == "low":
        summary += " Consider uploading a screenshot to confirm."
    elif confidence_level == "medium" and len(ranked) > 1:
        summary += f" {len(ranked) - 1} alternative(s) shown below."

    return summary
