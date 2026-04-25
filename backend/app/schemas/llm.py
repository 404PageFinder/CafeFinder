from pydantic import BaseModel, Field


class PlaceCandidate(BaseModel):
    name: str = ""
    city: str = ""
    area: str = ""
    state: str = ""
    country: str = ""
    category: str = ""
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class LocationClues(BaseModel):
    city: str = ""
    area: str = ""
    state: str = ""
    country: str = ""


class LLMExtraction(BaseModel):
    place_candidates: list[PlaceCandidate] = Field(default_factory=list)
    location_clues: LocationClues = Field(default_factory=LocationClues)
    search_queries: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    needs_user_input: bool = False
    suggested_user_question: str | None = None
