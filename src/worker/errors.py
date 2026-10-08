import httpx
import urllib3.exceptions
import voyageai.error
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

TRANSIENT_ERRORS = (
    httpx.HTTPError,
    urllib3.exceptions.HTTPError,
    ConnectionError,
    TimeoutError,
    voyageai.error.APIConnectionError,
    voyageai.error.RateLimitError,
    voyageai.error.ServerError,
    voyageai.error.ServiceUnavailableError,
    ResponseHandlingException,
    UnexpectedResponse,
)
