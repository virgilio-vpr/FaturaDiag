from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.integrations.storage.base import ObjetoNaoEncontrado
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}


class S3Storage:
    def __init__(self, client: S3Client | Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _code(error) in _NOT_FOUND:
                raise ObjetoNaoEncontrado(key) from error
            raise
        body: bytes = response["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _code(error) in _NOT_FOUND:
                return False
            raise
        return True


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))
