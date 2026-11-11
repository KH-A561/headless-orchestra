"""Минимальный read-only клиент сокета моста ``mcp-server-ableton-live``.

Протокол моста (проверено по исходникам ``ableton_live_mcp`` 1.8.1):
- TCP, ``ABLETON_HOST`` (по умолчанию ``127.0.0.1``) и ``ABLETON_PORT``
  (по умолчанию ``9877``) из переменных окружения;
- запрос — один JSON-объект ``{"type": "<command>", "params": {...}}``, UTF-8,
  без разделителя;
- ответ — один JSON-объект ``{"status": "success", "result": {...}}`` либо
  ``{"status": "error", "message": "..."}``; читать чанками, пока буфер не
  распарсится как JSON.

Клиент строго read-only: принимает только команды из белого списка и открывает
новое соединение на каждый вызов.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any

# Жёсткий белый список команд. Любая другая команда отклоняется до отправки.
ALLOWED_COMMANDS = frozenset(
    {
        "get_session_snapshot",
        "get_session_info",
        "get_track_info",
        "get_clip_notes",
        "get_clip_info",
        "get_drum_pads",
    }
)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9877
_DEFAULT_TIMEOUT = 15.0

_HINT = (
    "Live запущен? В Settings → Tempo & MIDI выбран Control Surface «AbletonMCP»? "
    "Модальный диалог в Live блокирует мост."
)


class BridgeError(Exception):
    """Ошибка моста: нет соединения / таймаут / status=error."""


class LiveBridge:
    """Клиент сокета моста Ableton.

    Args:
        host: адрес моста; ``None`` — из ``ABLETON_HOST`` (по умолчанию 127.0.0.1).
        port: порт моста; ``None`` — из ``ABLETON_PORT`` (по умолчанию 9877).
        timeout: таймаут на команду в секундах.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.host = host or os.environ.get("ABLETON_HOST", _DEFAULT_HOST)
        raw_port = port if port is not None else os.environ.get("ABLETON_PORT")
        self.port = int(raw_port) if raw_port is not None else _DEFAULT_PORT
        self.timeout = timeout

    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Выполнить команду моста и вернуть поле ``result`` ответа.

        Args:
            command: имя команды (должно быть в ``ALLOWED_COMMANDS``).
            params: параметры команды.

        Returns:
            Словарь ``result`` из успешного ответа моста.

        Raises:
            ValueError: команда не из белого списка (до отправки).
            BridgeError: нет соединения, таймаут или ``status=error``.
        """
        if command not in ALLOWED_COMMANDS:
            raise ValueError(f"Команда не в белом списке: {command}")

        request = {"type": command, "params": params or {}}
        payload = json.dumps(request).encode("utf-8")

        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except socket.timeout:
            raise BridgeError(
                f"Таймаут подключения к мосту Ableton ({self.host}:{self.port}). {_HINT}"
            ) from None
        except OSError as e:
            raise BridgeError(
                f"Не удалось подключиться к мосту Ableton ({self.host}:{self.port}). {_HINT}"
            ) from e

        with sock:
            sock.settimeout(self.timeout)
            try:
                sock.sendall(payload)
                raw = self._receive(sock)
            except socket.timeout:
                raise BridgeError(
                    f"Таймаут ответа моста Ableton ({self.timeout:g} с). {_HINT}"
                ) from None
            except OSError as e:
                raise BridgeError(f"Ошибка соединения с мостом Ableton. {_HINT}") from e

        try:
            response = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise BridgeError(f"Некорректный ответ моста Ableton: {raw!r}") from e

        if not isinstance(response, dict):
            raise BridgeError(f"Некорректный ответ моста Ableton: {raw!r}")

        status = response.get("status")
        if status == "success":
            result = response.get("result", {})
            return result if isinstance(result, dict) else {}
        if status == "error":
            raise BridgeError(str(response.get("message", "Мост вернул ошибку")))

        raise BridgeError(f"Неожиданный ответ моста Ableton: {raw!r}")

    def _receive(self, sock: socket.socket) -> bytes:
        """Читать ответ чанками, пока буфер не распарсится как один JSON-объект."""
        buffer = b""
        while True:
            try:
                json.loads(buffer.decode("utf-8"))
                return buffer
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
        return buffer
