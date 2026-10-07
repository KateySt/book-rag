import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from cyclopts import App

from src.container import Container
from src.settings import settings

app = App()


@asynccontextmanager
async def open_container() -> AsyncIterator[Container]:
    container = Container(settings)
    try:
        yield container
    finally:
        await container.close()


@app.command(name="index-pdf")
async def index_pdf_command(file: Path, book_title: str | None = None):
    data = file.read_bytes()
    document_id = f"cli:{hashlib.sha256(data).hexdigest()[:16]}"
    async with open_container() as container:
        count = await container.indexing.index(
            data,
            filename=book_title or file.name,
            document_id=document_id,
            run_id=uuid.uuid4().hex,
            chat_session_id=None,
        )
    print(f"Added {count} chunks from {file} (document_id={document_id})")


@app.command(name="search")
async def search_command(query: str, top_k: int = 10):
    async with open_container() as container:
        results = await container.rag.search(query, top_k=top_k)
    for result in results:
        location = f"{result.get('title', '')} — {result.get('section_path', '')}"
        print(f"{result['rank']}. {location} (score={result['score']:.4f})")


@app.command(name="ask", alias="get_answer")
async def ask_command(question: str, top_k: int = 5):
    async with open_container() as container:
        answer, results = await container.rag.ask(question, top_k=top_k)
    print(f"Answer: {answer}\n")
    print("Sources:")
    for result in results:
        pages = f"p. {result.get('page_start')}-{result.get('page_end')}"
        print(f"  - {result.get('title', '')}, {pages} (score={result['score']:.4f})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app()
