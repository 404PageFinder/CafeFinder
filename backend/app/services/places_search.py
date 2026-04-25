"""Google Places (New) text search client.

Uses the v1 endpoint with field mask for cheaper, more accurate results
than legacy Places API. Deduplicates by place_id across multiple queries.
"""

import httpx
from dataclasses import dataclass, field

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.rating,places.userRatingCount,places.primaryType,"
    "places.googleMapsUri,places.types"
)


@dataclass
class PlaceCandidate:
    google_place_id: str
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    rating: float | None = None
    review_count: int | None = None
    category: str = ""
    types: list[str] = field(default_factory=list)
    maps_url: str = ""
    raw: dict = field(default_factory=dict)


async def search_places(queries: list[str], max_per_query: int = 5) -> list[PlaceCandidate]:
    """Run each query through Places, dedupe by place_id, return combined list."""
    seen: dict[str, PlaceCandidate] = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for q in queries:
            if not q or not q.strip():
                continue
            try:
                results = await _text_search(client, q.strip(), max_per_query)
            except Exception as e:
                log.warning("Places search failed for '%s': %s", q, e)
                continue
            for p in results:
                if p.google_place_id and p.google_place_id not in seen:
                    seen[p.google_place_id] = p
    return list(seen.values())


async def _text_search(
    client: httpx.AsyncClient, query: str, max_results: int
) -> list[PlaceCandidate]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = {"textQuery": query, "maxResultCount": max_results}
    r = await client.post(PLACES_URL, headers=headers, json=body)
    if r.status_code != 200:
        log.warning("Places API %s: %s", r.status_code, r.text[:300])
        return []

    data = r.json()
    out: list[PlaceCandidate] = []
    for p in data.get("places", []):
        loc = p.get("location") or {}
        out.append(
            PlaceCandidate(
                google_place_id=p.get("id", ""),
                name=(p.get("displayName") or {}).get("text", ""),
                address=p.get("formattedAddress", ""),
                latitude=loc.get("latitude"),
                longitude=loc.get("longitude"),
                rating=p.get("rating"),
                review_count=p.get("userRatingCount"),
                category=p.get("primaryType", "") or "",
                types=p.get("types", []) or [],
                maps_url=p.get("googleMapsUri", ""),
                raw=p,
            )
        )
    return out
