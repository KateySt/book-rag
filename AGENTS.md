# Books RAG — AGENTS.md

RAG pipeline over technical books in PDF form: parse & chunk with Docling, embed with Voyage
contextualized embeddings, index/search in Qdrant (hybrid dense + BM25), answer with Claude.
Standalone project (own git remote), not part of the sibling `animal`/`animal-front` apps even
though it lives inside this folder.

## Stack
Python 3.11+ · uv · cyclopts (CLI) · Docling + langchain-docling (PDF parsing/chunking) ·
Voyage AI (`voyageai`, contextualized embeddings + rerank) · Qdrant (`qdrant-client`, hybrid
dense + BM25 via `fastembed`) · Anthropic SDK (`anthropic`, answer generation) · fully async

## Layout
```
src/
├── main.py                   # FastAPI app — used by the animal backend as a multi-tenant RAG service
├── documents_router.py       # POST /documents (upload+embed, background), DELETE /documents/{id}, POST /search
├── dependencies.py           # verify_internal_token — all routes except /health require X-Internal-Token
├── schemas.py                 # request/response pydantic models
├── console_interface.py     # CLI entry point (cyclopts): index-pdf, search, ask/get_answer
├── settings.py               # env config — read once at import, fails fast (KeyError) if missing
├── langchain_pipeline.py     # PDF → chunks (DoclingLoader + HybridChunker)
├── services/
│   └── rag_service.py        # orchestration: add_texts / search / ask / remove_document
├── clients/
│   ├── claude_client.py      # Anthropic answer generation
│   ├── voyage_client.py      # embeddings + reranking
│   └── callback_client.py    # tenacity-retried POST back to animal's /internal/documents/{id}/status
└── db/
    └── vector_store.py       # Qdrant collection, upsert, hybrid search, delete_by_document
```

## HTTP API (for the `animal` backend)
Not public-facing — only `animal` calls this, authenticated with a shared `X-Internal-Token` header
(`INTERNAL_SERVICE_TOKEN`, same value on both sides). Run with
`uv run uvicorn src.main:app --reload --port 8001`.

- `POST /documents` (multipart: `chat_session_id`, `document_id`, `filename`, `file`) → `202` immediately,
  embeds in a `BackgroundTasks` job, then POSTs the result to `ANIMAL_CALLBACK_URL/documents/{document_id}/status`.
  PDF-only, rejects anything over `MAX_UPLOAD_SIZE_BYTES`.
- `DELETE /documents/{document_id}` → removes all Qdrant points for that document (filter on `document_id`
  payload field — see `vector_store.delete_by_document`).
- `POST /search` (`{chat_session_id, query, top_k}`) → hybrid search filtered to that `chat_session_id` only
  (Qdrant payload filter on both the dense and BM25 prefetch legs).
- `GET /health` — unauthenticated.

Every chunk payload now carries `chat_session_id`, `document_id`, `filename` in addition to the existing
`section_path`/`chapter`/`page_*`/`doc_group` fields — this is what makes search multi-tenant. The CLI path
(`console_interface.py`) does not set these and is effectively single-tenant/global; don't mix CLI-indexed
and API-indexed data in the same collection if you care about isolation.

## Pipeline (the part that spans files)
```
PDF ──▶ Docling parse + HybridChunker ──▶ Voyage contextual embeddings
                                                    │
                                                    ▼
question ──▶ Voyage query embedding ──▶ Qdrant hybrid search (dense + BM25, RRF)
                                                 │
                                                 ▼
                                      Voyage rerank ──▶ Claude ──▶ answer + sources
```

- `langchain_pipeline.load_and_chunk` drops page furniture (`page_header`/`page_footer`/`footnote`),
  and tags each chunk with `section_path` (heading trail), `chapter` (top heading), `page_start`/
  `page_end`, `chunk_index`, coarse `type` (`code`/`table`/`text`), and `doc_group`
  (`"{file.stem}-{chunk_index // 64}"`).
- `rag_service.add_texts` groups payloads by `group_key` (CLI passes `"doc_group"`) **before**
  embedding — Voyage's contextualized embeddings are computed per group, so each vector is aware of
  its neighbours in the same group. Changing how chunks are grouped changes embedding quality
  silently; don't group across unrelated groups.
- `vector_store.ensure_collection` infers `vector_size` from the first embedding result and creates
  the Qdrant collection lazily on first index (`dense` cosine vector + `bm25` sparse/IDF vector).
  There is no migration path — the schema is fixed at creation time.
- Point IDs are random `uuid4`s and upserts never dedupe. Re-running `index-pdf` on the same file
  **appends duplicates**; drop the Qdrant collection first for a clean re-index.
- `VOYAGE_RERANK_MODEL` is the only optional setting — everything else in `settings.py` is
  `os.environ[...]` and raises `KeyError` at import time if unset.

## Commands
No test suite, linter, or formatter is configured in this repo (no pytest/ruff/mypy config, no
`tests/` directory) — don't assume `make test`/`make lint` exist.

```bash
uv sync                         # install deps
docker compose up -d            # start local Qdrant (localhost:6333 / gRPC 6334)
cp .env.example .env            # then fill in ANTHROPIC_API_KEY / VOYAGE_API_KEY

uv run python -m src.console_interface index-pdf <path.pdf> --book-title "..." --target-tokens 512
uv run python -m src.console_interface search "<query>" --top-k 10
uv run python -m src.console_interface ask "<question>" --top-k 5   # alias: get_answer
```

## Environment
Required (fail fast on import if missing): `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`,
`ANTHROPIC_MAX_TOKEN`, `VOYAGE_API_KEY`, `VOYAGE_MODEL`, `QDRANT_URL`, `QDRANT_COLLECTION`,
`INTERNAL_SERVICE_TOKEN`, `ANIMAL_CALLBACK_URL`.
Optional: `VOYAGE_RERANK_MODEL`, `MAX_UPLOAD_SIZE_BYTES` (default 15 MiB). See `.env.example`.

## Caveats / dependency drift
- `mineru` is declared in `pyproject.toml` but unused anywhere in `src/` — leftover from an earlier
  MinerU-based parsing pipeline replaced by the Docling/langchain pipeline. `fastapi`/`uvicorn` are
  **now used** (`src/main.py`, `src/documents_router.py`) — no longer dead weight.
- All `httpx.HTTPError`s calling back to `animal` are retried with `tenacity` (5 attempts, exponential
  backoff) in `callback_client.py`; a final failure is logged and swallowed, not raised — a dead
  callback must never crash the background embedding task.
- First run downloads Docling + fastembed models locally (disk space + time); later runs reuse the
  cache.
- `--target-tokens` is enforced by Docling's own tokenizer, not Voyage's — treat it as a guide, not
  an exact budget for the embedding model.
