"""Тесты адаптера Ableton + windowed(): окно анализа, пэды и material."""

from __future__ import annotations

from typing import Any

import pytest

from agents.adapters.ableton import AbletonAdapter, parse_ref_id
from agents.domain import windowed
from agents.live_bridge import LiveBridge
from agents.rhythm_analyzer import run_deterministic_rhythm_analysis


def _note(
    pitch: int,
    start_time: float,
    velocity: float = 100.0,
    probability: float = 1.0,
    mute: bool = False,
    duration: float = 0.25,
) -> dict[str, Any]:
    return {
        "pitch": pitch,
        "start_time": start_time,
        "duration": duration,
        "velocity": velocity,
        "mute": mute,
        "probability": probability,
    }


def _point_env(fake_bridge, monkeypatch) -> None:
    monkeypatch.setenv("ABLETON_HOST", "127.0.0.1")
    monkeypatch.setenv("ABLETON_PORT", str(fake_bridge.port))


_PADS = {
    "pads": [
        {"note": 36, "name": "DBL BASS B-1"},
        {"note": 37, "name": "DBL BASS C-2"},
        {"note": 38, "name": "FR BASSMUTEA"},
        {"note": 39, "name": "FR BASHAR A3"},
    ]
}

_CLIP_INFO_A = {
    "length": 4.0,
    "looping": True,
    "loop_start": 0.0,
    "loop_end": 4.0,
    "start_marker": 0.0,
    "end_marker": 4.0,
    "signature_numerator": 4,
    "signature_denominator": 4,
}

_STARTS_A = [
    0.0,
    0.9101343968531469,
    1.838241185897436,
    2.7663487554112556,
    3.7124289772727272,
    4.874187791375292,
    5.8921609640359645,
    6.874187531218781,
    7.874187531218781,
]


def _fixture_a(extra_notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    notes = [_note(36, start) for start in _STARTS_A]
    if extra_notes:
        notes = notes + extra_notes
    return {
        "get_session_snapshot": {
            "tempo": 120.0,
            "time_signature": "4/4",
            "tracks": [
                {"index": 0, "name": "8-Drum Rack 1", "type": "midi", "clips": 1, "devices": []}
            ],
        },
        "get_track_info": {
            "clip_slots": [
                {
                    "index": 0,
                    "has_clip": True,
                    "clip": {"name": "8-Drum Rack 1", "length": 4.0, "is_playing": False},
                }
            ],
            "devices": [
                {"index": 0, "name": "Velocity", "class_name": "MidiVelocity"},
                {"index": 1, "name": "Drum Rack", "class_name": "DrumGroupDevice"},
            ],
        },
        "get_clip_info": _CLIP_INFO_A,
        "get_clip_notes": {"notes": notes},
        "get_drum_pads": _PADS,
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


def _fixture_b() -> dict[str, Any]:
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


class TestFixtureA:
    def test_loop_window(self, fake_bridge, monkeypatch) -> None:
        _point_env(fake_bridge, monkeypatch)
        fake_bridge.responses = _fixture_a()

        adapter = AbletonAdapter(LiveBridge())
        clip = adapter.read_clip("ableton:t0/s0")
        win = windowed(clip, "loop")

        assert win.total == 9
        assert win.in_region == 5
        assert win.outside_region == 4
        assert win.muted_skipped == 0
        assert clip.pad_map is not None
        assert clip.pad_map[36] == "DBL BASS B-1"
        assert clip.window == (0.0, 4.0)
        assert len(win.notes) == 5
        assert win.notes[0].start == 0.0
        assert win.notes[0].pitch == 36  # MIDI 36
        assert win.length == 4.0

    def test_clip_window(self, fake_bridge, monkeypatch) -> None:
        _point_env(fake_bridge, monkeypatch)
        fake_bridge.responses = _fixture_a()

        adapter = AbletonAdapter(LiveBridge())
        clip = adapter.read_clip("ableton:t0/s0")
        win = windowed(clip, "clip")

        assert win.in_region == 9
        assert win.outside_region == 0
        assert win.length is None
        assert len(win.notes) == 9

        # Длина клипа выводится по последней ноте: 2 такта по 4 доли.
        rhythm = run_deterministic_rhythm_analysis(
            win.notes,
            clip.time_signature.beats_per_bar,
            clip_length_beats=None,
            material="percussion",
            lane_names=clip.pad_map,
        )
        assert rhythm.clip_length_inferred is True
        assert rhythm.clip_length_beats == 8.0


class TestFixtureB:
    def test_loop_window(self, fake_bridge, monkeypatch) -> None:
        _point_env(fake_bridge, monkeypatch)
        fake_bridge.responses = _fixture_b()

        adapter = AbletonAdapter(LiveBridge())
        clip = adapter.read_clip("ableton:t0/s0")
        win = windowed(clip, "loop")

        assert win.in_region == 7
        assert win.outside_region == 4
        assert win.probability_below_1 == 2
        assert win.pitches_without_pad == []
        assert win.notes[0].start == 0.0  # сдвиг сработал
        assert win.notes[0].velocity == 104.140625  # float, без округления
        assert win.length == pytest.approx(2.4240, abs=1e-4)

    def test_clip_window_pitches_without_pad(self, fake_bridge, monkeypatch) -> None:
        _point_env(fake_bridge, monkeypatch)
        fake_bridge.responses = _fixture_b()

        adapter = AbletonAdapter(LiveBridge())
        clip = adapter.read_clip("ableton:t0/s0")
        win = windowed(clip, "clip")

        assert win.pitches_without_pad == [40]


class TestMutedNotes:
    def test_muted_note_skipped_and_counted(self, fake_bridge, monkeypatch) -> None:
        _point_env(fake_bridge, monkeypatch)
        fake_bridge.responses = _fixture_a(extra_notes=[_note(36, 1.0, mute=True)])

        adapter = AbletonAdapter(LiveBridge())
        clip = adapter.read_clip("ableton:t0/s0")
        win = windowed(clip, "loop")

        assert win.total == 10
        assert win.muted_skipped == 1
        assert win.in_region == 5
        assert len(win.notes) == 5


class TestNoDrumRack:
    def test_heuristic_material_and_no_pads(self, fake_bridge, monkeypatch) -> None:
        _point_env(fake_bridge, monkeypatch)
        responses = _fixture_a()
        responses["get_track_info"]["devices"] = [
            {"index": 0, "name": "Simpler", "class_name": "Instrument"}
        ]
        responses["get_session_snapshot"]["tracks"][0]["name"] = "Keys"
        fake_bridge.responses = responses

        adapter = AbletonAdapter(LiveBridge())
        clip = adapter.read_clip("ableton:t0/s0")
        win = windowed(clip, "loop")

        assert clip.pad_map is None
        assert win.pitches_without_pad == []  # pad_map=None → []

        commands = [record["type"] for record in fake_bridge.recorded]
        assert "get_drum_pads" not in commands


class TestParseRefId:
    def test_valid(self) -> None:
        assert parse_ref_id("ableton:t7/s8") == (7, 8)

    def test_garbage(self) -> None:
        with pytest.raises(ValueError):
            parse_ref_id("file:foo#all")
        with pytest.raises(ValueError):
            parse_ref_id("ableton:xyz")


class TestTrackName:
    def test_track_name_from_track_info_not_snapshot_order(
        self, fake_bridge, monkeypatch
    ) -> None:
        _point_env(fake_bridge, monkeypatch)
        responses = _fixture_a()
        # Порядок/индексы в снапшоте не совпадают с track_index клипа.
        responses["get_session_snapshot"]["tracks"] = [
            {"index": 5, "name": "Wrong Order", "type": "midi", "clips": 1, "devices": []}
        ]
        responses["get_track_info"] = {
            "name": "Real Track Name",
            "clip_slots": [
                {"index": 0, "has_clip": True, "clip": {"name": "Clip", "length": 4.0}}
            ],
            "devices": [],
        }
        fake_bridge.responses = responses

        adapter = AbletonAdapter(LiveBridge())
        clip = adapter.read_clip("ableton:t0/s0")

        assert clip.ref.track_name == "Real Track Name"
