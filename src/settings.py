from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_SETTINGS = (
    "internal_service_token",
    "animal_callback_url",
    "minio_access_key",
    "minio_secret_key",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr
    anthropic_model: str
    anthropic_max_token: int

    voyage_api_key: SecretStr
    voyage_model: str = "voyage-context-4"
    voyage_rerank_model: str = "rerank-2.5"
    voyage_tokenizer: str = "voyageai/voyage-context-4"

    qdrant_url: str
    qdrant_collection: str = "books_v2"
    bm25_language: str = "english"

    redis_url: str = "redis://localhost:6380/0"

    internal_service_token: SecretStr | None = None
    animal_callback_url: str | None = None

    minio_endpoint: str = "localhost:9000"
    minio_region: str = "us-east-1"
    minio_access_key: SecretStr | None = None
    minio_secret_key: SecretStr | None = None
    minio_documents_bucket: str = "chat-documents"
    minio_secure: bool = False

    max_upload_size_bytes: int = 15 * 1024 * 1024
    max_pdf_pages: int = 2000
    max_queued_jobs: int = 200

    chunk_max_tokens: int = 512
    group_min_tokens: int = 4_000
    group_max_tokens: int = 24_000
    batch_max_tokens: int = 100_000

    docling_document_timeout: float = 900
    ocr_min_chars_per_page: int = 100

    job_timeout_seconds: int = 1800
    job_max_tries: int = 3

    def require_service_settings(self) -> None:
        missing = [name.upper() for name in SERVICE_SETTINGS if getattr(self, name) is None]
        if missing:
            raise RuntimeError(f"missing required settings: {', '.join(missing)}")


settings = Settings()
