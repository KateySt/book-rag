import uuid

from qdrant_client import AsyncQdrantClient, models

POINT_NAMESPACE = uuid.UUID("6f1c2a8e-3b7d-4c55-9a0e-2d4f8b1e7c90")
UPSERT_BATCH = 256


class VectorStore:
    def __init__(self, *, url: str, collection: str, bm25_language: str) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection = collection
        self._bm25_language = bm25_language

    @staticmethod
    def point_id(document_id: str, run_id: str, chunk_index: int) -> str:
        return str(uuid.uuid5(POINT_NAMESPACE, f"{document_id}:{run_id}:{chunk_index}"))

    async def ensure_collection(self, vector_size: int) -> None:
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config={
                    "dense": models.VectorParams(size=vector_size, distance=models.Distance.COSINE, on_disk=True),
                },
                sparse_vectors_config={
                    "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
                },
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        memory=models.Memory.PINNED,
                    ),
                ),
            )
        await self._client.create_payload_index(
            self._collection, "chat_session_id",
            field_schema=models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True),
        )
        for field, schema in (
            ("document_id", models.PayloadSchemaType.KEYWORD),
            ("index_run_id", models.PayloadSchemaType.KEYWORD),
            ("chunk_index", models.PayloadSchemaType.INTEGER),
        ):
            await self._client.create_payload_index(self._collection, field, field_schema=schema)

    async def upsert_chunks(self, dense_vectors: list[list[float]], payloads: list[dict]) -> None:
        points = [
            models.PointStruct(
                id=self.point_id(payload["document_id"], payload["index_run_id"], payload["chunk_index"]),
                vector={"dense": dense_vector, "bm25": self._bm25(payload["embed_text"])},
                payload=payload,
            )
            for dense_vector, payload in zip(dense_vectors, payloads, strict=True)
        ]
        for start in range(0, len(points), UPSERT_BATCH):
            await self._client.upsert(
                collection_name=self._collection,
                points=points[start:start + UPSERT_BATCH],
                wait=True,
            )

    async def search_hybrid(
            self,
            query_text: str,
            query_vector: list[float],
            *,
            top_k: int = 10,
            prefetch_limit: int = 50,
            chat_session_id: str | None = None,
    ) -> list[dict]:
        query_filter = (
            models.Filter(must=[self._match("chat_session_id", chat_session_id)])
            if chat_session_id is not None
            else None
        )
        if not await self._client.collection_exists(self._collection):
            return []
        result = await self._client.query_points(
            collection_name=self._collection,
            prefetch=[
                models.Prefetch(
                    query=query_vector,
                    using="dense",
                    limit=prefetch_limit,
                    filter=query_filter,
                    params=models.SearchParams(
                        quantization=models.QuantizationSearchParams(rescore=True, oversampling=2.0),
                    ),
                ),
                models.Prefetch(query=self._bm25(query_text), using="bm25", limit=prefetch_limit, filter=query_filter),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
        )
        return [
            {"rank": i + 1, "doc_id": point.id, "score": point.score, **point.payload}
            for i, point in enumerate(result.points)
        ]

    async def delete_points(
            self, document_id: str, *, run_id: str | None = None, except_run_id: str | None = None
    ) -> None:
        if not await self._client.collection_exists(self._collection):
            return
        must = [self._match("document_id", document_id)]
        must_not = []
        if run_id is not None:
            must.append(self._match("index_run_id", run_id))
        if except_run_id is not None:
            must_not.append(self._match("index_run_id", except_run_id))
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=must, must_not=must_not)),
            wait=True,
        )

    async def delete_documents(self, document_ids: list[str]) -> None:
        if not await self._client.collection_exists(self._collection):
            return
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="document_id", match=models.MatchAny(any=document_ids)),
            ])),
            wait=True,
        )

    async def fetch_chunks(self, document_id: str, run_id: str, chunk_indexes: set[int]) -> list[dict]:
        if not chunk_indexes:
            return []
        points, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=models.Filter(must=[
                self._match("document_id", document_id),
                self._match("index_run_id", run_id),
                models.FieldCondition(key="chunk_index", match=models.MatchAny(any=sorted(chunk_indexes))),
            ]),
            limit=len(chunk_indexes),
        )
        return [point.payload for point in points]

    async def close(self) -> None:
        await self._client.close()

    def _bm25(self, text: str) -> models.Document:
        return models.Document(text=text, model="Qdrant/bm25", options={"language": self._bm25_language})

    @staticmethod
    def _match(key: str, value) -> models.FieldCondition:
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))
