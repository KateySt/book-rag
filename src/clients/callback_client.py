import logging

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.TransportError)


class CallbackClient:
    def __init__(self, *, base_url: str, token: str, timeout: float = 5.0, max_attempts: int = 5) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Internal-Token": token},
            timeout=httpx.Timeout(timeout),
        )
        self._max_attempts = max_attempts

    async def notify(self, document_id: str, status: str, error: str | None = None) -> None:
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(_is_retryable),
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_exponential(multiplier=1, min=1, max=20),
                reraise=True,
            ):
                with attempt:
                    await self._post(document_id, status, error)
        except httpx.HTTPError:
            logger.exception("status callback for %s failed after retries", document_id)

    async def _post(self, document_id: str, status: str, error: str | None) -> None:
        response = await self._client.post(f"/documents/{document_id}/status", json={"status": status, "error": error})
        if response.status_code == httpx.codes.NOT_FOUND:
            logger.info("document %s no longer exists in animal, status %s dropped", document_id, status)
            return
        response.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()
