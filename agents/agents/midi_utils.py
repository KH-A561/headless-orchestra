"""Общие MIDI-утилиты (конвертация pitch-строк в Ableton-конвенции)."""

from __future__ import annotations

# Sharp-default pitch-class names (Ableton convention).
_PC_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_to_ableton_pitch(midi: int) -> str:
    """MIDI номер → строка pitch в конвенции Ableton (C3 = MIDI 60).

    Ableton C3 = music21 C4 = MIDI 60.
    """
    pc = midi % 12
    octave = midi // 12 - 2
    return f"{_PC_NAMES[pc]}{octave}"
