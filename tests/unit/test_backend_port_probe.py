"""Unit tests for _backend_port_reachable() in migrate.py."""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from migrate import _backend_port_reachable as migrate_probe


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestBackendPortReachable:
    def test_detects_listening_socket(self):
        port = _find_free_port()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        try:
            assert migrate_probe(host="127.0.0.1", port=port, timeout=0.5) is True
        finally:
            srv.close()

    def test_nothing_listening_returns_false(self):
        port = _find_free_port()
        assert migrate_probe(host="127.0.0.1", port=port, timeout=0.2) is False

    def test_timeout_respected(self):
        port = _find_free_port()
        t0 = time.monotonic()
        migrate_probe(host="127.0.0.1", port=port, timeout=0.3)
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0

    def test_accept_then_close(self):
        port = _find_free_port()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        try:
            assert migrate_probe(host="127.0.0.1", port=port) is True
        finally:
            srv.close()
        time.sleep(0.05)
        assert migrate_probe(host="127.0.0.1", port=port, timeout=0.2) is False
