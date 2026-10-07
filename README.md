# Books RAG

A retrieval-augmented generation (RAG) pipeline for technical books in PDF form. It converts a PDF
into structured, heading-aware chunks with Docling, indexes them into Qdrant with hybrid dense +
sparse vectors, and answers questions with Claude over the retrieved context.

## How it works

```
animal ──POST /documents {object_name}──▶ API ──▶ Redis queue ──▶ arq worker
                                                                     │
           MinIO (private bucket) ──download──────────────────────────┤
                                                                     ▼
       Docling parse (+ auto OCR) ──▶ HybridChunker (Voyage tokenizer, headings in text)
                                                                     │
                                                                     ▼
       groups per chapter ──▶ Voyage contextualized embeddings (batched to API limits)
                                                                     │
                                                                     ▼
       Qdrant: dense (int8 quantized) + server-side BM25 ──▶ callback to animal (ready / failed)

question ──▶ Voyage query embedding ──▶ Qdrant hybrid search (dense + BM25, RRF)
                                                 │
                                                 ▼
                         Voyage rerank ──▶ (+ neighbour chunks) ──▶ Claude ──▶ answer + sources
```

1. **Parsing & chunking** (`src/ingestion/chunking.py`) — `DocumentChunker.load_and_chunk(data: bytes, filename)` runs
   Docling's `DocumentConverter` on an in-memory `DocumentStream` (no temp files). Heading hierarchy is
   recovered from PDF bookmarks/numbering/fonts. If a PDF has almost no text layer it is re-parsed with
   OCR. A `PARTIAL_SUCCESS` (e.g. Docling timeout) is treated as a failure, never as a half-indexed book.
   `HybridChunker` counts tokens with the Voyage tokenizer; page furniture is dropped. Each chunk has
   `text` (shown to users) and `embed_text` (heading trail + text, used for embeddings, BM25 and rerank).
2. **Grouping** (`src/ingestion/grouping.py`) — chunks are grouped by chapter (bounded by
   `GROUP_MIN_TOKENS`/`GROUP_MAX_TOKENS`) because Voyage contextualized embeddings make each vector aware
   of its group; groups are batched to stay under Voyage request limits (1000 inputs, 16K chunks, 120K tokens).
3. **Storage** (`src/db/vector_store.py`) — Qdrant `dense` vector (originals on disk, int8 scalar
   quantization pinned in RAM, rescoring on search) and a `bm25` sparse vector computed by the Qdrant
   server. Payload indexes: `chat_session_id` (tenant), `document_id`, `index_run_id`, `chunk_index`.
4. **Versioning** (`src/services/indexing.py`, `src/services/runs.py`) — every indexing run has a
   `run_id`; point IDs are `uuid5(document_id, run_id, chunk_index)`. New points are written first, then
   older runs are deleted, so search keeps serving the old version until the new one is complete. A
   Redis key per document records the current run, which makes re-uploads and deletes during indexing safe.
5. **Answering** (`src/services/rag_service.py`) — candidates are reranked on `embed_text`; for `ask`,
   neighbouring chunks (`chunk_index ± 1`) are added to the context sent to Claude.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker (Qdrant and Redis)
- API keys for [Anthropic](https://console.anthropic.com/) and [Voyage AI](https://voyageai.com/)
- For the HTTP service: the `animal` MinIO with the read-only `book-rag` user (created by `minio-init`
  in `animal/docker/docker-compose.yml`)

## Setup

```bash
uv sync
docker compose up -d          # Qdrant (6333/6334) + Redis for the job queue (6380)
cp .env.example .env          # then fill in your keys
```

The first run downloads Docling layout/table models, the Voyage tokenizer from Hugging Face and (only
when a scan is detected) OCR models. For offline deploys pre-download them
(`uv run docling-tools models download`, warm the `HF_HOME` cache).

### Environment variables

Read by `pydantic-settings` (`src/settings.py`) from the environment / `.env` and validated at start-up.

| Variable | Description | Default |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_MAX_TOKEN` | Answer generation | required |
| `VOYAGE_API_KEY` | Voyage AI API key | required |
| `VOYAGE_MODEL` | Contextualized embedding model | `voyage-context-4` |
| `VOYAGE_RERANK_MODEL` | Reranking model | `rerank-2.5` |
| `VOYAGE_TOKENIZER` | HF tokenizer used for chunk sizes | `voyageai/voyage-context-4` |
| `QDRANT_URL` | Qdrant endpoint | required |
| `QDRANT_COLLECTION` | Collection name | `books_v2` |
| `BM25_LANGUAGE` | Stemming language for server-side BM25 | `english` |
| `REDIS_URL` | arq queue + run registry | `redis://localhost:6380/0` |
| `INTERNAL_SERVICE_TOKEN` | Shared secret with `animal` (API + worker only) | — |
| `ANIMAL_CALLBACK_URL` | `POST {url}/documents/{id}/status` (worker only) | — |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | Read-only access to chat documents | `localhost:9000` / — / — |
| `MINIO_REGION` | Must be set: the read-only user cannot call `GetBucketLocation` | `us-east-1` |
| `MINIO_DOCUMENTS_BUCKET` / `MINIO_SECURE` | Private documents bucket | `chat-documents` / `false` |
| `MAX_UPLOAD_SIZE_BYTES` / `MAX_PDF_PAGES` | Input limits | `15728640` / `2000` |
| `CHUNK_MAX_TOKENS` | Chunk size (one value per collection) | `512` |
| `JOB_TIMEOUT_SECONDS` / `JOB_MAX_TRIES` | Worker limits | `1800` / `3` |

## HTTP service (used by the `animal` backend)

Two processes:

```bash
uv run uvicorn src.main:app --reload --port 8001   # API
uv run arq src.worker.WorkerSettings               # indexing worker (one job at a time; scale with more workers)
```

Every route except `/health` requires the `X-Internal-Token` header.

| Endpoint | Purpose |
| --- | --- |
| `POST /documents` | JSON `{chat_session_id, document_id, filename, object_name, reindex?}` → `202`; checks the object exists in MinIO (`404`) and its size (`413`), queues the job (`503` when the queue is full). Repeating the same request does not queue a second job; `reindex: true` forces a new run |
| `DELETE /documents/{document_id}` | Marks the document deleted (a running job cleans up after itself) and removes its points |
| `POST /search` | Hybrid search + rerank scoped to one `chat_session_id` |
| `GET /health` | Redis and Qdrant reachability, no auth |

The worker reports `ready` or `failed` (with a user-readable reason: corrupted / password-protected /
too many pages / no text / parse failure / service unavailable) to `animal`. Transient errors (network,
Voyage rate limits, Qdrant) are retried by arq up to `JOB_MAX_TRIES`.

## CLI usage

```bash
uv run python -m src.console_interface index-pdf path/to/book.pdf --book-title "FastAPI Book"
uv run python -m src.console_interface search "how do I add dependencies to a route?" --top-k 10
uv run python -m src.console_interface ask "What is a FastAPI dependency?" --top-k 5   # alias: get_answer
```

The CLI indexes directly (no queue, no MinIO) with `document_id = cli:<sha256 prefix>`, so re-indexing
the same file replaces the previous version. CLI chunks have no `chat_session_id`; CLI `search`/`ask`
are not tenant-scoped, so keep CLI experiments in a separate `QDRANT_COLLECTION`.

## Project structure

```
src/
├── main.py                  # FastAPI app: builds the Container in lifespan, closes it on shutdown
├── worker/                  # arq worker (`uv run arq src.worker.WorkerSettings`)
│   ├── config.py            # WorkerSettings
│   ├── lifecycle.py         # startup / shutdown: build and close the Container, warm up Docling
│   ├── tasks.py             # index_document_job — the function registered in arq
│   ├── jobs.py              # IndexDocumentJob: run indexing, map errors to callbacks / retries
│   └── errors.py            # TRANSIENT_ERRORS that are retried
├── container.py             # Container: builds every client/service lazily from Settings, closes them
├── exceptions.py            # domain errors (parse, missing/too large object, superseded run, queue full)
├── documents_router.py      # /documents, /search — maps domain errors to HTTP codes
├── dependencies.py          # X-Internal-Token check, service dependencies from the Container
├── schemas.py               # request/response models
├── console_interface.py     # CLI (cyclopts), uses its own Container
├── settings.py              # pydantic-settings
├── prompts/                 # LLM prompts as text files ($placeholders), loaded by load_prompt()
│   └── answer.md            # answer generation prompt used by `ask`
├── ingestion/
│   ├── chunking.py          # DocumentChunker: bytes → chunks (Docling, auto OCR, PDF pre-check)
│   └── grouping.py          # ChunkGrouper: chapter groups + Voyage request batches
├── services/
│   ├── document_service.py  # DocumentService: validate + enqueue, delete
│   ├── indexing.py          # IndexingService: parse → embed → upsert → drop older runs
│   ├── runs.py              # RunRegistry: current run per document (Redis)
│   └── rag_service.py       # RagService: search / ask
├── clients/
│   ├── claude_client.py     # ClaudeClient: answer generation
│   ├── voyage_client.py     # VoyageClient: embeddings and reranking
│   ├── storage_client.py    # StorageClient: MinIO read-only download
│   └── callback_client.py   # CallbackClient: status callback to animal (retries 5xx/network only)
└── db/
    └── vector_store.py      # VectorStore: Qdrant collection, quantization, hybrid search, deletes
```
