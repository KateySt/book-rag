import os
from dotenv import load_dotenv

load_dotenv()

APP_NAME = os.environ.get("APP_NAME")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL")
ANTHROPIC_MAX_TOKEN = int(os.environ.get("ANTHROPIC_MAX_TOKEN"))

VOYAGE_API_KEY= os.environ.get("VOYAGE_API_KEY")
VOYAGE_MODEL = os.environ.get("VOYAGE_MODEL")
VOYAGE_RERANK_MODEL = os.environ.get("VOYAGE_RERANK_MODEL")

QDRANT_URL = os.environ.get("QDRANT_URL")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION")

INTERNAL_SERVICE_TOKEN = os.environ.get("INTERNAL_SERVICE_TOKEN")
ANIMAL_CALLBACK_URL = os.environ.get("ANIMAL_CALLBACK_URL")

MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", 15 * 1024 * 1024))