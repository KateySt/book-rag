import secrets

from fastapi import Header, HTTPException, Request, status

from src.container import Container
from src.services.document_service import DocumentService
from src.services.rag_service import RagService


def get_container(request: Request) -> Container:
    return request.app.state.container


async def verify_internal_token(request: Request, x_internal_token: str = Header(...)) -> None:
    expected = get_container(request).settings.internal_service_token.get_secret_value().encode()
    if not secrets.compare_digest(x_internal_token.encode(), expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


def get_document_service(request: Request) -> DocumentService:
    return get_container(request).documents


def get_rag_service(request: Request) -> RagService:
    return get_container(request).rag
