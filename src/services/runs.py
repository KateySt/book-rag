from redis.asyncio import Redis

DELETED = "deleted"
RUN_TTL_SECONDS = 7 * 24 * 3600


class RunRegistry:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def start(self, document_id: str, run_id: str) -> None:
        await self._redis.set(self._key(document_id), run_id, ex=RUN_TTL_SECONDS)

    async def mark_deleted_many(self, document_ids: list[str]) -> None:
        async with self._redis.pipeline(transaction=False) as pipe:
            for document_id in document_ids:
                pipe.set(self._key(document_id), DELETED, ex=RUN_TTL_SECONDS)
            await pipe.execute()

    async def is_current(self, document_id: str, run_id: str) -> bool:
        current = await self._redis.get(self._key(document_id))
        return current is None or current == run_id.encode()

    @staticmethod
    def _key(document_id: str) -> str:
        return f"book-rag:run:{document_id}"
