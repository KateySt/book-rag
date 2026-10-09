from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.dependencies import get_document_service, get_rag_service, verify_internal_token
from src.exceptions import ObjectMissingError, ObjectTooLargeError, QueueUnavailableError, UnsupportedFileError
from src.schemas import DeleteDocumentsRequest, EmbedAcceptedResponse, EmbedRequest, SearchChunk, SearchRequest
from src.services.document_service import DocumentService
from src.services.rag_service import RagService

router = APIRouter(dependencies=[Depends(verify_internal_token)])


@router.post("/documents", response_model=EmbedAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def embed_document(
        payload: EmbedRequest,
        documents: Annotated[DocumentService, Depends(get_document_service)],
) -> EmbedAcceptedResponse:
    try:
        await documents.submit(
            chat_session_id=payload.chat_session_id,
            document_id=payload.document_id,
            filename=payload.filename,
            object_name=payload.object_name,
            reindex=payload.reindex,
        )
    except UnsupportedFileError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="only PDF files are supported")
    except ObjectMissingError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="object not found")
    except ObjectTooLargeError:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file too large")
    except QueueUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="indexing queue is unavailable",
            headers={"Retry-After": "60"},
        )
    return EmbedAcceptedResponse(document_id=payload.document_id, status="embedding")


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, documents: Annotated[DocumentService, Depends(get_document_service)]):
    await documents.delete(document_id)


@router.post("/documents/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_documents(
        payload: DeleteDocumentsRequest,
        documents: Annotated[DocumentService, Depends(get_document_service)],
):
    await documents.delete_many(payload.document_ids)


@router.post("/search", response_model=list[SearchChunk])
async def search_documents(
        payload: SearchRequest,
        rag: Annotated[RagService, Depends(get_rag_service)],
) -> list[SearchChunk]:
    results = await rag.search(payload.query, top_k=payload.top_k, chat_session_id=payload.chat_session_id)
    return [SearchChunk(**result) for result in results]
