import logging

from arq import Retry

from src.container import Container
from src.exceptions import DocumentParseError, ObjectMissingError, ObjectTooLargeError, RunSupersededError
from src.worker.errors import TRANSIENT_ERRORS

logger = logging.getLogger(__name__)

RETRY_DELAY_SECONDS = 30


class IndexDocumentJob:
    def __init__(self, container: Container, *, max_tries: int) -> None:
        self._container = container
        self._max_tries = max_tries

    async def run(
            self,
            *,
            job_try: int,
            object_name: str,
            filename: str,
            document_id: str,
            run_id: str,
            chat_session_id: str,
    ) -> None:
        callback = self._container.callback
        try:
            data = await self._container.storage.download(object_name)
            count = await self._container.indexing.index(
                data,
                filename=filename,
                document_id=document_id,
                run_id=run_id,
                chat_session_id=chat_session_id,
            )
        except (RunSupersededError, ObjectMissingError):
            logger.info("document %s was deleted or re-uploaded, run %s skipped", document_id, run_id)
            return
        except ObjectTooLargeError:
            await callback.notify(document_id, "failed", "file too large")
            return
        except DocumentParseError as error:
            logger.warning("parse failed for %s (%s): %s", filename, document_id, error)
            await callback.notify(document_id, "failed", str(error))
            return
        except TRANSIENT_ERRORS as error:
            if job_try < self._max_tries:
                logger.warning("transient error for %s on try %s: %r", document_id, job_try, error)
                raise Retry(defer=RETRY_DELAY_SECONDS * job_try) from error
            logger.exception("giving up on %s after %s tries", document_id, job_try)
            await callback.notify(document_id, "failed", "embedding service unavailable")
            return
        except Exception:
            logger.exception("indexing failed for %s (%s)", filename, document_id)
            await callback.notify(document_id, "failed", "embedding failed")
            return

        logger.info("indexed %s chunks for %s (%s)", count, filename, document_id)
        await callback.notify(document_id, "ready")
