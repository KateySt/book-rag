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
├── console_interface.py     # CLI entry point (cyclopts): index-pdf, search, ask/get_answer
├── settings.py               # env config — read once at import, fails fast (KeyError) if missing
├── langchain_pipeline.py     # PDF → chunks (DoclingLoader + HybridChunker)
├── services/
│   └── rag_service.py        # orchestration: add_texts / search / ask
├── clients/
│   ├── claude_client.py      # Anthropic answer generation
│   └── voyage_client.py      # embeddings + reranking
└── db/
    └── vector_store.py       # Qdrant collection, upsert, hybrid search
```

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
`ANTHROPIC_MAX_TOKEN`, `VOYAGE_API_KEY`, `VOYAGE_MODEL`, `QDRANT_URL`, `QDRANT_COLLECTION`.
Optional: `VOYAGE_RERANK_MODEL`. See `.env.example`.

## Caveats / dependency drift
- `mineru`, `fastapi`, `uvicorn[standard]` are declared in `pyproject.toml` but unused anywhere in
  `src/` — leftovers from an earlier MinerU-based parsing pipeline that was replaced by the Docling/
  langchain pipeline (see git history: "add mineru" → "rewrite to langchain"). There is no FastAPI
  app in this repo; the only entry point is the cyclopts CLI in `console_interface.py`.
- First run downloads Docling + fastembed models locally (disk space + time); later runs reuse the
  cache.
- `--target-tokens` is enforced by Docling's own tokenizer, not Voyage's — treat it as a guide, not
  an exact budget for the embedding model.
