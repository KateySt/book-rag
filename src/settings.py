import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ANTHROPIC_MODEL = os.environ["ANTHROPIC_MODEL"]
ANTHROPIC_MAX_TOKEN = int(os.environ["ANTHROPIC_MAX_TOKEN"])

VOYAGE_API_KEY= os.environ["VOYAGE_API_KEY"]
VOYAGE_MODEL = os.environ["VOYAGE_MODEL"]

QDRANT_URL = os.environ["QDRANT_URL"]
QDRANT_COLLECTION = os.environ["QDRANT_COLLECTION"]