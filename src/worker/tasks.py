from src.worker.jobs import IndexDocumentJob


async def index_document_job(ctx: dict, **kwargs) -> None:
    job: IndexDocumentJob = ctx["job"]
    await job.run(job_try=ctx["job_try"], **kwargs)
