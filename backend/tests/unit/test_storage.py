from __future__ import annotations

from pathlib import Path

import pytest
from app.core.settings import Settings
from app.integrations.storage import (
    LocalStorage,
    ObjetoNaoEncontrado,
    S3Storage,
    criar_storage,
)
from botocore.exceptions import ClientError


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

        class _Body:
            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self) -> bytes:
                return self.data

        return {"Body": _Body(self.objects[Key])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop(Key, None)

    def head_object(self, *, Bucket: str, Key: str) -> None:
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")


@pytest.fixture(params=["local", "s3"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> LocalStorage | S3Storage:
    if request.param == "local":
        return LocalStorage(tmp_path)
    return S3Storage(FakeS3Client(), "bucket")


def test_roundtrip_exists_delete(storage: LocalStorage | S3Storage) -> None:
    key = "org/abc/arquivo.pdf"
    assert not storage.exists(key)
    storage.put(key, b"conteudo", "application/pdf")
    assert storage.exists(key)
    assert storage.get(key) == b"conteudo"
    storage.delete(key)
    assert not storage.exists(key)
    storage.delete(key)


def test_get_missing_raises(storage: LocalStorage | S3Storage) -> None:
    with pytest.raises(ObjetoNaoEncontrado):
        storage.get("nao/existe")


def test_local_rejects_path_traversal(tmp_path: Path) -> None:
    local = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        local.put("../fora.txt", b"x", "text/plain")
    with pytest.raises(ValueError):
        local.get("/etc/passwd")


def test_factory_selects_backend(tmp_path: Path) -> None:
    local = criar_storage(Settings(storage_backend="local", storage_local_path=str(tmp_path)))
    assert isinstance(local, LocalStorage)
    s3 = criar_storage(Settings(storage_backend="s3"))
    assert isinstance(s3, S3Storage)
    with pytest.raises(ValueError):
        criar_storage(Settings(storage_backend="ftp"))
