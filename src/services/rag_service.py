from src.clients.claude_client import generate_answer
from src.db.vector_store import ensure_collection, upsert_documents, search_hybrid
from src.clients.voyage_client import embed_documents, embed_query, rerank


async def add_texts(payloads: list[dict], group_key: str = "chapter") -> list[str]:
    groups: dict[str, list[dict]] = {}
    for payload in payloads:
        groups.setdefault(payload.get(group_key, ""), []).append(payload)

    ordered = [payload for group in groups.values() for payload in group]
    documents = [[payload["text"] for payload in group] for group in groups.values()]

    grouped_vectors = await embed_documents(documents)
    dense_vectors = [vector for group in grouped_vectors for vector in group]
    await ensure_collection(vector_size=len(dense_vectors[0]))

    return await upsert_documents(dense_vectors=dense_vectors, payloads=ordered)


async def search(query: str, top_k: int = 10, candidates: int = 50) -> list[dict]:
    query_vector = await embed_query(query)
    results = await search_hybrid(
        query_text=query,
        query_vector=query_vector,
        top_k=candidates,
        prefetch_limit=candidates,
    )
    if not results:
        return results

    ranked = await rerank(query, [result["text"] for result in results], top_k=top_k)
    return [
        {**results[index], "rank": rank, "score": score}
        for rank, (index, score) in enumerate(ranked, start=1)
    ]


async def ask(question: str, top_k: int = 5) -> tuple[str, list[dict]]:
    results = await search(question, top_k=top_k)
    context = "\n\n---\n\n".join(
        f"{result.get('title', '')}\n{result.get('text', '')}" for result in results
    )
    answer = await generate_answer(question, context)
    return answer, results
