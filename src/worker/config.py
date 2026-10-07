from arq.connections import RedisSettings

from src.settings import settings
from src.worker.lifecycle import shutdown, startup
from src.worker.tasks import index_document_job


class WorkerSettings:
    functions = [index_document_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 1
    job_timeout = settings.job_timeout_seconds
    max_tries = settings.job_max_tries
    keep_result = 3600
