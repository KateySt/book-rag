import logging

from anyio import to_thread

from src.container import Container
from src.settings import settings
from src.worker.jobs import IndexDocumentJob


async def startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO)
    settings.require_service_settings()
    container = Container(settings, redis=ctx["redis"])
    await to_thread.run_sync(container.chunker.warm_up)
    ctx["container"] = container
    ctx["job"] = IndexDocumentJob(container, max_tries=settings.job_max_tries)


async def shutdown(ctx: dict) -> None:
    if "container" in ctx:
        await ctx["container"].close()
