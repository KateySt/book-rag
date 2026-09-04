import voyageai

from src.settings import VOYAGE_API_KEY, VOYAGE_MODEL

voyageai_client = voyageai.AsyncClient(api_key=VOYAGE_API_KEY)


async def embed_documents(texts: list[str]) -> list[list[float]]:
    result = await voyageai_client.embed(texts=texts, model=VOYAGE_MODEL, input_type="document")
    return result.embeddings


async def embed_query(text: str) -> list[float]:
    result = await voyageai_client.embed(texts=[text], model=VOYAGE_MODEL, input_type="query")
    return result.embeddings[0]
