from cyclopts import App
from pathlib import Path

from src.chunking import chunk_blocks
from src.parsing import parse_pdf, load_blocks
from src.services.rag_service import add_texts, ask, search

app = App()


@app.command(name="index-pdf")
async def index_pdf_command(
        file: Path,
        book_title: str | None = None,
        target_tokens: int = 512,
        backend: str = "pipeline",
        lang: str = "en",
):
    blocks = load_blocks(parse_pdf(file, backend=backend, lang=lang))
    chunks = chunk_blocks(blocks, target_tokens=target_tokens)
    payloads = [{"title": book_title or file.stem, **chunk} for chunk in chunks]
    ids = await add_texts(payloads)
    print(f"Added {len(ids)} chunks from {file}")


@app.command(name="search")
async def search_command(query: str, top_k: int = 10):
    results = await search(query, top_k=top_k)
    for result in results:
        print(f"{result['rank']}. {result.get('title', '')} (score={result['score']:.4f})")


@app.command(name="ask", alias="get_answer")
async def ask_command(question: str, top_k: int = 5):
    answer, results = await ask(question, top_k=top_k)
    print(f"Answer: {answer}\n")
    print("Sources:")
    for result in results:
        print(f"  - {result.get('title', '')} (score={result['score']:.4f})")


if __name__ == "__main__":
    app()
