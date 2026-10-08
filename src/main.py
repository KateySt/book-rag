import logging
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from src.container import Container
from src.documents_router import router as documents_router
from src.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    settings.require_service_settings()
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.container = Container(settings, redis=redis)
    try:
        yield
    finally:
        await app.state.container.close()
        await redis.aclose()


app = FastAPI(title="books-rag", lifespan=lifespan)
app.include_router(documents_router)
