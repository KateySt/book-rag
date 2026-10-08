from functools import cached_property

from arq.connections import ArqRedis

from src.clients.callback_client import CallbackClient
from src.clients.claude_client import ClaudeClient
from src.clients.storage_client import StorageClient
from src.clients.voyage_client import VoyageClient
from src.db.vector_store import VectorStore
from src.ingestion.chunking import DocumentChunker
from src.ingestion.grouping import ChunkGrouper
from src.prompts import load_prompt
from src.services.document_service import DocumentService
from src.services.indexing import IndexingService
from src.services.rag_service import RagService
from src.services.runs import RunRegistry
from src.settings import Settings


class Container:
    def __init__(self, settings: Settings, *, redis: ArqRedis | None = None) -> None:
        self.settings = settings
        self.redis = redis

    @cached_property
    def storage(self) -> StorageClient:
        s = self.settings
        return StorageClient(
            endpoint=s.minio_endpoint,
            access_key=s.minio_access_key.get_secret_value(),
            secret_key=s.minio_secret_key.get_secret_value(),
            bucket=s.minio_documents_bucket,
            region=s.minio_region,
            secure=s.minio_secure,
            max_object_size=s.max_upload_size_bytes,
        )

    @cached_property
    def voyage(self) -> VoyageClient:
        s = self.settings
        return VoyageClient(
            api_key=s.voyage_api_key.get_secret_value(),
            model=s.voyage_model,
            rerank_model=s.voyage_rerank_model,
        )

    @cached_property
    def claude(self) -> ClaudeClient:
        s = self.settings
        return ClaudeClient(
            api_key=s.anthropic_api_key.get_secret_value(),
            model=s.anthropic_model,
            max_tokens=s.anthropic_max_token,
            answer_prompt=load_prompt("answer"),
        )

    @cached_property
    def callback(self) -> CallbackClient:
        s = self.settings
        return CallbackClient(base_url=s.animal_callback_url, token=s.internal_service_token.get_secret_value())

    @cached_property
    def store(self) -> VectorStore:
        s = self.settings
        return VectorStore(url=s.qdrant_url, collection=s.qdrant_collection, bm25_language=s.bm25_language)

    @cached_property
    def chunker(self) -> DocumentChunker:
        s = self.settings
        return DocumentChunker(
            tokenizer_name=s.voyage_tokenizer,
            chunk_max_tokens=s.chunk_max_tokens,
            max_pages=s.max_pdf_pages,
            max_file_size=s.max_upload_size_bytes,
            document_timeout=s.docling_document_timeout,
            ocr_min_chars_per_page=s.ocr_min_chars_per_page,
        )

    @cached_property
    def grouper(self) -> ChunkGrouper:
        s = self.settings
        return ChunkGrouper(
            group_min_tokens=s.group_min_tokens,
            group_max_tokens=s.group_max_tokens,
            batch_max_tokens=s.batch_max_tokens,
        )

    @cached_property
    def runs(self) -> RunRegistry | None:
        return RunRegistry(self.redis) if self.redis is not None else None

    @cached_property
    def indexing(self) -> IndexingService:
        return IndexingService(
            chunker=self.chunker,
            grouper=self.grouper,
            voyage=self.voyage,
            store=self.store,
            runs=self.runs,
        )

    @cached_property
    def rag(self) -> RagService:
        return RagService(voyage=self.voyage, store=self.store, claude=self.claude)

    @cached_property
    def documents(self) -> DocumentService:
        if self.redis is None or self.runs is None:
            raise RuntimeError("DocumentService needs a Redis connection")
        return DocumentService(
            arq=self.redis,
            storage=self.storage,
            store=self.store,
            runs=self.runs,
            max_upload_size=self.settings.max_upload_size_bytes,
            max_queued_jobs=self.settings.max_queued_jobs,
        )

    async def close(self) -> None:
        created = self.__dict__
        if "callback" in created:
            await self.callback.close()
        if "claude" in created:
            await self.claude.close()
        if "store" in created:
            await self.store.close()
