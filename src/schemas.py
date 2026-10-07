from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    chat_session_id: str
    document_id: str
    filename: str = Field(max_length=255)
    object_name: str = Field(pattern=r"^chat-documents/\S+$", max_length=512)
    reindex: bool = False


class EmbedAcceptedResponse(BaseModel):
    document_id: str
    status: str


class SearchRequest(BaseModel):
    chat_session_id: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)


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
