import voyageai

from src.settings import VOYAGE_API_KEY, VOYAGE_MODEL, VOYAGE_RERANK_MODEL

voyageai_client = voyageai.AsyncClient(api_key=VOYAGE_API_KEY)


async def embed_documents(documents: list[list[str]]) -> list[list[list[float]]]:
    result = await voyageai_client.contextualized_embed(
        inputs=documents,
        model=VOYAGE_MODEL,
        input_type="document",
    )
    return [item.embeddings for item in result.results]


async def embed_query(text: str) -> list[float]:
    result = await voyageai_client.contextualized_embed(
        inputs=[[text]],
        model=VOYAGE_MODEL,
        input_type="query",
    )
    return result.results[0].embeddings[0]


async def rerank(query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
    result = await voyageai_client.rerank(
        query=query,
        documents=documents,
        model=VOYAGE_RERANK_MODEL,
        top_k=top_k,
    )
    return [(item.index, item.relevance_score) for item in result.results]
