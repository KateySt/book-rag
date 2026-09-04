from cyclopts import App
from pathlib import Path

from src.services.rag_service import add_texts, ask, search
from src.utils import load_articles

app = App()


@app.command(name="index", alias="add_new_texts")
async def index_command(file: Path, separator: str = "\n\n"):
    articles = load_articles(file, separator=separator)
    payloads = [
        {"title": article.splitlines()[0][:80], "text": article}
        for article in articles
    ]
    ids = await add_texts(payloads)
    print(f"Added {len(ids)} docs from {file}")


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
