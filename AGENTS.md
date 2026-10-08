# Books RAG — AGENTS.md

RAG over PDF books: parse & chunk with Docling, embed with Voyage contextualized embeddings, index/search
in Qdrant (hybrid dense + server-side BM25), answer with Claude. Used by `animal` as an internal
multi-tenant service for chat documents; also has a CLI. Full description: `README.md`.

## Stack
Python 3.11+ · uv · FastAPI · arq (Redis job queue) · Docling + docling-core (HybridChunker) · transformers
(Voyage tokenizer) · pypdfium2 (PDF pre-check) · Voyage AI · Qdrant (`qdrant-client`) · MinIO SDK ·
Anthropic SDK · pydantic-settings · cyclopts · ruff

## Processes
- API: `uv run uvicorn src.main:app --reload --port 8001` — validates, queues, never parses PDFs.
- Worker: `uv run arq src.worker.WorkerSettings` — downloads from MinIO, parses, embeds, upserts, calls back.
  `max_jobs = 1` (Docling uses GBs of RAM); scale by running more workers.
- Infra: `docker compose up -d` → Qdrant (6333/6334) + own Redis (6380, `noeviction` + AOF). Do NOT use
  animal's Redis: it runs `allkeys-lru` and would evict queued jobs.

## Contract with `animal`
- `POST /documents` JSON `{chat_session_id, document_id, filename, object_name, reindex}`; the file is read
  from the private MinIO bucket by a read-only user, never sent in the request. Job id is
  `index:{document_id}` (duplicate requests are no-ops) or `index:{document_id}:{run_id}` when `reindex`.
- Deletes: `animal` calls `POST /documents/delete` with every affected `document_id` BEFORE deleting its DB rows
  (chat, document, user). It marks the runs deleted (so an in-flight job won't re-insert points) and is idempotent.
- Worker calls back `POST {ANIMAL_CALLBACK_URL}/documents/{id}/status`; 404 means the document was deleted
  and is not retried. If a job dies on arq timeout or with the worker, nobody calls back and the document
  stays `embedding` in `animal`.

## Invariants (the parts that span files)
- Everything is class-based and wired in `container.Container` (lazy `cached_property` per component, built
  from `Settings`; API, worker and CLI each own one Container and call `close()` on shutdown). Classes get
  their config through the constructor — don't read the global `settings` inside clients/services.
- Prompts live in `src/prompts/*.md` (`string.Template`, `$placeholders`), never inline in code; load them with
  `load_prompt(name)` in the Container and pass them into clients through the constructor.
- `DocumentChunker.load_and_chunk` takes `bytes`; sync and CPU-heavy — call only via `anyio.to_thread`.
  Docling converters/tokenizer live on the chunker instance; `warm_up()` runs at worker start-up.
- Docling `PARTIAL_SUCCESS` (timeout, failed pages) is an error, not a partial index.
- `embed_text` (heading trail + text) is what goes to Voyage, BM25 and rerank; `text` is what users see.
- Chunk size (`CHUNK_MAX_TOKENS`) and the tokenizer must stay constant within a collection.
- Groups (`ChunkGrouper.group_by_chapter`) define Voyage's embedding context; changing grouping silently
  changes embedding quality. Batches must respect Voyage limits (1000 inputs / 16K chunks / 120K tokens).
- Point id = `uuid5(document_id:run_id:chunk_index)`. Indexing writes the new run, re-checks the Redis run
  key (`book-rag:run:{document_id}`; missing key = current, `deleted` / other run = superseded), then deletes
  older runs. On any failure it deletes its own run's points.
- The collection schema (dense size, quantization, sparse BM25) is fixed at creation; payload indexes are
  (re)created idempotently by `VectorStore.ensure_collection`. Changing model/tokenizer/BM25 → new `QDRANT_COLLECTION`
  and re-index every document (`POST /documents` with `reindex: true`).
- `settings.py` validates at import; service-only settings (`INTERNAL_SERVICE_TOKEN`,
  `ANIMAL_CALLBACK_URL`, `MINIO_*` keys) are optional for the CLI and checked by `require_service_settings()`.

## Commands
No test suite yet.

```bash
uv sync
uv run ruff check src
uv run python -m src.console_interface index-pdf <path.pdf> --book-title "..."
uv run python -m src.console_interface search "<query>" --top-k 10
uv run python -m src.console_interface ask "<question>" --top-k 5
```

## Caveats
- First run downloads Docling models and the HF tokenizer; OCR models only when a scan is detected.
- CLI data has no `chat_session_id` and CLI search is not tenant-scoped — keep it in a separate collection.
- `docs/plans/` holds the design notes for the current pipeline.
