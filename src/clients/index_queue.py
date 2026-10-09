from vercel.queue import QueueClient, QueueError

from src.exceptions import QueueUnavailableError
from src.schemas import IndexJobMessage


class IndexQueue:
    def __init__(self, *, topic: str, region: str, client: QueueClient | None = None) -> None:
        self._topic = topic
        self._client = client or QueueClient(region=region)

    async def publish(self, message: IndexJobMessage, *, idempotency_key: str) -> None:
        try:
            await self._client.send(self._topic, message.model_dump(), idempotency_key=idempotency_key)
        except QueueError as error:
            raise QueueUnavailableError(str(error)) from error
