from src.clients.claude_client import ClaudeClient
from src.clients.voyage_client import VoyageClient
from src.db.vector_store import VectorStore


class RagService:
    def __init__(
            self,
            *,
            voyage: VoyageClient,
            store: VectorStore,
            claude: ClaudeClient,
            candidates: int = 50,
    ) -> None:
        self._voyage = voyage
        self._store = store
        self._claude = claude
        self._candidates = candidates

    async def search(self, query: str, *, top_k: int = 10, chat_session_id: str | None = None) -> list[dict]:
        query_vector = await self._voyage.embed_query(query)
        results = await self._store.search_hybrid(
            query,
            query_vector,
            top_k=self._candidates,
            prefetch_limit=self._candidates,
            chat_session_id=chat_session_id,
        )
        if not results:
            return results

        ranked = await self._voyage.rerank(query, [result["embed_text"] for result in results], top_k=top_k)
        return [
            {**results[index], "rank": rank, "score": score}
            for rank, (index, score) in enumerate(ranked, start=1)
        ]

    async def ask(self, question: str, *, top_k: int = 5, chat_session_id: str | None = None) -> tuple[str, list[dict]]:
        results = await self.search(question, top_k=top_k, chat_session_id=chat_session_id)
        context = "\n\n---\n\n".join([await self._with_neighbours(result) for result in results])
        answer = await self._claude.generate_answer(question, context)
        return answer, results

    async def _with_neighbours(self, result: dict) -> str:
        index = result["chunk_index"]
        neighbours = await self._store.fetch_chunks(
            result["document_id"], result["index_run_id"], {index - 1, index + 1}
        )
        by_index = {chunk["chunk_index"]: chunk["text"] for chunk in neighbours}
        by_index[index] = result["text"]
        body = "\n".join(by_index[i] for i in sorted(by_index))
        return f"{result.get('title', '')} — {result.get('section_path', '')}\n{body}"
