from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import Base, engine
from app.routers import analyze, feedback, health

# Import models so SQLAlchemy registers them on Base.metadata
from app.models import (  # noqa: F401
    extracted_clues,
    feedback as feedback_model,
    place_result,
    search_history,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health.router)
app.include_router(analyze.router)
app.include_router(feedback.router)
