"""Нейтральная доменная модель ядра (без DAW-специфики) и функции ядра.

Ядро работает с ``NoteEvent`` (MIDI pitch int, время в четвертях float) и не
знает ни про Ableton-конвенцию ``C3=60``, ни про строки ``"bar|beat"``. Всё,
что связано с Live, живёт в адаптере Ableton; всё, что связано с ``.mid``, —
в файловом адаптере; music21 — только внутри гармонического анализатора.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Имена питч-классов (диезы, как и раньше).
_PC_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class NoteEvent(BaseModel, frozen=True):
    """Одна нота клипа в нейтральном представлении.

    Attributes:
        pitch: MIDI-номер 0..127.
        start: позиция в четвертях от начала клипа (может быть < 0 — не отбрасывать).
        duration: длительность в четвертях, >= 0.
        velocity: 0..127, дробная допустима.
        probability: вероятность ноты.
        mute: замьючена ли нота.
    """

    pitch: int
    start: float
    duration: float
    velocity: float
    probability: float = 1.0
    mute: bool = False


class TimeSignature(BaseModel, frozen=True):
    """Размер такта.

    ``beats_per_bar`` = ``numerator`` (как сейчас; compound-размеры — известное
    ограничение).
    """

    numerator: int
    denominator: int

    @property
    def beats_per_bar(self) -> int:
        """Долей в такте — числитель (compound-размеры не различаются)."""
        return self.numerator


class ClipRef(BaseModel, frozen=True):
    """Ссылка на клип; ``id`` непрозрачен для ядра.

    Примеры ``id``: ``"ableton:t7/s8"``, ``"file:<path>#all"``, ``"file:<path>#t0"``.
    """

    id: str
    track_name: str
    clip_name: str


class ClipData(BaseModel, frozen=True):
    """Полные данные клипа для анализа."""

    ref: ClipRef
    notes: tuple[NoteEvent, ...]  # все ноты клипа, позиции от начала клипа
    window: tuple[float, float] | None  # петля/маркеры; None — границ нет (файл)
    time_signature: TimeSignature
    tempo_bpm: float | None
    pad_map: dict[int, str] | None  # None — инструмент не «кит»; {} — кит без имён


class ClipSummary(BaseModel, frozen=True):
    """Краткая информация о клипе (для перечисления клипов)."""

    ref: ClipRef
    length: float | None
    is_playing: bool | None
    has_kit: bool


class WindowedClip(BaseModel, frozen=True):
    """Ноты после применения окна анализа + счётчики выбора окна."""

    notes: tuple[NoteEvent, ...]  # сдвинуты к 0 для "loop", без muted
    length: float | None  # window[1]-window[0] или None
    total: int
    in_region: int
    outside_region: int
    muted_skipped: int
    probability_below_1: int
    pitches_without_pad: list[int]


def beats_per_bar(ts: TimeSignature) -> int:
    """Долей в такте (числитель размера)."""
    return ts.numerator


def pitch_name(
    midi: int,
    convention: Literal["scientific", "ableton"] = "scientific",
) -> str:
    """MIDI-номер → строка имени питча.

    ``scientific``: C4 = 60; ``ableton``: C3 = 60. Диезы, как раньше.
    """
    pc = midi % 12
    if convention == "scientific":
        octave = midi // 12 - 1
    else:
        octave = midi // 12 - 2
    return f"{_PC_NAMES[pc]}{octave}"


def windowed(
    clip: ClipData,
    region: Literal["loop", "clip"],
) -> WindowedClip:
    """Единственное место, где считается окно анализа.

    ``"loop"`` при ``clip.window is None`` → то же, что ``"clip"`` (границ нет).

    Логика и порядок подсчёта — ровно как раньше в ``clip_source.load_clip``:
    для каждой ноты считаем ``total``, пропускаем muted, отбрасываем ноты вне
    окна, сдвигаем позиции окна к нулю, считаем ``probability < 1`` только по
    нотам в регионе.
    """
    if region == "loop" and clip.window is not None:
        win_start, win_end = clip.window
    else:
        win_start, win_end = None, None

    notes_out: list[NoteEvent] = []
    total = 0
    in_region = 0
    outside_region = 0
    muted_skipped = 0
    probability_below_1 = 0
    analyzed_pitches: set[int] = set()

    for note in clip.notes:
        total += 1
        if note.mute:
            muted_skipped += 1
            continue

        if win_end is not None and (note.start < win_start or note.start >= win_end):
            outside_region += 1
            continue

        in_region += 1
        analyzed_pitches.add(note.pitch)

        if note.probability < 1.0:
            probability_below_1 += 1

        pos = note.start if win_start is None else note.start - win_start
        notes_out.append(
            NoteEvent(
                pitch=note.pitch,
                start=pos,
                duration=note.duration,
                velocity=note.velocity,
                probability=note.probability,
                mute=False,
            )
        )

    if clip.pad_map is not None:
        pitches_without_pad = sorted(p for p in analyzed_pitches if p not in clip.pad_map)
    else:
        pitches_without_pad = []

    length = win_end - win_start if win_end is not None else None

    return WindowedClip(
        notes=tuple(notes_out),
        length=length,
        total=total,
        in_region=in_region,
        outside_region=outside_region,
        muted_skipped=muted_skipped,
        probability_below_1=probability_below_1,
        pitches_without_pad=pitches_without_pad,
    )
