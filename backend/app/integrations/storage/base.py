from __future__ import annotations

from typing import Protocol


class ObjetoNaoEncontrado(LookupError):
    pass


class StorageBackend(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...
