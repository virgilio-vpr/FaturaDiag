from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from typing import Any

import pytest

_connect_original = socket.socket.connect


def _is_local(address: Any) -> bool:
    if not isinstance(address, tuple) or not address:
        return True  # sockets AF_UNIX
    host = str(address[0])
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _bloquear_rede_externa(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Testes de CI não podem chamar LLM nem qualquer serviço externo (§17.4)."""

    def connect_local_only(self: socket.socket, address: Any) -> Any:
        if not _is_local(address):
            raise RuntimeError(f"Acesso à rede externa bloqueado nos testes: {address!r}")
        return _connect_original(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect_local_only)
    yield
