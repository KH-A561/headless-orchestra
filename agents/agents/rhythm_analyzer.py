"""Детерминированный ритмический анализ MIDI-клипа (лейны, циклы, тайминг, velocity).

Всё выдаётся как нейтральные наблюдения с числом и confidence, без оценок
«правильно/неправильно». Лейн ``all`` присутствует всегда; для перкуссионного
материала добавляется лейн на каждый уникальный MIDI-питч.

Доли = четверти, отсчёт от 0 с начала клипа. Compound-размеры (6/8 и т.п.)
обрабатываются как в гармоническом слое: долей в такте = числитель.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from api_layer.models import Note

from .chord_grouping import parse_start_to_beats
from .harmony_pipeline import pitch_to_midi
from .midi_utils import midi_to_ableton_pitch

logger = logging.getLogger(__name__)

ObservationCode = Literal[
    "CYCLE",
    "SWING_8TH",
    "LAID_BACK",
    "PUSHED",
    "LOOSE",
    "UNQUANTIZED",
    "UNIFORM_VELOCITY",
    "ACCENTS",
    "GHOST_NOTES",
    "EMPTY_BARS",
    "TRAILING_EMPTY",
]

# Онсет: (позиция в долях, MIDI-номер, velocity).
Onset = tuple[float, int, int]


@dataclass(frozen=True)
class RhythmConfig:
    """Пороги ритмического анализа. Все дефолты — из ТЗ, раздел 4."""

    simultaneity_tol: float = 0.06
    routing_mono_min: float = 0.75
    routing_chrom_min: float = 0.5
    cycle_min_intervals: int = 3
    cycle_cv_max: float = 0.15
    timing_min_onsets: int = 4
    unquantized_dev: float = 0.08
    unquantized_ratio_min: float = 0.5
    shift_min: float = 0.02
    loose_std_min: float = 0.03
    swing_window_lo: float = 0.45
    swing_window_hi: float = 0.72
    swing_min_onsets: int = 3
    swing_std_max: float = 0.03
    swing_ratio_min: float = 0.53
    timing_conf_full: int = 16
    velocity_min_onsets: int = 4
    uniform_range_max: int = 2
    accent_ratio: float = 1.15
    ghost_ratio: float = 0.6


class Observation(BaseModel):
    """Одно нейтральное наблюдение (уровня лейна или клипа)."""

    code: ObservationCode
    lane_id: str | None  # None для наблюдений уровня клипа
    value: dict[str, Any]
    confidence: float  # 0..1
    text: str


class CycleInfo(BaseModel):
    """Информация о цикле лейна."""

    interval_mean: float
    interval_cv: float
    period_beats: float  # округлено до 0.5 доли
    aligns_with_bar: bool
    realign_bars: int  # через сколько тактов цикл снова совпадает с тактом


class BucketStats(BaseModel):
    """Статистика одной корзины 16-х (0..3)."""

    count: int
    dev_mean: float
    dev_std: float


class TimingStats(BaseModel):
    """Статистика тайминга лейна (по остаточным отклонениям)."""

    dev_mean: float  # среднее знаковое отклонение от ближайшей 16-й, в долях
    dev_std: float  # population std
    unquantized_ratio: float
    buckets: dict[int, BucketStats]  # только непустые корзины
    swing_ratio: float | None = None  # mean(frac) кандидатов свинга, если найден


class VelocityStats(BaseModel):
    """Статистика velocity лейна."""

    min: int
    max: int
    median: float
    mean: float
    std: float


class LaneAnalysis(BaseModel):
    """Анализ одного лейна."""

    lane_id: str  # "all" или str(midi_pitch)
    pitch: int | None
    pitch_name: str | None  # Ableton-имя, например "C1"
    label: str | None  # из lane_names
    onsets: list[float]
    count: int
    intervals: list[float]
    interval_mean: float | None  # None, если интервалов нет
    interval_cv: float | None  # None, если интервалов < 2 (или mean == 0)
    cycle: CycleInfo | None
    timing: TimingStats
    velocity: VelocityStats
    hits_per_bar: list[int]


class RoutingInfo(BaseModel):
    """Решение о типе материала + признаки, на которых оно основано."""

    material: Literal["percussion", "pitched"]
    source: Literal["explicit", "auto"]
    monophonic_ratio: float
    distinct_pitches: int
    chromatic_neighbor_ratio: float


class DeterministicRhythmAnalysis(BaseModel):
    """Полный результат детерминированного ритмического анализа."""

    beats_per_bar: int
    clip_length_beats: float
    clip_length_inferred: bool
    routing: RoutingInfo
    lanes: list[LaneAnalysis]  # первым всегда "all", дальше по возрастанию pitch
    observations: list[Observation]


def _pstdev(values: list[float]) -> float:
    """Population std; 0.0 для пустого/одноэлементного списка (нет разброса)."""
    if len(values) < 2:
        return 0.0
    return statistics.pstdev(values)


def _build_onsets(notes: list[Note], beats_per_bar: int) -> list[Onset]:
    """Ноты → онсеты (позиция, MIDI-номер, velocity); невалидные питчи пропускаются."""
    onsets: list[Onset] = []
    for note in notes:
        try:
            midi = pitch_to_midi(note.pitch)
        except ValueError as e:
            logger.warning("skip invalid pitch %s: %s", note.pitch, e)
            continue
        pos = parse_start_to_beats(note.start, beats_per_bar)
        onsets.append((pos, midi, note.velocity))
    onsets.sort(key=lambda o: o[0])
    return onsets


def _resolve_clip_length(
    onsets: list[Onset],
    beats_per_bar: int,
    clip_length_beats: float | None,
) -> tuple[float, bool, int]:
    """Возвращает (clip_length_beats, clip_length_inferred, num_bars)."""
    last_onset = onsets[-1][0]
    if clip_length_beats is not None:
        for pos, _, _ in onsets:
            if pos >= clip_length_beats:
                logger.warning(
                    "onset at %.4f beats lies beyond clip length %.4f beats",
                    pos,
                    clip_length_beats,
                )
        actual_last_bar_end = math.ceil((last_onset + 1e-9) / beats_per_bar) * beats_per_bar
        effective = max(clip_length_beats, actual_last_bar_end)
        return clip_length_beats, False, int(math.ceil(effective / beats_per_bar))

    clip = math.ceil((last_onset + 1e-9) / beats_per_bar) * beats_per_bar
    return clip, True, int(math.ceil(clip / beats_per_bar))


def _monophonic_ratio(onsets: list[Onset], tol: float) -> float:
    """Доля групп одновременных онсетов, где ровно один уникальный питч."""
    if not onsets:
        return 0.0
    groups: list[list[Onset]] = []
    current = [onsets[0]]
    first_time = onsets[0][0]
    for onset in onsets[1:]:
        if onset[0] - first_time <= tol:
            current.append(onset)
        else:
            groups.append(current)
            current = [onset]
            first_time = onset[0]
    groups.append(current)

    mono = sum(1 for g in groups if len({p for _, p, _ in g}) == 1)
    return mono / len(groups)


def _chromatic_neighbor_ratio(pitches: list[int]) -> float:
    """Доля уникальных питчей, у которых в наборе есть сосед ±1 полутон."""
    unique = set(pitches)
    if not unique:
        return 0.0
    with_neighbor = sum(1 for p in unique if (p - 1) in unique or (p + 1) in unique)
    return with_neighbor / len(unique)


def _compute_routing(
    onsets: list[Onset],
    config: RhythmConfig,
    material: Literal["percussion", "pitched", "auto"],
) -> RoutingInfo:
    mono = _monophonic_ratio(onsets, config.simultaneity_tol)
    pitches = sorted({p for _, p, _ in onsets})
    distinct = len(pitches)
    chrom = _chromatic_neighbor_ratio(pitches)

    source: Literal["explicit", "auto"] = "explicit" if material != "auto" else "auto"
    if material == "auto":
        resolved: Literal["percussion", "pitched"] = (
            "percussion"
            if mono >= config.routing_mono_min and chrom >= config.routing_chrom_min
            else "pitched"
        )
    else:
        resolved = material

    return RoutingInfo(
        material=resolved,
        source=source,
        monophonic_ratio=mono,
        distinct_pitches=distinct,
        chromatic_neighbor_ratio=chrom,
    )


def _detect_cycle(
    intervals: list[float],
    config: RhythmConfig,
    beats_per_bar: int,
) -> CycleInfo | None:
    """Определяет цикл, если интервалы стабильны (cv <= cycle_cv_max)."""
    if len(intervals) < config.cycle_min_intervals:
        return None

    mean = statistics.mean(intervals)
    if mean <= 0:
        return None
    std = _pstdev(intervals)
    cv = std / mean
    if cv > config.cycle_cv_max:
        return None

    period_beats = round(mean * 2) / 2
    h = int(round(period_beats * 2))
    b = beats_per_bar * 2
    if h <= 0:
        return None
    aligns_with_bar = (b % h == 0) or (h % b == 0)
    realign_bars = math.lcm(h, b) // b

    return CycleInfo(
        interval_mean=mean,
        interval_cv=cv,
        period_beats=period_beats,
        aligns_with_bar=aligns_with_bar,
        realign_bars=realign_bars,
    )


def _detect_swing_ratio(
    rows: list[tuple[float, float, float, int]],
    config: RhythmConfig,
) -> float | None:
    """Возвращает mean(frac) кандидатов свинга, если свинг найден, иначе None."""
    cand_fracs = [
        frac
        for _, frac, _, _ in rows
        if config.swing_window_lo <= frac <= config.swing_window_hi
    ]
    if len(cand_fracs) < config.swing_min_onsets:
        return None
    if _pstdev(cand_fracs) > config.swing_std_max:
        return None
    mean_frac = statistics.mean(cand_fracs)
    if mean_frac < config.swing_ratio_min:
        return None
    return mean_frac


def _timing_stats(positions: list[float], config: RhythmConfig) -> TimingStats:
    """Считает тайминговые статистики; buckets — всегда по сырому dev."""
    rows: list[tuple[float, float, float, int]] = []
    for pos in positions:
        frac = pos - math.floor(pos)
        g = round(frac * 4) / 4
        dev = frac - g
        bucket = round(frac * 4) % 4
        rows.append((pos, frac, dev, bucket))

    buckets: dict[int, BucketStats] = {}
    for b in range(4):
        devs = [dev for _, _, dev, bk in rows if bk == b]
        if devs:
            buckets[b] = BucketStats(
                count=len(devs),
                dev_mean=statistics.mean(devs),
                dev_std=_pstdev(devs),
            )

    swing_ratio = _detect_swing_ratio(rows, config)

    residuals: list[float] = []
    for _, frac, dev, _ in rows:
        if swing_ratio is not None and config.swing_window_lo <= frac <= config.swing_window_hi:
            residuals.append(frac - swing_ratio)
        else:
            residuals.append(dev)

    dev_mean = statistics.mean(residuals)
    dev_std = _pstdev(residuals)
    unquantized = sum(1 for r in residuals if abs(r) > config.unquantized_dev) / len(residuals)

    return TimingStats(
        dev_mean=dev_mean,
        dev_std=dev_std,
        unquantized_ratio=unquantized,
        buckets=buckets,
        swing_ratio=swing_ratio,
    )


def _velocity_stats(velocities: list[int]) -> VelocityStats:
    return VelocityStats(
        min=min(velocities),
        max=max(velocities),
        median=statistics.median(velocities),
        mean=statistics.mean(velocities),
        std=_pstdev([float(v) for v in velocities]),
    )


def _hits_per_bar(positions: list[float], beats_per_bar: int, num_bars: int) -> list[int]:
    hits = [0] * num_bars
    for pos in positions:
        bar = int(pos // beats_per_bar)
        if 0 <= bar < num_bars:
            hits[bar] += 1
        else:
            logger.warning("onset at %.4f beats outside %d bars", pos, num_bars)
    return hits


def _cycle_text(cycle: CycleInfo, beats_per_bar: int) -> str:
    if cycle.aligns_with_bar:
        return (
            f"repeats every {cycle.period_beats:.1f} beats, "
            f"aligned with the {beats_per_bar}-beat bar grid"
        )
    return (
        f"repeats every {cycle.period_beats:.1f} beats against "
        f"{beats_per_bar}-beat bar, realigns every {cycle.realign_bars} bars"
    )


def _swing_text(ratio: float) -> str:
    base = f"offbeat 8th notes land late, swing ratio {ratio:.2f}"
    if abs(ratio - 2 / 3) <= 0.03:
        return f"{base} (triplet feel)"
    return base


def _lane_observations(
    lane_id: str,
    onsets: list[Onset],
    cycle: CycleInfo | None,
    timing: TimingStats,
    velocity: VelocityStats,
    config: RhythmConfig,
    beats_per_bar: int,
) -> list[Observation]:
    """Наблюдения уровня лейна: CYCLE, тайминг, velocity."""
    observations: list[Observation] = []
    count = len(onsets)

    if cycle is not None:
        confidence = round(1 - cycle.interval_cv / config.cycle_cv_max, 2)
        observations.append(
            Observation(
                code="CYCLE",
                lane_id=lane_id,
                value={
                    "period_beats": cycle.period_beats,
                    "realign_bars": cycle.realign_bars,
                    "aligns_with_bar": cycle.aligns_with_bar,
                    "interval_cv": cycle.interval_cv,
                },
                confidence=confidence,
                text=_cycle_text(cycle, beats_per_bar),
            )
        )

    if count >= config.timing_min_onsets:
        timing_conf = min(1.0, count / config.timing_conf_full)

        if timing.swing_ratio is not None:
            observations.append(
                Observation(
                    code="SWING_8TH",
                    lane_id=lane_id,
                    value={"ratio": timing.swing_ratio},
                    confidence=timing_conf,
                    text=_swing_text(timing.swing_ratio),
                )
            )

        if timing.unquantized_ratio >= config.unquantized_ratio_min:
            observations.append(
                Observation(
                    code="UNQUANTIZED",
                    lane_id=lane_id,
                    value={"ratio": timing.unquantized_ratio},
                    confidence=timing_conf,
                    text=(
                        f"{timing.unquantized_ratio:.0%} of onsets are more than "
                        f"{config.unquantized_dev:g} beat from the nearest 16th-note"
                    ),
                )
            )
            return observations  # пункты 4–5 не выдаются

        if abs(timing.dev_mean) >= config.shift_min and abs(timing.dev_mean) >= timing.dev_std:
            if timing.dev_mean > 0:
                observations.append(
                    Observation(
                        code="LAID_BACK",
                        lane_id=lane_id,
                        value={"dev_mean": timing.dev_mean},
                        confidence=timing_conf,
                        text=(
                            f"onsets land on average {timing.dev_mean:.3f} beat "
                            "after the 16th-note grid"
                        ),
                    )
                )
            elif timing.dev_mean < 0:
                observations.append(
                    Observation(
                        code="PUSHED",
                        lane_id=lane_id,
                        value={"dev_mean": timing.dev_mean},
                        confidence=timing_conf,
                        text=(
                            f"onsets land on average {abs(timing.dev_mean):.3f} beat "
                            "before the 16th-note grid"
                        ),
                    )
                )

        if timing.dev_std >= config.loose_std_min:
            observations.append(
                Observation(
                    code="LOOSE",
                    lane_id=lane_id,
                    value={"dev_std": timing.dev_std},
                    confidence=timing_conf,
                    text=f"onset timing is spread (std {timing.dev_std:.3f} beat)",
                )
            )

    if count >= config.velocity_min_onsets:
        velocity_conf = min(1.0, count / config.timing_conf_full)

        if velocity.max - velocity.min <= config.uniform_range_max:
            observations.append(
                Observation(
                    code="UNIFORM_VELOCITY",
                    lane_id=lane_id,
                    value={"min": velocity.min, "max": velocity.max},
                    confidence=velocity_conf,
                    text=(
                        f"velocities stay within a range of "
                        f"{velocity.max - velocity.min} (min {velocity.min}, max {velocity.max})"
                    ),
                )
            )

        accents = [pos for pos, _, v in onsets if v >= velocity.median * config.accent_ratio]
        if accents:
            observations.append(
                Observation(
                    code="ACCENTS",
                    lane_id=lane_id,
                    value={"positions": accents},
                    confidence=velocity_conf,
                    text=(
                        f"{len(accents)} onset(s) at or above "
                        f"{config.accent_ratio:g}x the lane median velocity"
                    ),
                )
            )

        ghosts = [pos for pos, _, v in onsets if v <= velocity.median * config.ghost_ratio]
        if ghosts:
            observations.append(
                Observation(
                    code="GHOST_NOTES",
                    lane_id=lane_id,
                    value={"positions": ghosts},
                    confidence=velocity_conf,
                    text=(
                        f"{len(ghosts)} onset(s) at or below "
                        f"{config.ghost_ratio:g}x the lane median velocity"
                    ),
                )
            )

    return observations


def _analyze_lane(
    lane_id: str,
    onsets: list[Onset],
    pitch: int | None,
    pitch_name: str | None,
    label: str | None,
    beats_per_bar: int,
    num_bars: int,
    config: RhythmConfig,
) -> tuple[LaneAnalysis, list[Observation]]:
    positions = [o[0] for o in onsets]
    intervals = [b - a for a, b in zip(positions, positions[1:])]
    interval_mean = statistics.mean(intervals) if intervals else None
    interval_cv = None
    if interval_mean and len(intervals) >= 2:
        interval_cv = _pstdev(intervals) / interval_mean
    cycle = _detect_cycle(intervals, config, beats_per_bar)
    timing = _timing_stats(positions, config)
    velocity = _velocity_stats([o[2] for o in onsets])
    hits = _hits_per_bar(positions, beats_per_bar, num_bars)

    lane = LaneAnalysis(
        lane_id=lane_id,
        pitch=pitch,
        pitch_name=pitch_name,
        label=label,
        onsets=positions,
        count=len(positions),
        intervals=intervals,
        interval_mean=interval_mean,
        interval_cv=interval_cv,
        cycle=cycle,
        timing=timing,
        velocity=velocity,
        hits_per_bar=hits,
    )
    observations = _lane_observations(
        lane_id, onsets, cycle, timing, velocity, config, beats_per_bar
    )
    return lane, observations


def _clip_observations(
    all_lane: LaneAnalysis,
    clip_length_inferred: bool,
) -> list[Observation]:
    """Наблюдения уровня клипа: EMPTY_BARS, TRAILING_EMPTY."""
    observations: list[Observation] = []
    hits = all_lane.hits_per_bar

    last_with_onset = -1
    for i, h in enumerate(hits):
        if h > 0:
            last_with_onset = i

    empty_bars = [i + 1 for i in range(last_with_onset) if hits[i] == 0]
    if empty_bars:
        observations.append(
            Observation(
                code="EMPTY_BARS",
                lane_id=None,
                value={"bars": empty_bars},
                confidence=1.0,
                text=f"empty bar(s) inside the clip: {', '.join(map(str, empty_bars))}",
            )
        )

    trailing = len(hits) - 1 - last_with_onset
    if not clip_length_inferred and trailing > 0:
        observations.append(
            Observation(
                code="TRAILING_EMPTY",
                lane_id=None,
                value={"bars": trailing},
                confidence=1.0,
                text=f"clip ends with {trailing} empty bar(s) after the last onset",
            )
        )

    return observations


def run_deterministic_rhythm_analysis(
    notes: list[Note],
    beats_per_bar: int,
    *,
    clip_length_beats: float | None = None,
    material: Literal["percussion", "pitched", "auto"] = "auto",
    lane_names: dict[int, str] | None = None,
    config: RhythmConfig | None = None,
) -> DeterministicRhythmAnalysis:
    """Единая точка входа детерминированного ритмического анализа.

    Args:
        notes: те же ``api_layer.models.Note``, что и в гармонии. Позиции
            переводятся в доли через ``chord_grouping.parse_start_to_beats``,
            MIDI-номера — через ``harmony_pipeline.pitch_to_midi`` (Ableton, C3=60).
        beats_per_bar: долей в такте (compound-размеры — по числителю).
        clip_length_beats: длина клипа в долях; если не задана — выводится из
            последнего онсета с округлением вверх до границы такта.
        material: тип материала; ``auto`` — по эвристике из раздела 3.2.
        lane_names: человекочитаемые имена лейнов {midi_pitch: label}.
        config: пороги; по умолчанию ``RhythmConfig()``.

    Raises:
        ValueError: если ``notes`` пуст.
    """
    if not notes:
        raise ValueError("No notes to analyze")

    config = config or RhythmConfig()

    onsets = _build_onsets(notes, beats_per_bar)
    if not onsets:
        raise ValueError("No valid pitches extracted from notes")

    clip_length_beats, clip_length_inferred, num_bars = _resolve_clip_length(
        onsets, beats_per_bar, clip_length_beats
    )

    routing = _compute_routing(onsets, config, material)

    lanes: list[LaneAnalysis] = []
    observations: list[Observation] = []

    all_lane, all_obs = _analyze_lane(
        "all", onsets, None, None, None, beats_per_bar, num_bars, config
    )
    lanes.append(all_lane)
    observations.extend(all_obs)

    if routing.material == "percussion":
        for pitch in sorted({p for _, p, _ in onsets}):
            lane_onsets = [o for o in onsets if o[1] == pitch]
            label = lane_names.get(pitch) if lane_names else None
            lane, lane_obs = _analyze_lane(
                str(pitch),
                lane_onsets,
                pitch,
                midi_to_ableton_pitch(pitch),
                label,
                beats_per_bar,
                num_bars,
                config,
            )
            lanes.append(lane)
            observations.extend(lane_obs)

    observations.extend(_clip_observations(all_lane, clip_length_inferred))

    return DeterministicRhythmAnalysis(
        beats_per_bar=beats_per_bar,
        clip_length_beats=clip_length_beats,
        clip_length_inferred=clip_length_inferred,
        routing=routing,
        lanes=lanes,
        observations=observations,
    )
