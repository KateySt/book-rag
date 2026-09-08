# Books RAG

A retrieval-augmented generation (RAG) pipeline for technical books in PDF form. It converts a PDF
into structured, heading-aware chunks with Docling, indexes them into Qdrant with hybrid dense +
sparse vectors, and answers questions with Claude over the retrieved context.

## How it works

```
PDF ──▶ Docling parse + hybrid chunking ──▶ Voyage contextual embeddings
                                                        │
                                                        ▼
question ──▶ Voyage query embedding ──▶ Qdrant hybrid search (dense + BM25, RRF)
                                                     │
                                                     ▼
                                          Voyage rerank ──▶ Claude ──▶ answer + sources
```

1. **Parsing & chunking** (`src/langchain_pipeline.py`) — [`DoclingLoader`](https://github.com/docling-project/docling)
   converts the PDF and emits `HybridChunker` chunks that respect the document's own structure and
   a token budget. Page furniture (headers, footers, footnotes) is dropped. Each chunk carries its
   `section_path` (heading trail), `chapter` (top heading), `page_start`/`page_end`, `chunk_index`,
   a coarse `type` (`code` / `table` / `text`) and a `doc_group` used to batch embeddings.
2. **Embedding** (`src/clients/voyage_client.py`) — Voyage *contextualized* embeddings are used, so
   chunks are embedded as groups and each vector is aware of its neighbours in the same group.
3. **Storage & retrieval** (`src/db/vector_store.py`) — Qdrant holds a `dense` vector and a `bm25`
   sparse vector (via [fastembed](https://github.com/qdrant/fastembed)) per chunk. Search prefetches
   candidates from both and fuses them with Reciprocal Rank Fusion.
4. **Reranking & answering** (`src/services/rag_service.py`) — the fused candidates are reranked by
   Voyage, and the top results are passed to Claude, which is instructed to answer *only* from the
   provided context.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker (for the local Qdrant instance)
- API keys for [Anthropic](https://console.anthropic.com/) and [Voyage AI](https://voyageai.com/)

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Start Qdrant
docker compose up -d

# 3. Configure environment
cp .env.example .env   # then fill in your keys
```

### Environment variables

All variables are required except `VOYAGE_RERANK_MODEL`, and are read once at import time in
`src/settings.py`. A missing key fails fast with a `KeyError`.

| Variable | Description | Example |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `ANTHROPIC_MODEL` | Model used to generate answers | `claude-sonnet-5` |
| `ANTHROPIC_MAX_TOKEN` | Max tokens in the generated answer | `1024` |
| `VOYAGE_API_KEY` | Voyage AI API key | `pa-...` |
| `VOYAGE_MODEL` | Contextualized embedding model | `voyage-context-3` |
| `VOYAGE_RERANK_MODEL` | Reranking model | `rerank-2.5` |
| `QDRANT_URL` | Qdrant endpoint | `http://localhost:6333` |
| `QDRANT_COLLECTION` | Collection name | `books` |

## Usage

The CLI is built with [cyclopts](https://cyclopts.readthedocs.io/) and exposed through
`src/console_interface.py`:

```bash
uv run python -m src.console_interface <command> [OPTIONS]
```

### `index-pdf` — parse, chunk and index a book

```bash
uv run python -m src.console_interface index-pdf src/data/fastapibook.pdf \
    --book-title "FastAPI Book" \
    --target-tokens 512
```

| Option | Default | Description |
| --- | --- | --- |
| `--book-title` | PDF file stem | Stored as `title` on every chunk |
| `--target-tokens` | `512` | `max_tokens` passed to the Docling `HybridChunker` |

The Qdrant collection is created on first index using the embedding dimensionality returned by
Voyage.

### `search` — retrieve chunks without generating an answer

```bash
uv run python -m src.console_interface search "how do I add dependencies to a route?" --top-k 10
```

Retrieves 50 hybrid candidates, reranks them, and prints the top `--top-k`.

### `ask` — full RAG answer with sources

```bash
uv run python -m src.console_interface ask "What is a FastAPI dependency?" --top-k 5
```

Aliased as `get_answer`.

## Project structure

```
src/
├── console_interface.py     # CLI entry point (cyclopts commands)
├── settings.py              # Environment configuration
├── langchain_pipeline.py    # PDF → chunks (Docling loader + hybrid chunker)
├── services/
│   └── rag_service.py       # Index / search / ask orchestration
├── clients/
│   ├── claude_client.py     # Anthropic answer generation
│   └── voyage_client.py     # Embeddings and reranking
└── db/
    └── vector_store.py      # Qdrant collection, upsert, hybrid search
parsed/                      # Leftover parse artifacts from the earlier MinerU pipeline
```

## Notes & caveats

- The first run downloads the Docling and fastembed models, which takes a while and needs disk
  space; later runs reuse the local model cache.
- Chunk sizes are enforced by Docling's tokenizer, not Voyage's, so `--target-tokens` is a guide
  rather than an exact budget for the embedding model.
- Re-indexing the same book appends new points (IDs are random UUIDs) rather than replacing the old
  ones — drop the collection first if you want a clean index.
