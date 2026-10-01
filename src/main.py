from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from src.documents_router import router as documents_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    app.state.http_client = http_client
    yield
    await http_client.aclose()


app = FastAPI(title="books-rag", lifespan=lifespan)
app.include_router(documents_router)