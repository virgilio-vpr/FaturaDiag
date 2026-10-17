from __future__ import annotations

import socket

import pytest


def test_conexao_externa_e_bloqueada() -> None:
    with pytest.raises(RuntimeError, match="bloqueado"):
        socket.socket().connect(("93.184.216.34", 80))
