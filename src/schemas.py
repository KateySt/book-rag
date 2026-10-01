from pydantic import BaseModel


class EmbedAcceptedResponse(BaseModel):
    document_id: str
    status: str


class SearchRequest(BaseModel):
    chat_session_id: str
    query: str
    top_k: int = 5


class SearchChunk(BaseModel):
    document_id: str | None = None
    filename: str | None = None
    title: str | None = None
    chapter: str | None = None
    section_path: str | None = None
    text: str
    page_start: int | None = None
    page_end: int | None = None
    rank: int
    score: float
