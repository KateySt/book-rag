import logging
from dataclasses import asdict

from anyio import CancelScope, to_thread

from src.clients.voyage_client import VoyageClient
from src.db.vector_store import VectorStore
from src.exceptions import DocumentParseError, RunSupersededError
from src.ingestion.chunking import Chunk, DocumentChunker
from src.ingestion.grouping import ChunkGrouper
from src.services.runs import RunRegistry

logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(
            self,
            *,
            chunker: DocumentChunker,
            grouper: ChunkGrouper,
            voyage: VoyageClient,
            store: VectorStore,
            runs: RunRegistry | None = None,
    ) -> None:
        self._chunker = chunker
        self._grouper = grouper
        self._voyage = voyage
        self._store = store
        self._runs = runs

    async def index(
            self,
            data: bytes,
            *,
            filename: str,
            document_id: str,
            run_id: str,
            chat_session_id: str | None,
    ) -> int:
        await to_thread.run_sync(self._chunker.inspect_pdf, data)
        chunks = await to_thread.run_sync(self._chunker.load_and_chunk, data, filename)
        if not chunks:
            raise DocumentParseError("no text extracted from PDF")

        ordered, vectors = await self._embed(chunks)
        payloads = [
            {
                "title": filename,
                "filename": filename,
                "document_id": document_id,
                "index_run_id": run_id,
                "chat_session_id": chat_session_id,
                **asdict(chunk),
            }
            for chunk in ordered
        ]

        await self._ensure_current(document_id, run_id)
        await self._store.ensure_collection(vector_size=len(vectors[0]))
        try:
            await self._store.upsert_chunks(vectors, payloads)
            await self._ensure_current(document_id, run_id)
        except BaseException:
            with CancelScope(shield=True):
                await self._store.delete_points(document_id, run_id=run_id)
            raise
        await self._store.delete_points(document_id, except_run_id=run_id)
        return len(payloads)

    async def _embed(self, chunks: list[Chunk]) -> tuple[list[Chunk], list[list[float]]]:
        groups = self._grouper.group_by_chapter(chunks)
        ordered: list[Chunk] = []
        vectors: list[list[float]] = []
        for batch in self._grouper.batches(groups):
            embeddings = await self._voyage.embed_documents([[chunk.embed_text for chunk in group] for group in batch])
            for group, group_vectors in zip(batch, embeddings, strict=True):
                ordered.extend(group)
                vectors.extend(group_vectors)
        logger.info("embedded %s chunks in %s groups", len(ordered), len(groups))
        return ordered, vectors

    async def _ensure_current(self, document_id: str, run_id: str) -> None:
        if self._runs is not None and not await self._runs.is_current(document_id, run_id):
            raise RunSupersededError(document_id)
