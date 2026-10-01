import httpx
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.settings import ANIMAL_CALLBACK_URL, INTERNAL_SERVICE_TOKEN


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    reraise=True,
)
async def post_status(client: httpx.AsyncClient, document_id: str, status: str, error: str | None):
    response = await client.post(
        f"{ANIMAL_CALLBACK_URL}/documents/{document_id}/status",
        json={"status": status, "error": error},
        headers={"X-Internal-Token": INTERNAL_SERVICE_TOKEN},
    )
    response.raise_for_status()


async def notify_document_status(
        client: httpx.AsyncClient, document_id: str, status: str, error: str | None = None
):
    await post_status(client, document_id, status, error)

