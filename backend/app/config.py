from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "CafeFinder"
    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str  # e.g. postgresql+asyncpg://postgres:postgres@localhost:5432/cafefinder

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # External APIs
    youtube_api_key: str
    google_places_api_key: str

    # LLM
    llm_provider: str = "openai"   # "openai" | "anthropic"
    llm_api_key: str
    llm_model: str = "gpt-4o-mini"

    # Ranking thresholds
    confidence_high: float = 0.85
    confidence_medium: float = 0.55


settings = Settings()
