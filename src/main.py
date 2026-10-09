import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from src.container import Container
from src.documents_router import router as documents_router
from src.internal_router import router as internal_router
from src.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    settings.require_service_settings()
    redis = Redis.from_url(settings.redis_url)
    app.state.container = Container(settings, redis=redis)
    app.state.container.index_queue
    try:
        yield
    finally:
        await app.state.container.close()
        await redis.aclose()


app = FastAPI(title="books-rag", lifespan=lifespan)
app.include_router(documents_router)
app.include_router(internal_router)
