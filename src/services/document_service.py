import uuid

from arq.connections import ArqRedis
from arq.constants import default_queue_name

from src.clients.storage_client import StorageClient
from src.db.vector_store import VectorStore
from src.exceptions import ObjectTooLargeError, QueueFullError, UnsupportedFileError
from src.services.runs import RunRegistry

INDEX_JOB = "index_document_job"


class DocumentService:
    def __init__(
            self,
            *,
            arq: ArqRedis,
            storage: StorageClient,
            store: VectorStore,
            runs: RunRegistry,
            max_upload_size: int,
            max_queued_jobs: int,
    ) -> None:
        self._arq = arq
        self._storage = storage
        self._store = store
        self._runs = runs
        self._max_upload_size = max_upload_size
        self._max_queued_jobs = max_queued_jobs

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
        if await self._arq.zcard(default_queue_name) >= self._max_queued_jobs:
            raise QueueFullError()

        run_id = uuid.uuid4().hex
        job = await self._arq.enqueue_job(
            INDEX_JOB,
            object_name=object_name,
            filename=filename,
            document_id=document_id,
            run_id=run_id,
            chat_session_id=chat_session_id,
            _job_id=f"index:{document_id}:{run_id}" if reindex else f"index:{document_id}",
        )
        if job is not None:
            await self._runs.start(document_id, run_id)

    async def delete(self, document_id: str) -> None:
        await self.delete_many([document_id])

    async def delete_many(self, document_ids: list[str]) -> None:
        await self._runs.mark_deleted_many(document_ids)
        await self._store.delete_documents(document_ids)
