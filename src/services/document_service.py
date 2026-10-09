import uuid

from src.clients.index_queue import IndexQueue
from src.clients.storage_client import StorageClient
from src.db.vector_store import VectorStore
from src.exceptions import ObjectTooLargeError, QueueUnavailableError, UnsupportedFileError
from src.schemas import IndexJobMessage
from src.services.runs import RunRegistry


class DocumentService:
    def __init__(
            self,
            *,
            queue: IndexQueue,
            storage: StorageClient,
            store: VectorStore,
            runs: RunRegistry,
            max_upload_size: int,
    ) -> None:
        self._queue = queue
        self._storage = storage
        self._store = store
        self._runs = runs
        self._max_upload_size = max_upload_size

    async def submit(
            self,
            *,
            chat_session_id: str,
            document_id: str,
            filename: str,
            object_name: str,
            reindex: bool = False,
    ) -> None:
        if not filename.lower().endswith(".pdf"):
            raise UnsupportedFileError(filename)
        if await self._storage.object_size(object_name) > self._max_upload_size:
            raise ObjectTooLargeError(object_name)

        run_id = uuid.uuid4().hex
        if reindex:
            await self._runs.start(document_id, run_id)
        elif not await self._runs.claim(document_id, run_id):
            return

        message = IndexJobMessage(
            object_name=object_name,
            filename=filename,
            document_id=document_id,
            run_id=run_id,
            chat_session_id=chat_session_id,
        )
        try:
            await self._queue.publish(message, idempotency_key=run_id)
        except QueueUnavailableError:
            if not reindex:
                await self._runs.release(document_id, run_id)
            raise

    async def delete(self, document_id: str) -> None:
        await self.delete_many([document_id])

    async def delete_many(self, document_ids: list[str]) -> None:
        await self._runs.mark_deleted_many(document_ids)
        await self._store.delete_documents(document_ids)
