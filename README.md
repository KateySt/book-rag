# Books RAG

A retrieval-augmented generation (RAG) pipeline for technical books in PDF form. It converts a PDF
into structured, heading-aware chunks with Docling, indexes them into Qdrant with hybrid dense +
sparse vectors, and answers questions with Claude over the retrieved context.

## How it works

```
animal ──POST /documents {object_name}──▶ API ──▶ Vercel Queues ──▶ jobs relay ──▶ POST /internal/index
                                                                     │
      Vercel Blob (private store) ──download──────────────────────────┤
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
- For the HTTP service: the token of `animal`'s private Vercel Blob store with chat PDFs
  (`BLOB_DOCUMENTS_READ_WRITE_TOKEN`, same value as in `animal/.env`)

## Setup

```bash
uv sync
docker compose up -d          # Qdrant (6333/6334) + Redis for the run registry (6380)
cp .env.example .env          # then fill in your keys
```

The first run downloads Docling layout/table models, the Voyage tokenizer from Hugging Face and (only
when a scan is detected) OCR models. The Docker image (`Dockerfile.vercel`) bakes all of them in at build
time with `python -m src.ingestion.prefetch` and runs with `HF_HUB_OFFLINE=1`.

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
| `QDRANT_API_KEY` | Qdrant Cloud API key (empty for local Qdrant) | — |
| `QDRANT_COLLECTION` | Collection name | `books_v2` |
| `BM25_LANGUAGE` | Stemming language for server-side BM25 | `english` |
| `REDIS_URL` | Run registry (current run per document) | `redis://localhost:6380/0` |
| `INDEX_QUEUE_TOPIC` | Vercel Queues topic for indexing jobs | `book-rag-index` |
| `QUEUE_REGION` | Vercel Queues region the api publishes to; must match `regions` in `vercel.json` | `fra1` |
| `INTERNAL_SERVICE_TOKEN` | Shared secret with `animal` and the `jobs` relay | — |
| `ANIMAL_CALLBACK_URL` | `POST {url}/documents/{id}/status`, must be reachable from Vercel | — |
| `BLOB_DOCUMENTS_READ_WRITE_TOKEN` | Private Vercel Blob store with chat documents (same as in `animal/.env`); `object_name` is the blob pathname | — |
| `MAX_UPLOAD_SIZE_BYTES` / `MAX_PDF_PAGES` | Input limits | `15728640` / `2000` |
| `CHUNK_MAX_TOKENS` | Chunk size (one value per collection) | `512` |
| `DOCLING_DOCUMENT_TIMEOUT` | Docling parse budget per document, seconds | `900` (`.env.example`: `200`) |
| `JOB_MAX_TRIES` | Attempts for transient errors before `failed` | `3` |
| `INDEX_TIMEOUT_SECONDS` | Whole indexing run budget; past it the document is `failed` | `230` |
| `INDEX_LOCK_TIMEOUT_SECONDS` | How long `/internal/index` waits for the run already in progress, then `503` + `Retry-After` | `5` |
| `VERCEL_REGION` / `VERCEL_QUEUE_TOKEN` / `VERCEL_QUEUE_BASE_URL` | Local queue devserver and `jobs/poll.py` only (`fra1` / `vc-dev-token` / printed `baseUrl`); Vercel sets them in the cloud | — |

## HTTP service (used by the `animal` backend)

Locally three processes (plus `docker compose up -d`):

```bash
uv run python -m vercel.queue.devserver            # local Vercel Queues; put the printed baseUrl in VERCEL_QUEUE_BASE_URL
uv run --env-file .env uvicorn src.main:app --reload --port 8001   # API, also runs indexing in POST /internal/index
cd jobs && BOOK_RAG_API_URL=http://localhost:8001 uv run --project .. --env-file ../.env python poll.py   # relay
```

On Vercel there is no worker process: Vercel Queues pushes each message to the `jobs` service, which calls
`POST /internal/index` on the `api` container over a service binding (see "Deploy to Vercel").

Every route except `/health` requires the `X-Internal-Token` header.

| Endpoint | Purpose |
| --- | --- |
| `POST /documents` | JSON `{chat_session_id, document_id, filename, object_name, reindex?}` → `202`; checks the object exists in Vercel Blob (`404`) and its size (`413`), publishes the job to Vercel Queues (`503` when the queue is unavailable). Repeating the same request does not queue a second job; `reindex: true` forces a new run |
| `POST /documents/delete` | JSON `{document_ids: [...]}` (1–1000) — batch delete used by `animal` when a chat, document or user is deleted; marks each document deleted and removes its points in one Qdrant call |
| `DELETE /documents/{document_id}` | Marks the document deleted (a running job cleans up after itself) and removes its points |
| `POST /search` | Hybrid search + rerank scoped to one `chat_session_id` |
| `POST /internal/index` | Called only by the `jobs` relay: one indexing run per queue delivery; `204`, or `503` + `Retry-After` on transient errors |
| `GET /health` | Redis and Qdrant reachability, no auth |

Indexing reports `ready` or `failed` (with a user-readable reason: corrupted / password-protected /
too many pages / no text / parse failure / service unavailable) to `animal`. Transient errors (network,
Voyage rate limits, Qdrant) return `503`; the relay re-queues the message with that delay, up to
`JOB_MAX_TRIES` attempts (the queue itself stops after 5 deliveries). Delivery is at-least-once, so one
`run_id` may be indexed twice; that is safe because point ids are derived from `run_id`.

## Deploy to Vercel

One Vercel project with root `book-rag/` and two services (`vercel.json`):

- `api` — `Dockerfile.vercel` (Container Images): FastAPI with every route above, public via the rewrite.
- `jobs` — `jobs/consumer.py`, a Vercel Queues push subscriber (consumer group `book-rag-index-relay`,
  `"entrypoint": "pyproject.toml"` in `vercel.json`; `[[tool.vercel.subscribers]]` in
  `jobs/pyproject.toml`); it reaches `api` through the `BOOK_RAG_API_URL` binding and is not public.

Functions run in `fra1`; keep Qdrant Cloud, Upstash Redis and the Blob store in Frankfurt too.
Hobby limits shape the settings: 2 GB RAM / 1 vCPU and 300 s per request, so indexing must finish well
under 300 s (the relay gives up at 280 s and the message is retried). Measured with 1 vCPU / 2 GB: a 1-page
PDF takes about 19 s including model loading (1.1 GB peak), 20 pages take about 200–230 s and reach 1.9–2.2 GB,
so `MAX_PDF_PAGES=5`. One indexing run at a time per container (lock + `max_concurrency=1` on the subscriber; a second request
waits at most `INDEX_LOCK_TIMEOUT_SECONDS`, then gets `503` and the relay retries it later);
past `INDEX_TIMEOUT_SECONDS` the document is reported `failed` ("document is too long to process").

Environment variables in the Vercel project:

| Service | Variables |
| --- | --- |
| `api` | everything from `.env.example` except the local queue block; `QDRANT_URL` + `QDRANT_API_KEY` from Qdrant Cloud, `REDIS_URL=rediss://…` from Upstash, `MAX_PDF_PAGES=5`, `DOCLING_DOCUMENT_TIMEOUT=100`, `INDEX_TIMEOUT_SECONDS=230` |
| `jobs` | `INTERNAL_SERVICE_TOKEN` |

In `animal`: `BOOK_RAG_BASE_URL=https://<project>.vercel.app`, `BOOK_RAG_REQUEST_TIMEOUT_SECONDS=60`
(the first request after idle starts the container). `ANIMAL_CALLBACK_URL` in book-rag must point at
animal's public URL + `/api/v1/internal`. Hobby is for non-commercial use only.

Timeouts must nest: `INDEX_LOCK_TIMEOUT_SECONDS` (5) + `INDEX_TIMEOUT_SECONDS` (230) + status callback retries
(≤ 40 s) < relay HTTP timeout (280 s, `jobs/consumer.py`) < function `maxDuration` (300 s, the Hobby default and maximum). Change them together.

Queue messages are pinned to the deployment that sent them: promote or rollback does not stop an old
deployment from retrying its own messages until they are acked or expire. Remove stale deployments
(`vercel remove <deployment-url>`) to stop them.

## CLI usage

```bash
uv run python -m src.console_interface index-pdf path/to/book.pdf --book-title "FastAPI Book"
uv run python -m src.console_interface search "how do I add dependencies to a route?" --top-k 10
uv run python -m src.console_interface ask "What is a FastAPI dependency?" --top-k 5   # alias: get_answer
```

The CLI indexes directly (no queue, no Vercel Blob) with `document_id = cli:<sha256 prefix>`, so re-indexing
the same file replaces the previous version. CLI chunks have no `chat_session_id`; CLI `search`/`ask`
are not tenant-scoped, so keep CLI experiments in a separate `QDRANT_COLLECTION`.

## Project structure

```
src/
├── main.py                  # FastAPI app: builds the Container in lifespan, closes it on shutdown
├── container.py             # Container: builds every client/service lazily from Settings, closes them
├── exceptions.py            # domain errors (parse, missing/too large object, superseded run, queue unavailable, transient)
├── documents_router.py      # /documents, /search — maps domain errors to HTTP codes
├── internal_router.py       # /internal/index — one indexing run per queue delivery
├── dependencies.py          # X-Internal-Token check, service dependencies from the Container
├── schemas.py               # request/response models
├── console_interface.py     # CLI (cyclopts), uses its own Container
├── settings.py              # pydantic-settings
├── prompts/                 # LLM prompts as text files ($placeholders), loaded by load_prompt()
│   └── answer.md            # answer generation prompt used by `ask`
├── ingestion/
│   ├── chunking.py          # DocumentChunker: bytes → chunks (Docling, auto OCR, PDF pre-check)
│   ├── prefetch.py          # build-time model download for the Docker image
│   └── grouping.py          # ChunkGrouper: chapter groups + Voyage request batches
├── services/
│   ├── document_service.py  # DocumentService: validate, claim run, publish to the queue; delete
│   ├── index_job.py         # IndexJob: download → index → callback; transient errors → retry
│   ├── indexing.py          # IndexingService: parse → embed → upsert → drop older runs
│   ├── runs.py              # RunRegistry: current run per document (Redis)
│   └── rag_service.py       # RagService: search / ask
├── clients/
│   ├── claude_client.py     # ClaudeClient: answer generation
│   ├── index_queue.py       # IndexQueue: publish indexing jobs to Vercel Queues
│   ├── voyage_client.py     # VoyageClient: embeddings and reranking
│   ├── storage_client.py    # StorageClient: Vercel Blob (private store) download
│   └── callback_client.py   # CallbackClient: status callback to animal (retries 5xx/network only)
└── db/
    └── vector_store.py      # VectorStore: Qdrant collection, quantization, hybrid search, deletes
jobs/                        # separate Vercel service: queue subscriber relay (+ poll.py for local dev)
Dockerfile.vercel            # api container image (CPU torch, models baked in)
vercel.json                  # services api + jobs, binding, region
```
