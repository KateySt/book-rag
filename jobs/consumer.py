import logging
import os

import httpx
from vercel.queue import Message, RetryAfter, subscribe

logger = logging.getLogger(__name__)

TOPIC = "book-rag-index"
CONSUMER_GROUP = "book-rag-index-relay"
REQUEST_TIMEOUT_SECONDS = 280
DEFAULT_RETRY_AFTER_SECONDS = 60


async def forward(payload: dict[str, object], *, attempt: int, client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{os.environ['BOOK_RAG_API_URL'].rstrip('/')}/internal/index",
        json={**payload, "attempt": attempt},
        headers={"X-Internal-Token": os.environ["INTERNAL_SERVICE_TOKEN"]},
    )
    if response.status_code == httpx.codes.SERVICE_UNAVAILABLE:
        raise RetryAfter(int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_SECONDS)))
    if response.is_server_error:
        response.raise_for_status()
    if response.is_client_error:
        logger.error("book-rag rejected index job for %s with %s", payload.get("document_id"), response.status_code)


@subscribe(topic=TOPIC, consumer_group=CONSUMER_GROUP, max_attempts=5, retry_after=60, max_concurrency=1)
async def relay(message: Message[dict[str, object]]) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS)) as client:
        await forward(message.payload, attempt=message.metadata.delivery_count, client=client)
