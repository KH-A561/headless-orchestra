"""Тесты доменной модели: windowed, pitch_name, beats_per_bar."""

from __future__ import annotations

import pytest

from agents.domain import (
    ClipData,
    ClipRef,
    NoteEvent,
    TimeSignature,
    beats_per_bar,
    pitch_name,
    windowed,
)


def _clip(
    notes: list[NoteEvent],
    *,
    window: tuple[float, float] | None = (0.0, 4.0),
    pad_map: dict[int, str] | None = None,
) -> ClipData:
    return ClipData(
        ref=ClipRef(id="test:0", track_name="t", clip_name="c"),
        notes=tuple(notes),
        window=window,
        time_signature=TimeSignature(numerator=4, denominator=4),
        tempo_bpm=120.0,
        pad_map=pad_map,
    )


def _note(
    pitch: int,
    start: float,
    *,
    velocity: float = 100.0,
    probability: float = 1.0,
    mute: bool = False,
) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        start=start,
        duration=0.25,
        velocity=velocity,
        probability=probability,
        mute=mute,
    )


class TestPitchName:
    @pytest.mark.parametrize(
        ("midi", "scientific", "ableton"),
        [(60, "C4", "C3"), (36, "C2", "C1"), (0, "C-1", "C-2"), (127, "G9", "G8")],
    )
    def test_both_conventions(self, midi: int, scientific: str, ableton: str) -> None:
        assert pitch_name(midi, "scientific") == scientific
        assert pitch_name(midi, "ableton") == ableton


class TestBeatsPerBar:
    def test_numerator(self) -> None:
        assert beats_per_bar(TimeSignature(numerator=7, denominator=8)) == 7
        assert TimeSignature(numerator=3, denominator=4).beats_per_bar == 3


class TestWindowed:
    def test_loop_shifts_and_counts(self) -> None:
        clip = _clip(
            [
                _note(36, 1.0),
                _note(37, 2.0, probability=0.5),
                _note(38, 5.0),  # вне окна
                _note(39, 0.0, mute=True),
            ],
            window=(1.0, 5.0),
        )
        win = windowed(clip, "loop")

        assert win.total == 4
        assert win.in_region == 2
        assert win.outside_region == 1
        assert win.muted_skipped == 1
        assert win.probability_below_1 == 1
        assert [n.start for n in win.notes] == [0.0, 1.0]
        assert win.length == 4.0

    def test_clip_no_shift_no_window(self) -> None:
        clip = _clip([_note(36, 0.5), _note(37, 5.0)])
        win = windowed(clip, "clip")

        assert win.in_region == 2
        assert win.outside_region == 0
        assert win.length is None
        assert [n.start for n in win.notes] == [0.5, 5.0]

    def test_loop_with_none_window_like_clip(self) -> None:
        clip = _clip([_note(36, 0.5)], window=None)
        win = windowed(clip, "loop")

        assert win.length is None
        assert win.notes[0].start == 0.5

    def test_pad_map_none_pitches_without_pad_empty(self) -> None:
        clip = _clip([_note(36, 0.0), _note(40, 1.0)], pad_map=None)
        win = windowed(clip, "clip")
        assert win.pitches_without_pad == []

    def test_pad_map_known_and_missing(self) -> None:
        clip = _clip(
            [_note(36, 0.0), _note(40, 1.0)],
            pad_map={36: "kick"},
        )
        win = windowed(clip, "clip")
        assert win.pitches_without_pad == [40]
