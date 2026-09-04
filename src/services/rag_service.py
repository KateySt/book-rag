from src.clients.claude_client import generate_answer
from src.db.vector_store import ensure_collection, upsert_documents, search_hybrid
from src.clients.voyage_client import embed_documents, embed_query


async def add_texts(payloads: list[dict]) -> list[str]:
    texts = [payload["text"] for payload in payloads]

    dense_vectors = await embed_documents(texts)
    await ensure_collection(vector_size=len(dense_vectors[0]))

    return await upsert_documents(dense_vectors=dense_vectors, payloads=payloads)


async def search(query: str, top_k: int = 10) -> list[dict]:
    query_vector = await embed_query(query)
    return await search_hybrid(query_text=query, query_vector=query_vector, top_k=top_k)


async def ask(question: str, top_k: int = 5) -> tuple[str, list[dict]]:
    results = await search(question, top_k=top_k)
    context = "\n\n---\n\n".join(
        f"{result.get('title', '')}\n{result.get('text', '')}" for result in results
    )
    answer = await generate_answer(question, context)
    return answer, results
