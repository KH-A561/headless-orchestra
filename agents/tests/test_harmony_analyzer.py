"""Unit tests for chord grouping helpers."""

import pytest

from agents.chord_grouping import (
    ChordGroupingConfig,
    beats_to_start,
    group_notes_into_chords,
)
from agents.domain import NoteEvent


def _note(pitch: int, start: float) -> NoteEvent:
    return NoteEvent(pitch=pitch, start=start, duration=1.0, velocity=100.0)


class TestBeatsToStart:
    def test_beats_to_start_roundtrip(self) -> None:
        assert beats_to_start(0.0, 4) == "1|1"
        assert beats_to_start(1.998, 4) == "1|2.998"
        assert beats_to_start(4.0, 4) == "2|1"

    def test_bar_two_beat_one_in_3_4(self) -> None:
        assert beats_to_start(3.0, 3) == "2|1"


class TestGroupNotesIntoChords:
    def test_microshift_chord_stays_one_group(self) -> None:
        notes = [
            _note(60, 0.0),
            _note(64, 0.01),
            _note(67, 0.02),
        ]
        events = group_notes_into_chords(notes)
        assert len(events) == 1
        assert len(events[0].notes) == 3
        assert events[0].is_possible_anticipation is False

    def test_anticipation_flag_near_next_downbeat(self) -> None:
        # pos 3.7 anticipates downbeat at 4.0 (bar 2 beat 1)
        notes = [_note(60, 3.7)]
        events = group_notes_into_chords(notes)
        assert len(events) == 1
        assert events[0].raw_pos == 3.7
        assert events[0].is_possible_anticipation is True

    def test_on_grid_notes_unchanged(self) -> None:
        notes = [
            _note(60, 0.0),
            _note(64, 1.0),
            _note(67, 2.0),
        ]
        events = group_notes_into_chords(notes)
        assert len(events) == 3
        assert all(not event.is_possible_anticipation for event in events)
        assert [event.raw_pos for event in events] == [0.0, 1.0, 2.0]

    def test_syncopation_not_flagged(self) -> None:
        notes = [_note(60, 1.5)]
        events = group_notes_into_chords(notes)
        assert len(events) == 1
        assert events[0].raw_pos == 1.5
        assert events[0].is_possible_anticipation is False

    def test_nominal_pos_snaps_to_grid(self) -> None:
        notes = [_note(60, 0.01)]
        events = group_notes_into_chords(notes)
        assert events[0].nominal_pos == 0.0

    def test_anticipation_flag_in_3_4(self) -> None:
        # pos 2.7 anticipates downbeat at 3.0 (bar 2 beat 1 in 3/4)
        notes = [_note(60, 2.7)]
        config = ChordGroupingConfig(beats_per_bar=3)
        events = group_notes_into_chords(notes, config)
        assert len(events) == 1
        assert events[0].raw_pos == pytest.approx(2.7)
        assert events[0].is_possible_anticipation is True
