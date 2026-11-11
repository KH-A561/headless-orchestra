"""Тесты MCP-инструментов: вызов функций-обработчиков напрямую (не через stdio)."""

from __future__ import annotations

import json
from typing import Any, Callable

from agents.mcp_server import analyze_clip, find_midi_clips


def _patch_bridge(
    monkeypatch,
    dispatcher: Callable[[str, dict], Any],
) -> list[tuple[str, dict]]:
    """Подменить ``agents.mcp_server.LiveBridge`` стабом и собрать все вызовы."""
    calls: list[tuple[str, dict]] = []

    class StubBridge:
        def call(self, command: str, params: dict | None = None) -> Any:
            params = params or {}
            calls.append((command, params))
            return dispatcher(command, params)

    monkeypatch.setattr("agents.mcp_server.LiveBridge", StubBridge)
    return calls


def _note(
    pitch: int,
    start_time: float,
    velocity: float = 100.0,
    probability: float = 1.0,
) -> dict[str, Any]:
    return {
        "pitch": pitch,
        "start_time": start_time,
        "duration": 0.25,
        "velocity": velocity,
        "mute": False,
        "probability": probability,
    }


_PADS = {
    "pads": [
        {"note": 36, "name": "DBL BASS B-1"},
        {"note": 37, "name": "DBL BASS C-2"},
        {"note": 38, "name": "FR BASSMUTEA"},
        {"note": 39, "name": "FR BASHAR A3"},
    ]
}

_IN_LOOP_B = [
    (38, 53.45095815642691, 104.140625, 1.0),
    (37, 53.847051646270394, 77.0, 0.5),
    (36, 54.1875, 102.0, 1.0),
    (38, 54.509809201215454, 72.0, 1.0),
    (39, 54.86459816225441, 100.0, 1.0),
    (38, 55.21440928862804, 87.0, 1.0),
    (37, 55.56623844905095, 81.0, 0.5),
]

_OUTSIDE_B = [
    (36, 55.89501982392608, 100.0, 1.0),
    (37, 53.14393158924409, 100.0, 1.0),
    (38, 52.74783783924409, 100.0, 1.0),
    (40, 28.28447594072594, 100.0, 1.0),
]


def _fixture_b(notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if notes is None:
        notes = [_note(p, s, v, prob) for p, s, v, prob in _IN_LOOP_B + _OUTSIDE_B]
    return {
        "get_session_snapshot": {
            "tempo": 120.0,
            "time_signature": "4/4",
            "tracks": [
                {"index": 0, "name": "8-Drum Rack 2", "type": "midi", "clips": 1, "devices": []}
            ],
        },
        "get_track_info": {
            "clip_slots": [
                {
                    "index": 0,
                    "has_clip": True,
                    "clip": {"name": "8-Drum Rack 2", "length": 4.0, "is_playing": False},
                }
            ],
            "devices": [
                {"index": 0, "name": "Velocity", "class_name": "MidiVelocity"},
                {"index": 1, "name": "Drum Rack", "class_name": "DrumGroupDevice"},
            ],
        },
        "get_clip_info": {
            "length": 4.0,
            "looping": True,
            "loop_start": 53.45095815642691,
            "loop_end": 55.875,
            "start_marker": 53.45095815642691,
            "end_marker": 79.90760385447885,
            "signature_numerator": 4,
            "signature_denominator": 4,
        },
        "get_clip_notes": {"notes": notes},
        "get_drum_pads": _PADS,
    }


class TestFindMidiClips:
    _SNAPSHOT = {
        "tempo": 120.0,
        "time_signature": "4/4",
        "tracks": [
            {"index": 0, "name": "Drums", "type": "midi", "clips": 2, "devices": []},
            {"index": 1, "name": "Audio Lead", "type": "audio", "clips": 3, "devices": []},
            {"index": 2, "name": "Bass", "type": "midi", "clips": 1, "devices": []},
        ],
    }

    _TRACK_INFOS = {
        0: {
            "clip_slots": [
                {
                    "index": 0,
                    "has_clip": True,
                    "clip": {"name": "Kick Pattern", "length": 2.0, "is_playing": False},
                },
                {
                    "index": 1,
                    "has_clip": True,
                    "clip": {"name": "Hihat", "length": 2.0, "is_playing": True},
                },
            ],
            "devices": [{"index": 0, "name": "Drum Rack", "class_name": "DrumGroupDevice"}],
        },
        2: {
            "clip_slots": [
                {
                    "index": 0,
                    "has_clip": True,
                    "clip": {"name": "Bassline", "length": 4.0, "is_playing": False},
                }
            ],
            "devices": [],
        },
    }

    @staticmethod
    def _dispatcher(command: str, params: dict) -> Any:
        if command == "get_session_snapshot":
            return TestFindMidiClips._SNAPSHOT
        if command == "get_track_info":
            return TestFindMidiClips._TRACK_INFOS[params["track_index"]]
        raise AssertionError(f"unexpected command: {command}")

    def test_filter_and_skips_audio(self, monkeypatch) -> None:
        calls = _patch_bridge(monkeypatch, self._dispatcher)

        result = json.loads(find_midi_clips("drum"))

        assert result["tempo"] == 120.0
        assert result["time_signature"] == "4/4"
        assert len(result["clips"]) == 2
        assert all(c["track_index"] == 0 for c in result["clips"])
        assert all(c["has_drum_rack"] is True for c in result["clips"])

        track_info_params = [params for cmd, params in calls if cmd == "get_track_info"]
        assert {"track_index": 1} not in track_info_params
        assert sorted(p["track_index"] for p in track_info_params) == [0, 2]

    def test_empty_query_returns_all(self, monkeypatch) -> None:
        _patch_bridge(monkeypatch, self._dispatcher)

        result = json.loads(find_midi_clips(""))

        assert len(result["clips"]) == 3


class TestAnalyzeClip:
    def test_compact_no_verbose_keys(self, monkeypatch) -> None:
        responses = _fixture_b()
        _patch_bridge(monkeypatch, lambda cmd, params: responses[cmd])

        text = analyze_clip(0, 0)

        assert "onsets" not in text
        assert "raw_notes" not in text
        assert "buckets" not in text
        assert len(text) < 4096

        data = json.loads(text)
        assert data["context"]["notes_in_region"] == 7
        assert data["rhythm"] is not None
        assert data["harmony"] is not None
        assert data["errors"] == {}

    def test_detail_returns_full_dump(self, monkeypatch) -> None:
        responses = _fixture_b()
        _patch_bridge(monkeypatch, lambda cmd, params: responses[cmd])

        text = analyze_clip(0, 0, detail=True)

        assert "onsets" in text
        assert "raw_notes" in text

    def test_empty_window_errors_no_exception(self, monkeypatch) -> None:
        responses = _fixture_b(notes=[])
        _patch_bridge(monkeypatch, lambda cmd, params: responses[cmd])

        data = json.loads(analyze_clip(0, 0))

        assert data["rhythm"] is None
        assert data["harmony"] is None
        assert data["errors"]
        assert data["context"]["notes_total"] == 0
