from __future__ import annotations

import boto3
from app.core.settings import Settings
from app.integrations.storage.base import StorageBackend
from app.integrations.storage.local import LocalStorage
from app.integrations.storage.s3 import S3Storage


def criar_storage(settings: Settings) -> StorageBackend:
    backend = settings.storage_backend.casefold()
    if backend == "local":
        return LocalStorage(settings.storage_local_path)
    if backend == "s3":
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        )
        return S3Storage(client, settings.s3_bucket)
    raise ValueError(f"STORAGE_BACKEND desconhecido: {settings.storage_backend!r}.")
