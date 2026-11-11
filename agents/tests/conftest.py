"""Общие фикстуры для тестов live_bridge / clip_source / mcp_server."""

from __future__ import annotations

import json
import socketserver
import threading
from typing import Any

import pytest


class FakeBridgeServer:
    """Фейковый мост Ableton: TCP-сервер, отвечающий по словарю {command: result}.

    Поднимает ``socketserver.ThreadingTCPServer`` на 127.0.0.1:0 в отдельном
    потоке и записывает полученные команды в ``recorded``. Команды из
    ``errors`` получают ответ ``{"status": "error", "message": ...}``.
    """

    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        self.recorded: list[dict] = []
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> None:
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:  # noqa: D102
                data = b""
                while True:
                    try:
                        request = json.loads(data.decode("utf-8"))
                        break
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        byte = self.rfile.read(1)
                        if not byte:
                            return
                        data += byte

                outer.recorded.append(request)
                command = request.get("type")
                if command in outer.errors:
                    response = {"status": "error", "message": outer.errors[command]}
                else:
                    response = {"status": "success", "result": outer.responses.get(command)}
                self.wfile.write(json.dumps(response).encode("utf-8"))
                self.wfile.flush()

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


@pytest.fixture
def fake_bridge() -> FakeBridgeServer:
    """Запущенный фейковый мост; тест заполняет ``responses`` и читает ``recorded``."""
    server = FakeBridgeServer()
    server.start()
    yield server
    server.stop()
