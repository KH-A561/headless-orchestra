"""Unit tests for chord grouping and HarmonyAnalyzer helpers."""

import logging

import pytest
from api_layer.models import Note

from agents.chord_grouping import (
    ChordGroupingConfig,
    beats_to_start,
    group_notes_into_chords,
    parse_start_to_beats,
    parse_time_signature,
)


def _note(pitch: str, start: str) -> Note:
    return Note(pitch=pitch, start=start, duration="1:0")


class TestParseTimeSignature:
    def test_common_signatures(self) -> None:
        assert parse_time_signature("4/4") == 4
        assert parse_time_signature("3/4") == 3
        assert parse_time_signature("7/8") == 7

    def test_empty_string_defaults_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_time_signature("") == 4
        assert "defaulting to 4/4" in caplog.text

    def test_invalid_string_defaults_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_time_signature("abc") == 4
        assert "defaulting to 4/4" in caplog.text


class TestParseStartToBeats:
    def test_bar_beat_examples_4_4(self) -> None:
        assert parse_start_to_beats("1|1", 4) == 0.0
        assert parse_start_to_beats("1|2.998", 4) == pytest.approx(1.998)
        assert parse_start_to_beats("2|1", 4) == 4.0

    def test_beats_to_start_roundtrip(self) -> None:
        assert beats_to_start(0.0, 4) == "1|1"
        assert beats_to_start(1.998, 4) == "1|2.998"
        assert beats_to_start(4.0, 4) == "2|1"

    def test_bar_two_beat_one_in_3_4(self) -> None:
        assert parse_start_to_beats("2|1", 3) == 3.0
        assert beats_to_start(3.0, 3) == "2|1"


class TestGroupNotesIntoChords:
    def test_microshift_chord_stays_one_group(self) -> None:
        notes = [
            _note("C3", "1|1"),
            _note("E3", "1|1.01"),
            _note("G3", "1|1.02"),
        ]
        events = group_notes_into_chords(notes)
        assert len(events) == 1
        assert len(events[0].notes) == 3
        assert events[0].is_possible_anticipation is False

    def test_anticipation_flag_near_next_downbeat(self) -> None:
        # pos 3.7 anticipates downbeat at 4.0 (bar 2 beat 1)
        notes = [_note("C3", "1|4.7")]
        events = group_notes_into_chords(notes)
        assert len(events) == 1
        assert events[0].raw_pos == 3.7
        assert events[0].is_possible_anticipation is True

    def test_on_grid_notes_unchanged(self) -> None:
        notes = [
            _note("C3", "1|1"),
            _note("E3", "1|2"),
            _note("G3", "1|3"),
        ]
        events = group_notes_into_chords(notes)
        assert len(events) == 3
        assert all(not event.is_possible_anticipation for event in events)
        assert [event.raw_pos for event in events] == [0.0, 1.0, 2.0]

    def test_syncopation_not_flagged(self) -> None:
        notes = [_note("C3", "1|2.5")]
        events = group_notes_into_chords(notes)
        assert len(events) == 1
        assert events[0].raw_pos == 1.5
        assert events[0].is_possible_anticipation is False

    def test_nominal_pos_snaps_to_grid(self) -> None:
        notes = [_note("C3", "1|1.01")]
        events = group_notes_into_chords(notes)
        assert events[0].nominal_pos == 0.0

    def test_anticipation_flag_in_3_4(self) -> None:
        # pos 2.7 anticipates downbeat at 3.0 (bar 2 beat 1 in 3/4)
        notes = [_note("C3", "1|3.7")]
        config = ChordGroupingConfig(beats_per_bar=3)
        events = group_notes_into_chords(notes, config)
        assert len(events) == 1
        assert events[0].raw_pos == pytest.approx(2.7)
        assert events[0].is_possible_anticipation is True
