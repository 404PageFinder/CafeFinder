from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import engine, Base
from app.routers import analyze, health

# Import models so SQLAlchemy registers them on Base.metadata
from app.models import search_history, extracted_clues, place_result  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP-only: auto-create tables. Use Alembic migrations in production.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health.router)
app.include_router(analyze.router)
