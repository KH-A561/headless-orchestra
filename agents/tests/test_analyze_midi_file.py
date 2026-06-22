"""Smoke test for offline MIDI harmony harness."""

from __future__ import annotations

from pathlib import Path

import pytest
from music21 import chord, meter, note, stream

from scripts.analyze_midi_file import load_midi_notes

from agents.chord_grouping import parse_start_to_beats
from agents.harmony_pipeline import run_deterministic_harmony_analysis


def _write_c_f_g_midi(path: Path) -> None:
    """Simple I-IV-V in C major on beats 0, 1, 2."""
    score = stream.Score()
    part = stream.Part()
    part.append(meter.TimeSignature("4/4"))
    triads = [
        (0.0, ("C4", "E4", "G4")),
        (1.0, ("F4", "A4", "C5")),
        (2.0, ("G4", "B4", "D5")),
    ]
    for offset, names in triads:
        ch = chord.Chord(names)
        ch.quarterLength = 1.0
        part.insert(offset, ch)
    score.insert(0, part)
    score.write("midi", fp=str(path))


def _analyze_loaded(path: Path):
    load_result = load_midi_notes(path)
    result = run_deterministic_harmony_analysis(
        load_result.notes,
        load_result.beats_per_bar,
    )
    return load_result, result


class TestAnalyzeMidiFile:
    def test_c_major_i_iv_v_progression(self, tmp_path: Path) -> None:
        midi_path = tmp_path / "c_f_g.mid"
        _write_c_f_g_midi(midi_path)

        _, result = _analyze_loaded(midi_path)

        assert result.key == "C major"
        assert len(result.chord_events) == 3
        assert result.tonal_mode == "functional"
        # chord_events — list[dict]: сериализованные LabeledChord для JSON/workflow state.
        functions = [event["function"] for event in result.chord_events]
        assert functions == ["T", "S", "D"]

    def test_fractional_offset_survives_midi_load(self, tmp_path: Path) -> None:
        """Loader only: fractional onset survives quantizePost=False round-trip."""
        score = stream.Score()
        part = stream.Part()
        part.append(meter.TimeSignature("4/4"))
        ch = chord.Chord(["C4", "E4", "G4"])
        ch.quarterLength = 0.5
        part.insert(1.998, ch)
        score.insert(0, part)
        midi_path = tmp_path / "micro.mid"
        score.write("midi", fp=str(midi_path))

        load_result = load_midi_notes(midi_path)
        assert len(load_result.notes) == 3
        starts = {note_obj.pitch: note_obj.start for note_obj in load_result.notes}
        pos = parse_start_to_beats(starts["C3"], load_result.beats_per_bar)
        assert pos == pytest.approx(1.998, abs=0.02)

    def test_jittered_notes_grouped_into_one_chord(self, tmp_path: Path) -> None:
        """Full harness: micro-shifted onsets collapse via tolerant grouping."""
        score = stream.Score()
        part = stream.Part()
        part.append(meter.TimeSignature("4/4"))
        for off, name in [(0.0, "C4"), (0.012, "E4"), (0.018, "G4")]:
            part.insert(off, note.Note(name, quarterLength=1.0))
        score.insert(0, part)
        midi_path = tmp_path / "jitter.mid"
        score.write("midi", fp=str(midi_path))

        load_result = load_midi_notes(midi_path)
        assert len(load_result.notes) == 3

        _, result = _analyze_loaded(midi_path)
        assert len(result.chord_events) == 1
        event = result.chord_events[0]
        assert set(event["pitches"]) == {60, 64, 67}
        assert event["roman_numeral"] == "I"

    def test_chord_expansion_preserves_simultaneity(self, tmp_path: Path) -> None:
        """Chord → separate notes at one offset; grouping yields one event."""
        score = stream.Score()
        part = stream.Part()
        part.append(meter.TimeSignature("4/4"))
        ch = chord.Chord(["C4", "E4", "G4"])
        part.insert(0.0, ch)
        score.insert(0, part)
        midi_path = tmp_path / "triad.mid"
        score.write("midi", fp=str(midi_path))

        load_result = load_midi_notes(midi_path)
        assert len(load_result.notes) == 3
        assert len({n.start for n in load_result.notes}) == 1

        _, result = _analyze_loaded(midi_path)
        assert len(result.chord_events) == 1
