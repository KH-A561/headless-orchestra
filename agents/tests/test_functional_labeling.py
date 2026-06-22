"""Unit tests for deterministic functional harmony labeling."""

from __future__ import annotations

import pytest
from music21 import key as m21key

from agents.functional_labeling import (
    KeyAnalysis,
    analyze_functional_harmony,
    assign_harmonic_functions,
    detect_clip_key,
    detect_tonal_mode,
    label_chord,
)


def _event(pitches: list[int], time: str = "1|1") -> dict:
    return {
        "time": time,
        "raw_pos": 0.0,
        "nominal_pos": 0.0,
        "pitches": pitches,
        "is_possible_anticipation": False,
    }


def _midi(note_name: str, octave: int) -> int:
    names = {
        "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
        "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
    }
    return (octave + 1) * 12 + names[note_name]


def _fixed_key(tonic: str, mode: str, *, confidence: float = 0.95) -> KeyAnalysis:
    """Фиксированная тональность для тестов разметки (не детектор)."""
    k = m21key.Key(tonic.lower(), mode)
    tonic_name = k.tonic.name.replace("-", "b")
    return KeyAnalysis(
        key=f"{tonic_name} {mode}",
        tonic=tonic_name,
        mode=mode,
        key_confidence=confidence,
        alternate_gap=0.2,
        m21_key=k,
    )


class TestDetectClipKey:
    def test_c_major_triad_material(self) -> None:
        pitches = [_midi("C", 3), _midi("E", 3), _midi("G", 3), _midi("F", 3), _midi("G", 3)]
        result = detect_clip_key(pitches)
        assert result.key == "C major"
        assert result.key_confidence > 0.5


class TestFunctionalProgression:
    def test_c_major_i_iv_v(self) -> None:
        events = [
            _event([_midi("C", 3), _midi("E", 3), _midi("G", 3)], "1|1"),
            _event([_midi("F", 3), _midi("A", 3), _midi("C", 4)], "1|2"),
            _event([_midi("G", 3), _midi("B", 3), _midi("D", 4)], "1|3"),
        ]
        all_pitches = [p for e in events for p in e["pitches"]]
        result = analyze_functional_harmony(events, all_pitches)

        assert result.key_analysis.key == "C major"
        assert result.tonal_mode.mode == "functional"
        numerals = [c.roman_numeral for c in result.labeled_chords]
        assert numerals[0] == "I"
        assert numerals[1] == "IV"
        assert numerals[2] == "V"
        functions = [c.function for c in result.labeled_chords]
        assert functions == ["T", "S", "D"]


class TestModalProgression:
    def test_am_d_dorian_loop(self) -> None:
        key_result = _fixed_key("A", "minor")
        am = [_midi("A", 3), _midi("C", 4), _midi("E", 4)]
        d = [_midi("D", 3), _midi("F#", 3), _midi("A", 3)]
        labeled = [
            label_chord(am, key_result, time="1|1"),
            label_chord(d, key_result, time="1|2"),
        ]
        mode = detect_tonal_mode(key_result, labeled)

        assert mode.mode == "modal"
        assert labeled[0].roman_numeral == "i"
        assert labeled[1].roman_numeral == "IV"
        assert all(c.function is None for c in labeled)

        events = [_event(am, "1|1"), _event(d, "1|2")]
        all_pitches = am * 6 + d * 2
        result = analyze_functional_harmony(events, all_pitches)
        assert result.tonal_mode.mode in ("modal", "ambiguous")
        assert all(c.function is None for c in result.labeled_chords)


class TestIncompleteChords:
    def test_power_chord(self) -> None:
        key_result = _fixed_key("C", "major")
        labeled = label_chord([_midi("C", 3), _midi("G", 3)], key_result)

        assert labeled.is_incomplete is True
        assert labeled.quality == "ambiguous"
        assert labeled.roman_numeral == "I"

    def test_unclassified_dyad_does_not_crash(self) -> None:
        """Дайда, которую music21 может не классифицировать — workflow не падает."""
        events = [_event([_midi("C", 3), _midi("D", 3)])]
        result = analyze_functional_harmony(events, events[0]["pitches"])
        ch = result.labeled_chords[0]

        assert ch.is_incomplete is True
        assert ch.function is None


class TestOutOfKey:
    def test_eb_in_c_major(self) -> None:
        key_result = _fixed_key("C", "major")
        labeled = label_chord(
            [_midi("D#", 3), _midi("G", 3), _midi("A#", 3)],
            key_result,
        )
        assert labeled.is_diatonic is False
        assert labeled.function is None

        chords = [labeled]
        assign_harmonic_functions(chords)
        assert labeled.function is None


class TestAmbiguousMode:
    def test_low_confidence_suppresses_functions(self) -> None:
        events = [_event([_midi("C", 3)])]
        all_pitches = [_midi("C", 3)]
        result = analyze_functional_harmony(events, all_pitches)

        assert result.tonal_mode.mode == "ambiguous"
        assert all(c.function is None for c in result.labeled_chords)


class TestFunctionGateInOrchestrator:
    def test_assign_not_called_for_modal(self) -> None:
        key_result = _fixed_key("A", "minor")
        chords = [
            label_chord([_midi("A", 3), _midi("C", 4), _midi("E", 4)], key_result),
            label_chord([_midi("D", 3), _midi("F#", 3), _midi("A", 3)], key_result),
        ]
        mode = detect_tonal_mode(key_result, chords)
        assert mode.mode == "modal"

        for ch in chords:
            ch.function = "SHOULD_NOT_HAPPEN"
        if mode.mode == "functional":
            assign_harmonic_functions(chords)

        assert all(c.function == "SHOULD_NOT_HAPPEN" for c in chords)

    def test_assign_only_via_orchestrator_for_functional(self) -> None:
        events = [
            _event([_midi("C", 3), _midi("E", 3), _midi("G", 3)], "1|1"),
            _event([_midi("F", 3), _midi("A", 3), _midi("C", 4)], "1|2"),
            _event([_midi("G", 3), _midi("B", 3), _midi("D", 4)], "1|3"),
        ]
        all_pitches = [p for e in events for p in e["pitches"]]
        result = analyze_functional_harmony(events, all_pitches)
        assert result.tonal_mode.mode == "functional"
        assert result.labeled_chords[2].function == "D"
