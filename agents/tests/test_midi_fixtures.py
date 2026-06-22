"""Integration tests on real MIDI fixtures (mido loader, no music21 parse dupes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.analyze_midi_file import load_midi_notes

from agents.harmony_pipeline import run_deterministic_harmony_analysis

_FIXTURES_DIR = Path(__file__).parent / "midi"


def _analyze_fixture(name: str):
    path = _FIXTURES_DIR / name
    load_result = load_midi_notes(path)
    result = run_deterministic_harmony_analysis(
        load_result.notes,
        load_result.beats_per_bar,
    )
    return load_result, result


def _assert_no_duplicate_pitch_classes(events: list[dict]) -> None:
    for event in events:
        pitches = event["pitches"]
        pcs = [p % 12 for p in pitches]
        assert len(pitches) == len(set(pcs)), f"duplicate pitch classes in {pitches}"
        assert len(pitches) <= 6


class TestMidiFixtures:
    def test_clean_functional(self) -> None:
        load_result, result = _analyze_fixture("1_clean_functional.mid")

        assert len(load_result.notes) == 12
        assert len(result.chord_events) == 4
        assert result.key == "C major"
        assert result.tonal_mode == "functional"

        anticip_events = [e for e in result.chord_events if e["is_possible_anticipation"]]
        assert len(anticip_events) == 1
        assert anticip_events[0]["roman_numeral"] == "V"

        functions = [e["function"] for e in result.chord_events]
        assert functions == ["T", "S", "D", "T"]

        nominals = [e["nominal_pos"] for e in result.chord_events]
        assert 8.0 not in nominals

        _assert_no_duplicate_pitch_classes(result.chord_events)
        assert all(len(e["pitches"]) == 3 for e in result.chord_events)

    def test_anticipation(self) -> None:
        load_result, result = _analyze_fixture("2_anticipation.mid")

        assert len(load_result.notes) == 15
        assert len(result.chord_events) == 5

        anticip_events = [e for e in result.chord_events if e["is_possible_anticipation"]]
        assert len(anticip_events) == 2
        anticip_romans = {e["roman_numeral"] for e in anticip_events}
        assert anticip_romans == {"IV", "V"}

        stab = next(e for e in result.chord_events if abs(e["nominal_pos"] - 1.5) < 0.01)
        assert stab["is_possible_anticipation"] is False

        nominals = [e["nominal_pos"] for e in result.chord_events]
        assert 4.0 not in nominals
        assert 8.0 not in nominals

        _assert_no_duplicate_pitch_classes(result.chord_events)
        assert all(len(e["pitches"]) == 3 for e in result.chord_events)

    def test_dorian_modal(self) -> None:
        load_result, result = _analyze_fixture("3_dorian_modal.mid")

        assert len(result.chord_events) == 4
        assert result.tonal_mode in ("modal", "ambiguous")
        assert all(e["function"] is None for e in result.chord_events)

        _assert_no_duplicate_pitch_classes(result.chord_events)
        assert all(len(e["pitches"]) == 3 for e in result.chord_events)
