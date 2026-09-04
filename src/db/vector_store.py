import uuid

from fastembed import SparseTextEmbedding
from qdrant_client import AsyncQdrantClient, models

from src.settings import QDRANT_URL, QDRANT_COLLECTION

qdrant_client = AsyncQdrantClient(url=QDRANT_URL)
bm25_encoder = SparseTextEmbedding(model_name="Qdrant/bm25")


async def ensure_collection(vector_size: int):
    if await qdrant_client.collection_exists(QDRANT_COLLECTION):
        return
    await qdrant_client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config={
            "dense": models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
        },
    )


async def upsert_documents(
        dense_vectors: list[list[float]],
        payloads: list[dict],
) -> list[str]:
    texts = [payload["text"] for payload in payloads]
    sparse_vectors = list(bm25_encoder.embed(texts))
    ids = [str(uuid.uuid4()) for _ in payloads]
    points = [
        models.PointStruct(
            id=doc_id,
            vector={"dense": dense_vector, "bm25": sparse_vector.as_object()},
            payload=payload,
        )
        for doc_id, dense_vector, sparse_vector, payload in zip(ids, dense_vectors, sparse_vectors, payloads)
    ]
    await qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=points)
    return ids


async def search_hybrid(query_text: str, query_vector: list[float], top_k: int = 10) -> list[dict]:
    sparse_query = next(bm25_encoder.embed([query_text]))
    result = await qdrant_client.query_points(
        collection_name=QDRANT_COLLECTION,
        prefetch=[
            models.Prefetch(query=query_vector, using="dense", limit=50),
            models.Prefetch(query=sparse_query.as_object(), using="bm25", limit=50),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
    )
    return [
        {"rank": i + 1, "doc_id": point.id, "score": point.score, **point.payload}
        for i, point in enumerate(result.points)
    ]
