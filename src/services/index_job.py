import logging

import anyio
import httpx
import redis.exceptions
import voyageai.error
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from vercel.blob import BlobServiceNotAvailable, BlobServiceRateLimited

from src.clients.callback_client import CallbackClient
from src.clients.storage_client import StorageClient
from src.exceptions import (
    DocumentParseError,
    ObjectMissingError,
    ObjectTooLargeError,
    RunSupersededError,
    TransientIndexError,
)
from src.schemas import IndexJobRequest
from src.services.indexing import IndexingService

logger = logging.getLogger(__name__)

TRANSIENT_ERRORS = (
    httpx.HTTPError,
    ConnectionError,
    TimeoutError,
    voyageai.error.APIConnectionError,
    voyageai.error.RateLimitError,
    voyageai.error.ServerError,
    voyageai.error.ServiceUnavailableError,
    ResponseHandlingException,
    UnexpectedResponse,
    BlobServiceNotAvailable,
    BlobServiceRateLimited,
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
)


class IndexJob:
    def __init__(
            self,
            *,
            storage: StorageClient,
            indexing: IndexingService,
            callback: CallbackClient,
            max_tries: int,
            timeout_seconds: float,
            lock_timeout_seconds: float,
    ) -> None:
        self._storage = storage
        self._indexing = indexing
        self._callback = callback
        self._max_tries = max_tries
        self._timeout_seconds = timeout_seconds
        self._lock_timeout_seconds = lock_timeout_seconds
        self._lock = anyio.Lock()

    async def run(self, request: IndexJobRequest) -> None:
        try:
            with anyio.fail_after(self._lock_timeout_seconds):
                await self._lock.acquire()
        except TimeoutError:
            logger.warning("another run is in progress, %s will be retried", request.document_id)
            raise TransientIndexError(request.document_id) from None
        try:
            await self._run(request)
        finally:
            self._lock.release()

    async def _run(self, request: IndexJobRequest) -> None:
        document_id = request.document_id
        try:
            with anyio.move_on_after(self._timeout_seconds) as deadline:
                data = await self._storage.download(request.object_name)
                count = await self._indexing.index(
                    data,
                    filename=request.filename,
                    document_id=document_id,
                    run_id=request.run_id,
                    chat_session_id=request.chat_session_id,
                )
            if deadline.cancelled_caught:
                logger.warning("indexing %s (%s) exceeded %ss", request.filename, document_id, self._timeout_seconds)
                await self._callback.notify(document_id, "failed", "document is too long to process")
                return
        except (RunSupersededError, ObjectMissingError):
            logger.info("document %s was deleted or re-uploaded, run %s skipped", document_id, request.run_id)
            return
        except ObjectTooLargeError:
            await self._callback.notify(document_id, "failed", "file too large")
            return
        except DocumentParseError as error:
            logger.warning("parse failed for %s (%s): %s", request.filename, document_id, error)
            await self._callback.notify(document_id, "failed", str(error))
            return
        except TRANSIENT_ERRORS as error:
            if request.attempt < self._max_tries:
                logger.warning("transient error for %s on try %s: %r", document_id, request.attempt, error)
                raise TransientIndexError(document_id) from error
            logger.exception("giving up on %s after %s tries", document_id, request.attempt)
            await self._callback.notify(document_id, "failed", "embedding service unavailable")
            return
        except Exception:
            logger.exception("indexing failed for %s (%s)", request.filename, document_id)
            await self._callback.notify(document_id, "failed", "embedding failed")
            return

        logger.info("indexed %s chunks for %s (%s)", count, request.filename, document_id)
        await self._callback.notify(document_id, "ready")
