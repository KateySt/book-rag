import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from starlette.types import ASGIApp, Receive, Scope, Send
from vercel.headers import HeadersContext, headers_from_asgi_scope

from src.container import Container
from src.documents_router import router as documents_router
from src.internal_router import router as internal_router
from src.settings import settings


class VercelHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with HeadersContext(headers_from_asgi_scope(scope)).use():
            await self.app(scope, receive, send)


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
app.add_middleware(VercelHeadersMiddleware)
app.include_router(documents_router)
app.include_router(internal_router)
