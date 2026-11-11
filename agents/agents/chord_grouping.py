"""Группировка MIDI-нот в аккордовые события с допуском по времени."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from .domain import NoteEvent


@dataclass(frozen=True)
class ChordGroupingConfig:
    """Параметры группировки нот в аккорды."""

    # TODO: compound meters (6/8 etc.) — for now use time signature numerator only.
    beats_per_bar: int = 4
    tolerance: float = 0.06
    grid_step: float = 0.25
    anticipation_window: float = 0.5
    strong_beats: tuple[int, ...] = (1,)  # 1-indexed beats within bar


@dataclass
class ChordEvent:
    """Одно аккордовое событие — группа одновременных (или почти одновременных) нот.

    Downstream harmony/voice-leading checks should skip or soften groups where
    is_possible_anticipation is True.
    """

    raw_pos: float
    nominal_pos: float
    notes: list[NoteEvent]
    is_possible_anticipation: bool


def beats_to_start(pos: float, beats_per_bar: int) -> str:
    """Convert absolute beat position back to ``bar|beat`` string (1-indexed)."""
    bar = int(pos // beats_per_bar) + 1
    beat = (pos % beats_per_bar) + 1
    if beat == int(beat):
        return f"{bar}|{int(beat)}"
    return f"{bar}|{beat}"


def _snap_to_grid(pos: float, grid_step: float) -> float:
    return round(pos / grid_step) * grid_step


def _strong_beat_positions(
    raw_pos: float,
    config: ChordGroupingConfig,
    *,
    bars_ahead: int = 2,
) -> list[float]:
    """Strong-beat positions from the bar containing raw_pos through bars_ahead more bars."""
    bar_index = int(raw_pos // config.beats_per_bar)
    start_bar = max(0, bar_index - 1)
    end_bar = bar_index + bars_ahead
    positions: list[float] = []
    for bar in range(start_bar, end_bar + 1):
        for beat in config.strong_beats:
            positions.append(bar * config.beats_per_bar + (beat - 1))
    return sorted(set(positions))


def _distance_to_nearest_strong_beat(raw_pos: float, config: ChordGroupingConfig) -> float:
    for strong_pos in _strong_beat_positions(raw_pos, config):
        if abs(raw_pos - strong_pos) <= config.tolerance:
            return 0.0
    return min(abs(raw_pos - strong_pos) for strong_pos in _strong_beat_positions(raw_pos, config))


def _next_strong_beat_right(raw_pos: float, config: ChordGroupingConfig) -> float | None:
    candidates = [
        pos
        for pos in _strong_beat_positions(raw_pos, config, bars_ahead=4)
        if pos >= raw_pos - config.tolerance
    ]
    for strong_pos in candidates:
        if strong_pos >= raw_pos - config.tolerance and strong_pos - raw_pos > config.tolerance:
            return strong_pos
    return None


def _is_possible_anticipation(raw_pos: float, config: ChordGroupingConfig) -> bool:
    """Time-only anticipation heuristic — may false-positive; safe for downstream leniency."""
    if _distance_to_nearest_strong_beat(raw_pos, config) <= config.tolerance:
        return False
    next_strong = _next_strong_beat_right(raw_pos, config)
    if next_strong is None:
        return False
    return (next_strong - raw_pos) <= config.anticipation_window


def _finalize_group(
    notes_with_pos: list[tuple[NoteEvent, float]],
    config: ChordGroupingConfig,
) -> ChordEvent:
    positions = [pos for _, pos in notes_with_pos]
    raw_pos = statistics.median(positions)
    nominal_pos = _snap_to_grid(raw_pos, config.grid_step)
    return ChordEvent(
        raw_pos=raw_pos,
        nominal_pos=nominal_pos,
        notes=[note for note, _ in notes_with_pos],
        is_possible_anticipation=_is_possible_anticipation(raw_pos, config),
    )


def group_notes_into_chords(
    notes: Sequence[NoteEvent],
    config: ChordGroupingConfig | None = None,
) -> list[ChordEvent]:
    """Group notes into chord events using numeric time tolerance."""
    if config is None:
        config = ChordGroupingConfig()

    if not notes:
        return []

    notes_with_pos = [(note, note.start) for note in notes]
    notes_with_pos.sort(key=lambda item: item[1])

    groups: list[list[tuple[NoteEvent, float]]] = [[notes_with_pos[0]]]

    for note, pos in notes_with_pos[1:]:
        current = groups[-1]
        current_positions = [p for _, p in current]
        median_pos = statistics.median(current_positions)
        if abs(pos - median_pos) <= config.tolerance:
            current.append((note, pos))
        else:
            groups.append([(note, pos)])

    return [_finalize_group(group, config) for group in groups]
