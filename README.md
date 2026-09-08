# Books RAG

A retrieval-augmented generation (RAG) pipeline for technical books in PDF form. It parses a PDF
into structured blocks, chunks them along the book's own section boundaries, indexes them into
Qdrant with hybrid dense + sparse vectors, and answers questions with Claude over the retrieved
context.

## How it works

```
PDF ──▶ MinerU parse ──▶ blocks ──▶ section-aware chunking ──▶ Voyage contextual embeddings
                                                                        │
                                                                        ▼
question ──▶ Voyage query embedding ──▶ Qdrant hybrid search (dense + BM25, RRF)
                                                     │
                                                     ▼
                                          Voyage rerank ──▶ Claude ──▶ answer + sources
```

1. **Parsing** (`src/parsing.py`) — [MinerU](https://github.com/opendatalab/MinerU) converts the PDF
   into a content list. Page furniture (headers, footers, page numbers) and front/back matter
   (contents, index, acknowledgments, …) are dropped; headings are tracked to build a
   `section_path` and `chapter` for every block. Parse output is cached under `parsed/`, so
   re-running a command on the same PDF skips the expensive parse.
2. **Chunking** (`src/chunking.py`) — blocks are packed up to a token budget and flushed whenever
   the section changes, so a chunk never spans two sections. Atomic blocks (code, tables,
   equations) that exceed the budget become chunks of their own instead of being split. Each chunk
   is prefixed with its section path and carries `chapter`, `page_start`/`page_end`, and
   `chunk_index` metadata.
3. **Embedding** (`src/clients/voyage_client.py`) — Voyage *contextualized* embeddings are used, so
   chunks are embedded as groups (by chapter) and each vector is aware of its neighbours.
4. **Storage & retrieval** (`src/db/vector_store.py`) — Qdrant holds a `dense` vector and a `bm25`
   sparse vector per chunk. Search prefetches candidates from both and fuses them with Reciprocal
   Rank Fusion.
5. **Reranking & answering** (`src/services/rag_service.py`) — the fused candidates are reranked by
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

### `list-chapters` — inspect a book before indexing

```bash
uv run python -m src.console_interface list-chapters src/data/fastapibook.pdf
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
| `--target-tokens` | `512` | Token budget per chunk |
| `--backend` | `pipeline` | MinerU backend (`pipeline` or a `vlm*` backend) |
| `--lang` | `en` | OCR language hint |

The Qdrant collection is created on first index using the embedding dimensionality returned by
Voyage.

### `search` — retrieve chunks without generating an answer

```bash
uv run python -m src.console_interface search "how do I add dependencies to a route?" --top-k 10
```

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
├── parsing.py               # PDF → structured blocks (MinerU)
├── chunking.py              # Blocks → section-aware chunks
├── services/
│   └── rag_service.py       # Index / search / ask orchestration
├── clients/
│   ├── claude_client.py     # Anthropic answer generation
│   └── voyage_client.py     # Embeddings, reranking, token counting
└── db/
    └── vector_store.py      # Qdrant collection, upsert, hybrid search
docs/                        # Chunking research notes
parsed/                      # MinerU parse cache (generated)
```

## Notes & caveats

- The first MinerU run downloads its models, which takes a while and needs disk space. Subsequent
  runs on the same PDF reuse the cache in `parsed/`.
- Chunk token counts come from Voyage's tokenizer, so they match what the embedding model actually
  sees.
- Re-indexing the same book appends new points (IDs are random UUIDs) rather than replacing the old
  ones - drop the collection first if you want a clean index.