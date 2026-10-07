from anyio import to_thread
from minio import Minio
from minio.error import S3Error

from src.exceptions import ObjectMissingError, ObjectTooLargeError

MISSING_CODES = {"NoSuchKey", "NoSuchObject"}


class StorageClient:
    def __init__(
            self,
            *,
            endpoint: str,
            access_key: str,
            secret_key: str,
            bucket: str,
            region: str,
            secure: bool,
            max_object_size: int,
    ) -> None:
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure, region=region)
        self._bucket = bucket
        self._max_object_size = max_object_size

    async def object_size(self, object_name: str) -> int:
        return await to_thread.run_sync(self._stat, object_name)

    async def download(self, object_name: str) -> bytes:
        return await to_thread.run_sync(self._download, object_name)

    def _stat(self, object_name: str) -> int:
        try:
            return self._client.stat_object(self._bucket, object_name).size
        except S3Error as error:
            raise self._translate(error, object_name) from error

    def _download(self, object_name: str) -> bytes:
        limit = self._max_object_size
        if self._stat(object_name) > limit:
            raise ObjectTooLargeError(object_name)
        try:
            response = self._client.get_object(self._bucket, object_name)
        except S3Error as error:
            raise self._translate(error, object_name) from error
        try:
            data = response.read(limit + 1)
        finally:
            response.close()
            response.release_conn()
        if len(data) > limit:
            raise ObjectTooLargeError(object_name)
        return data

    @staticmethod
    def _translate(error: S3Error, object_name: str) -> Exception:
        if error.code in MISSING_CODES:
            return ObjectMissingError(object_name)
        return error
