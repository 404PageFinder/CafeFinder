from typing import Literal
from uuid import UUID

from pydantic import BaseModel, HttpUrl, Field


class AnalyzeLinkRequest(BaseModel):
    user_id: str | None = None
    url: HttpUrl
    user_hint_city: str | None = None


class AnalyzeLinkResponse(BaseModel):
    search_id: UUID
    status: str


class PlaceResultOut(BaseModel):
    rank: int
    name: str
    address: str
    latitude: float | None
    longitude: float | None
    rating: float | None
    review_count: int | None
    maps_url: str | None
    confidence: float
    reason: list[str]


class SearchResultsResponse(BaseModel):
    search_id: UUID
    status: str
    confidence_level: Literal["high", "medium", "low", "none"] | None = None
    needs_user_input: bool = False
    suggested_user_question: str | None = None
    results: list[PlaceResultOut] = Field(default_factory=list)
