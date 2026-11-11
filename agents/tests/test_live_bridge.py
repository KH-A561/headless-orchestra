"""Тесты LiveBridge: белый список, ошибки, таймауты, успех."""

from __future__ import annotations

import socket

import pytest

from agents.live_bridge import ALLOWED_COMMANDS, BridgeError, LiveBridge


class TestLiveBridge:
    def test_whitelist_rejects_unknown_command(self, fake_bridge, monkeypatch) -> None:
        monkeypatch.setenv("ABLETON_HOST", "127.0.0.1")
        monkeypatch.setenv("ABLETON_PORT", str(fake_bridge.port))
        bridge = LiveBridge()

        with pytest.raises(ValueError):
            bridge.call("delete_track")

        assert fake_bridge.recorded == []

    def test_status_error_raises_bridge_error(self, fake_bridge, monkeypatch) -> None:
        monkeypatch.setenv("ABLETON_HOST", "127.0.0.1")
        monkeypatch.setenv("ABLETON_PORT", str(fake_bridge.port))
        fake_bridge.errors = {"get_session_snapshot": "Track not found"}

        bridge = LiveBridge()
        with pytest.raises(BridgeError, match="Track not found"):
            bridge.call("get_session_snapshot")

    def test_connection_refused_raises_bridge_error_with_hint(self) -> None:
        # Свободный порт без слушателя → ConnectionRefusedError.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
        probe.close()

        bridge = LiveBridge(host="127.0.0.1", port=free_port, timeout=2.0)
        with pytest.raises(BridgeError, match="Control Surface"):
            bridge.call("get_session_snapshot")

    def test_success_returns_result(self, fake_bridge, monkeypatch) -> None:
        monkeypatch.setenv("ABLETON_HOST", "127.0.0.1")
        monkeypatch.setenv("ABLETON_PORT", str(fake_bridge.port))
        fake_bridge.responses = {"get_session_snapshot": {"tempo": 120.0}}

        bridge = LiveBridge()
        result = bridge.call("get_session_snapshot")

        assert result == {"tempo": 120.0}
        assert fake_bridge.recorded == [{"type": "get_session_snapshot", "params": {}}]

    def test_all_whitelisted_commands_accepted_by_type_check(self) -> None:
        # Все команды из белого списка проходят проверку (без реального соединения).
        assert ALLOWED_COMMANDS == {
            "get_session_snapshot",
            "get_session_info",
            "get_track_info",
            "get_clip_notes",
            "get_clip_info",
            "get_drum_pads",
        }
