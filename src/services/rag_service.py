import tempfile
from contextlib import contextmanager
from pathlib import Path

import httpx

from src.clients.callback_client import notify_document_status
from src.clients.claude_client import generate_answer
from src.db.vector_store import ensure_collection, upsert_documents, search_hybrid, delete_by_document
from src.clients.voyage_client import embed_documents, embed_query, rerank
from src.langchain_pipeline import load_and_chunk


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


async def remove_document(document_id: str) -> None:
    await delete_by_document(document_id)


async def search(query: str, top_k: int = 10, candidates: int = 50, chat_session_id: str | None = None) -> list[dict]:
    query_vector = await embed_query(query)
    results = await search_hybrid(
        query_text=query,
        query_vector=query_vector,
        top_k=candidates,
        prefetch_limit=candidates,
        chat_session_id=chat_session_id,
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


@contextmanager
def _temp_pdf(data: bytes):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        tmp_file.write(data)
        tmp_path = Path(tmp_file.name)
    try:
        yield tmp_path
    finally:
        tmp_path.unlink(missing_ok=True)


def _build_payloads(chunks: list[dict], *, chat_session_id: str, document_id: str, filename: str) -> list[dict]:
    return [
        {
            "title": filename,
            "chat_session_id": chat_session_id,
            "document_id": document_id,
            "filename": filename,
            **chunk,
        }
        for chunk in chunks
    ]


async def embed_document_file(
        client: httpx.AsyncClient, data: bytes, chat_session_id: str, document_id: str, filename: str
) -> None:
    try:
        with _temp_pdf(data) as tmp_path:
            payloads = _build_payloads(
                load_and_chunk(tmp_path),
                chat_session_id=chat_session_id,
                document_id=document_id,
                filename=filename,
            )
        await add_texts(payloads, group_key="doc_group")
        await notify_document_status(client, document_id, "ready")
    except Exception:
        await notify_document_status(client, document_id, "failed", error="embedding failed")
