from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, status

from src.dependencies import validate_pdf_upload, verify_internal_token
from src.schemas import EmbedAcceptedResponse, SearchChunk, SearchRequest
from src.services.rag_service import embed_document_file, remove_document, search

router = APIRouter(dependencies=[Depends(verify_internal_token)])


@router.post("/documents", response_model=EmbedAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def embed_document(
        request: Request,
        background_tasks: BackgroundTasks,
        chat_session_id: str = Form(...),
        document_id: str = Form(...),
        filename: str = Form(...),
        data: bytes = Depends(validate_pdf_upload),
) -> EmbedAcceptedResponse:
    background_tasks.add_task(
        embed_document_file, request.app.state.http_client, data, chat_session_id, document_id, filename
    )
    return EmbedAcceptedResponse(document_id=document_id, status="embedding")


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str):
    await remove_document(document_id)


@router.post("/search", response_model=list[SearchChunk])
async def search_documents(payload: SearchRequest) -> list[SearchChunk]:
    results = await search(payload.query, top_k=payload.top_k, chat_session_id=payload.chat_session_id)
    return [SearchChunk(**result) for result in results]
