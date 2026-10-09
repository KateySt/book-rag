from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.dependencies import get_index_job, verify_internal_token
from src.exceptions import TransientIndexError
from src.schemas import IndexJobRequest
from src.services.index_job import IndexJob

RETRY_DELAY_SECONDS = 30
MAX_RETRY_DELAY_SECONDS = 300

router = APIRouter(prefix="/internal", dependencies=[Depends(verify_internal_token)], include_in_schema=False)


@router.post("/index", status_code=status.HTTP_204_NO_CONTENT)
async def index_document(payload: IndexJobRequest, job: Annotated[IndexJob, Depends(get_index_job)]) -> None:
    try:
        await job.run(payload)
    except TransientIndexError:
        delay = min(MAX_RETRY_DELAY_SECONDS, RETRY_DELAY_SECONDS * payload.attempt)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="indexing dependency unavailable, retry later",
            headers={"Retry-After": str(delay)},
        )
