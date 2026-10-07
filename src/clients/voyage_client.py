import voyageai


class VoyageClient:
    def __init__(self, *, api_key: str, model: str, rerank_model: str) -> None:
        self._client = voyageai.AsyncClient(api_key=api_key, max_retries=3, timeout=120)
        self._model = model
        self._rerank_model = rerank_model

    async def embed_documents(self, documents: list[list[str]]) -> list[list[list[float]]]:
        result = await self._client.contextualized_embed(
            inputs=documents,
            model=self._model,
            input_type="document",
        )
        return [item.embeddings for item in result.results]

    async def embed_query(self, text: str) -> list[float]:
        result = await self._client.contextualized_embed(
            inputs=[[text]],
            model=self._model,
            input_type="query",
        )
        return result.results[0].embeddings[0]

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        result = await self._client.rerank(
            query=query,
            documents=documents,
            model=self._rerank_model,
            top_k=top_k,
        )
        return [(item.index, item.relevance_score) for item in result.results]
