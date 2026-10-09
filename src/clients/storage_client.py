from vercel.blob import AsyncBlobClient, BlobNotFoundError

from src.exceptions import ObjectMissingError, ObjectTooLargeError

DOWNLOAD_TIMEOUT_SECONDS = 60


def _private_store_url(token: str) -> str:
    parts = token.split("_")
    if len(parts) < 5 or not parts[3]:
        raise ValueError("Vercel Blob token has unexpected format, expected vercel_blob_rw_<storeId>_<secret>")
    return f"https://{parts[3].lower()}.private.blob.vercel-storage.com/"


class StorageClient:
    def __init__(self, *, token: str, max_object_size: int) -> None:
        self._client = AsyncBlobClient(token=token)
        self._base_url = _private_store_url(token)
        self._max_object_size = max_object_size

    async def object_size(self, object_name: str) -> int:
        try:
            result = await self._client.head(self._base_url + object_name)
        except BlobNotFoundError as error:
            raise ObjectMissingError(object_name) from error
        return result.size

    async def download(self, object_name: str) -> bytes:
        if await self.object_size(object_name) > self._max_object_size:
            raise ObjectTooLargeError(object_name)
        try:
            result = await self._client.get(
                self._base_url + object_name,
                access="private",
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
                use_cache=False,
            )
        except BlobNotFoundError as error:
            raise ObjectMissingError(object_name) from error
        if len(result.content) > self._max_object_size:
            raise ObjectTooLargeError(object_name)
        return result.content

    async def close(self) -> None:
        await self._client.aclose()
