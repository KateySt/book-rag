# Books RAG — AGENTS.md

RAG over PDF books: parse & chunk with Docling, embed with Voyage contextualized embeddings, index/search
in Qdrant (hybrid dense + server-side BM25), answer with Claude. Used by `animal` as an internal
multi-tenant service for chat documents; also has a CLI. Full description: `README.md`.

## Stack
Python 3.11+ · uv · FastAPI · Vercel Queues (`vercel.queue`) · Redis (run registry) · Docling + docling-core (HybridChunker) · transformers
(Voyage tokenizer) · pypdfium2 (PDF pre-check) · Voyage AI · Qdrant (`qdrant-client`) · Vercel Blob SDK (`vercel`) ·
Anthropic SDK · pydantic-settings · cyclopts · ruff

## Processes
Deployed to Vercel as one project with two services (`vercel.json`, details in README "Deploy to Vercel"):
- `api` (`Dockerfile.vercel`, Container Images): `uvicorn src.main:app`. `POST /documents` validates and
  publishes to Vercel Queues; `POST /internal/index` downloads from Vercel Blob, parses, embeds, upserts and
  calls back, all inside one request (Hobby: 2 GB RAM, 300 s).
- `jobs` (`jobs/consumer.py`): Vercel Queues push subscriber that relays each message to `/internal/index`
  over the `BOOK_RAG_API_URL` binding (new `httpx.AsyncClient` per delivery). Separate build root: never import
  `src` there. The consumer group is set explicitly (`book-rag-index-relay`); renaming it creates a new group.
- Local: `docker compose up -d` (Qdrant 6333/6334 + own Redis 6380), `uv run python -m vercel.queue.devserver`,
  `uv run --env-file .env uvicorn src.main:app --reload --port 8001` (the queue SDK reads `VERCEL_*` from the process env), `jobs/poll.py` (env in `.env.example`, local queue block).
  Do NOT use animal's Redis: it runs `allkeys-lru` and would evict run keys.

## Contract with `animal`
- `POST /documents` JSON `{chat_session_id, document_id, filename, object_name, reindex}`; the file is read
  from the private Vercel Blob store (`object_name` = pathname, same token as animal), never sent in the request. A repeated
  request is a no-op (the run key is claimed with `SET NX`); `reindex` starts a new run. The queue message
  carries `run_id`; its idempotency key is the `run_id`.
- Deletes: `animal` calls `POST /documents/delete` with every affected `document_id` BEFORE deleting its DB rows
  (chat, document, user). It marks the runs deleted (so an in-flight job won't re-insert points) and is idempotent.
- Indexing calls back `POST {ANIMAL_CALLBACK_URL}/documents/{id}/status`; 404 means the document was deleted
  and is not retried. If every delivery fails without reaching the callback (5 deliveries, or the relay keeps
  timing out), nobody calls back and the document stays `embedding` in `animal`.

## Invariants (the parts that span files)
- Everything is class-based and wired in `container.Container` (lazy `cached_property` per component, built
  from `Settings`; API and CLI each own one Container and call `close()` on shutdown). Classes get
  their config through the constructor — don't read the global `settings` inside clients/services.
- Prompts live in `src/prompts/*.md` (`string.Template`, `$placeholders`), never inline in code; load them with
  `load_prompt(name)` in the Container and pass them into clients through the constructor.
- `DocumentChunker.load_and_chunk` takes `bytes`; sync and CPU-heavy — call only via `anyio.to_thread`.
  Docling converters/tokenizer live on the chunker instance and load lazily on the first `/internal/index`
  (never in lifespan: it would slow every cold `POST /documents`). Models are baked into the image by
  `python -m src.ingestion.prefetch`; the container runs with `HF_HUB_OFFLINE=1`.
- Queue delivery is at-least-once: `/internal/index` must stay idempotent per `run_id` (it is, because point
  ids derive from `run_id`). `IndexJob` runs one document at a time per process (lock, waited for at most
  `INDEX_LOCK_TIMEOUT_SECONDS`, then `TransientIndexError` → 503) within
  `INDEX_TIMEOUT_SECONDS`; Docling threads can't be cancelled, so a timed-out parse is abandoned, not stopped.
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
  `ANIMAL_CALLBACK_URL`, `BLOB_DOCUMENTS_READ_WRITE_TOKEN`) are optional for the CLI and checked by `require_service_settings()`.

## Commands
```bash
uv sync
uv run ruff check src jobs
uv run python -m src.console_interface index-pdf <path.pdf> --book-title "..."
uv run python -m src.console_interface search "<query>" --top-k 10
uv run python -m src.console_interface ask "<question>" --top-k 5
```

## Caveats
- First run downloads Docling models and the HF tokenizer; OCR models only when a scan is detected.
- CLI data has no `chat_session_id` and CLI search is not tenant-scoped — keep it in a separate collection.
- `docs/plans/` holds the design notes for the current pipeline.
