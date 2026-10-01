from fastapi import File, Form, Header, HTTPException, UploadFile, status

from src.settings import INTERNAL_SERVICE_TOKEN, MAX_UPLOAD_SIZE_BYTES


async def verify_internal_token(x_internal_token: str = Header(...)) -> None:
    if x_internal_token != INTERNAL_SERVICE_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


async def validate_pdf_upload(filename: str = Form(...), file: UploadFile = File(...)) -> bytes:
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only PDF files are supported")

    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="file too large")

    return data
