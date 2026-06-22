"""Детерминированная функциональная разметка аккордов через music21.

Единственная точка определения тональности клипа — ``detect_clip_key``.
Оркестратор ``analyze_functional_harmony`` — единственный вход для полного анализа.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from music21 import chord, key, note, roman, stream

logger = logging.getLogger(__name__)

# v1-эвристика tonal mode — грубая, легко уточняемая
AMBIGUOUS_CONFIDENCE_THRESHOLD = 0.65
AMBIGUOUS_GAP_THRESHOLD = 0.08
MIN_CHORDS_FOR_MODE = 2

_PC_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# iii and vi are functionally ambiguous — still mapped to T per spec.
_TONIC = frozenset({"I", "i", "iii", "III", "vi", "VI"})
_SUBDOMINANT = frozenset({"ii", "ii°", "iio", "IV", "iv"})
_DOMINANT = frozenset({"V", "V7", "vii°", "viio", "vii"})


@dataclass(frozen=True)
class KeyAnalysis:
    """Результат определения глобальной тональности клипа."""

    key: str
    tonic: str
    mode: str
    key_confidence: float
    alternate_gap: float
    m21_key: key.Key = field(repr=False)


@dataclass(frozen=True)
class TonalModeResult:
    """Результат детектора functional / modal / ambiguous (v1-эвристика)."""

    mode: Literal["functional", "modal", "ambiguous"]
    reason: str
    confidence: float


@dataclass
class LabeledChord:
    """Аккордовое событие с гармонической разметкой."""

    raw_pos: float
    nominal_pos: float
    is_possible_anticipation: bool
    time: str
    pitches: list[int]
    roman_numeral: str | None = None
    scale_degree: int | None = None
    quality: str | None = None
    inversion: int | None = None
    function: str | None = None
    is_diatonic: bool = False
    is_incomplete: bool = False
    pitch_class: str | None = None


@dataclass(frozen=True)
class FunctionalHarmonyResult:
    """Полный результат детерминированного анализа."""

    key_analysis: KeyAnalysis
    tonal_mode: TonalModeResult
    labeled_chords: list[LabeledChord]
    scale_notes: list[str]
    chords: list[str]


def detect_clip_key(pitches: list[int]) -> KeyAnalysis:
    """Единственный детектор тональности клипа (music21 Krumhansl-Schmuckler).

    TODO: вес нот по duration.
    """
    if not pitches:
        raise ValueError("Cannot detect key from empty pitch list")

    s = stream.Stream()
    for midi in pitches:
        s.append(note.Note(midi))

    k = s.analyze("key")
    confidence = float(k.correlationCoefficient or 0.0)
    alternate_gap = confidence
    if k.alternateInterpretations:
        second = float(k.alternateInterpretations[0].correlationCoefficient or 0.0)
        alternate_gap = confidence - second

    tonic_name = _format_pitch_name(k.tonic)
    mode = k.mode or "major"
    return KeyAnalysis(
        key=f"{tonic_name} {mode}",
        tonic=tonic_name,
        mode=mode,
        key_confidence=confidence,
        alternate_gap=alternate_gap,
        m21_key=k,
    )


def label_chord(
    pitches: list[int],
    key_analysis: KeyAnalysis,
    *,
    raw_pos: float = 0.0,
    nominal_pos: float = 0.0,
    is_possible_anticipation: bool = False,
    time: str = "1|1",
) -> LabeledChord:
    """Разметка одного аккордового события. Никогда не бросает исключение."""
    result = LabeledChord(
        raw_pos=raw_pos,
        nominal_pos=nominal_pos,
        is_possible_anticipation=is_possible_anticipation,
        time=time,
        pitches=sorted(pitches),
        function=None,
    )

    unique_pcs = sorted({p % 12 for p in pitches})
    if not unique_pcs:
        result.is_incomplete = True
        result.quality = "unclassified"
        return result

    if len(unique_pcs) == 1:
        result.pitch_class = _PC_NAMES[unique_pcs[0]]
        result.is_incomplete = True
        return result

    scale_pcs = _scale_pitch_classes(key_analysis.m21_key)

    if len(unique_pcs) == 2:
        result.is_incomplete = True
        if _is_power_chord(pitches):
            result.quality = "ambiguous"
            _apply_roman_from_pitches(result, pitches, key_analysis)
        else:
            result.quality = "unclassified"
            _apply_roman_from_pitches(result, pitches, key_analysis)
        result.is_diatonic = all(pc in scale_pcs for pc in unique_pcs)
        return result

    if len(unique_pcs) < 3:
        result.is_incomplete = True
        result.quality = "unclassified"
        return result

    try:
        ch = chord.Chord([note.Note(m) for m in sorted(set(pitches))])
        rn = roman.romanNumeralFromChord(ch, key_analysis.m21_key)
        result.roman_numeral = rn.figure
        result.scale_degree = rn.scaleDegree
        result.quality = rn.quality
        result.inversion = rn.inversion()
        result.is_diatonic = _chord_is_diatonic(unique_pcs, scale_pcs)
    except Exception:
        logger.debug("romanNumeralFromChord failed for pitches %s", pitches, exc_info=True)
        result.is_incomplete = True
        result.quality = "unclassified"
        result.is_diatonic = all(pc in scale_pcs for pc in unique_pcs)

    return result


def detect_tonal_mode(
    key_analysis: KeyAnalysis,
    chords: list[LabeledChord],
) -> TonalModeResult:
    """v1-эвристика: functional / modal / ambiguous."""
    if key_analysis.key_confidence < AMBIGUOUS_CONFIDENCE_THRESHOLD:
        return TonalModeResult(
            mode="ambiguous",
            reason=(
                f"low key confidence ({key_analysis.key_confidence:.2f} "
                f"< {AMBIGUOUS_CONFIDENCE_THRESHOLD})"
            ),
            confidence=key_analysis.key_confidence,
        )

    if key_analysis.alternate_gap < AMBIGUOUS_GAP_THRESHOLD:
        return TonalModeResult(
            mode="ambiguous",
            reason=(
                f"small gap to alternate key ({key_analysis.alternate_gap:.2f} "
                f"< {AMBIGUOUS_GAP_THRESHOLD})"
            ),
            confidence=key_analysis.key_confidence,
        )

    labeled = [c for c in chords if c.roman_numeral and not c.is_incomplete]
    if len(labeled) < MIN_CHORDS_FOR_MODE:
        return TonalModeResult(
            mode="ambiguous",
            reason=f"few classifiable chords ({len(labeled)} < {MIN_CHORDS_FOR_MODE})",
            confidence=key_analysis.key_confidence,
        )

    figures = [_normalize_figure(c.roman_numeral) for c in labeled if c.roman_numeral]
    has_dominant = any(fig in _DOMINANT for fig in figures)
    has_modal_marker = _has_modal_markers(key_analysis, figures)

    if has_dominant and _has_dominant_resolution(labeled):
        return TonalModeResult(
            mode="functional",
            reason="dominant chord present with resolution to tonic",
            confidence=min(1.0, key_analysis.key_confidence + 0.1),
        )

    if has_dominant:
        return TonalModeResult(
            mode="functional",
            reason="dominant chord (V or vii°) present",
            confidence=key_analysis.key_confidence,
        )

    if has_modal_marker or not has_dominant:
        return TonalModeResult(
            mode="modal",
            reason="no dominant; diatonic/modal harmonic profile",
            confidence=key_analysis.key_confidence,
        )

    return TonalModeResult(
        mode="ambiguous",
        reason="insufficient functional/modal signals",
        confidence=key_analysis.key_confidence,
    )


def assign_harmonic_functions(chords: list[LabeledChord]) -> None:
    """Чистый маппер figure → T/S/D. Без проверки tonal_mode — гейт в оркестраторе."""
    for ch in chords:
        if ch.is_incomplete or not ch.is_diatonic or not ch.roman_numeral:
            ch.function = None
            continue

        fig = _normalize_figure(ch.roman_numeral)
        if fig in _TONIC:
            ch.function = "T"
        elif fig in _SUBDOMINANT:
            ch.function = "S"
        elif fig in _DOMINANT:
            ch.function = "D"
        else:
            ch.function = None


def analyze_functional_harmony(
    events: list[dict[str, Any]],
    all_pitches: list[int],
) -> FunctionalHarmonyResult:
    """Единая точка входа: key → label → mode → (optional) T-S-D."""
    key_analysis = detect_clip_key(all_pitches)

    labeled: list[LabeledChord] = []
    for event in events:
        labeled.append(
            label_chord(
                event["pitches"],
                key_analysis,
                raw_pos=event.get("raw_pos", 0.0),
                nominal_pos=event.get("nominal_pos", 0.0),
                is_possible_anticipation=event.get("is_possible_anticipation", False),
                time=event.get("time", "1|1"),
            )
        )

    tonal_mode = detect_tonal_mode(key_analysis, labeled)

    if tonal_mode.mode == "functional":
        assign_harmonic_functions(labeled)

    scale_notes = [_format_pitch_name(p) for p in key_analysis.m21_key.getScale().pitches]
    chord_strings = [_format_chord_string(ch) for ch in labeled]

    return FunctionalHarmonyResult(
        key_analysis=key_analysis,
        tonal_mode=tonal_mode,
        labeled_chords=labeled,
        scale_notes=scale_notes,
        chords=chord_strings,
    )


def labeled_chord_to_dict(ch: LabeledChord) -> dict[str, Any]:
    """Сериализация LabeledChord для chord_events."""
    return {
        "time": ch.time,
        "raw_pos": ch.raw_pos,
        "nominal_pos": ch.nominal_pos,
        "pitches": ch.pitches,
        "is_possible_anticipation": ch.is_possible_anticipation,
        "roman_numeral": ch.roman_numeral,
        "scale_degree": ch.scale_degree,
        "quality": ch.quality,
        "inversion": ch.inversion,
        "function": ch.function,
        "is_diatonic": ch.is_diatonic,
        "is_incomplete": ch.is_incomplete,
        "pitch_class": ch.pitch_class,
    }


def _apply_roman_from_pitches(
    result: LabeledChord,
    pitches: list[int],
    key_analysis: KeyAnalysis,
) -> None:
    """Best-effort roman numeral from bass/root; never raises."""
    try:
        bass_pc = min(pitches) % 12
        roman_fig, degree = _roman_from_pitch_class(bass_pc, key_analysis.m21_key)
        if roman_fig:
            result.roman_numeral = roman_fig
            result.scale_degree = degree
            result.inversion = 0
            if result.quality is None:
                result.quality = "ambiguous"
            return
        ch = chord.Chord([note.Note(min(pitches))])
        rn = roman.romanNumeralFromChord(ch, key_analysis.m21_key)
        result.roman_numeral = rn.figure
        result.scale_degree = rn.scaleDegree
        result.inversion = 0
        if result.quality is None:
            result.quality = rn.quality
    except Exception:
        logger.debug("root-only roman failed for pitches %s", pitches, exc_info=True)
        result.roman_numeral = None


def _roman_from_pitch_class(bass_pc: int, k: key.Key) -> tuple[str | None, int | None]:
    """Map bass pitch class to diatonic roman numeral in key."""
    scale_pcs = [(p.pitchClass, i + 1) for i, p in enumerate(k.getScale().pitches[:7])]
    for pc, degree in scale_pcs:
        if pc == bass_pc:
            if k.mode == "major":
                figures = ("I", "ii", "iii", "IV", "V", "vi", "vii°")
            else:
                figures = ("i", "ii°", "III", "iv", "v", "VI", "VII")
            return figures[degree - 1], degree

    try:
        ch = chord.Chord([note.Note(bass_pc)])
        rn = roman.romanNumeralFromChord(ch, k)
        return rn.figure, rn.scaleDegree
    except Exception:
        return None, None


def _is_power_chord(pitches: list[int]) -> bool:
    pcs = sorted({p % 12 for p in pitches})
    if len(pcs) != 2:
        return False
    bass_pc = min(pitches) % 12
    other_pc = pcs[1] if pcs[0] == bass_pc else pcs[0]
    interval = (other_pc - bass_pc) % 12
    if interval not in (5, 7):
        return False
    third_major = (bass_pc + 4) % 12
    third_minor = (bass_pc + 3) % 12
    return third_major not in pcs and third_minor not in pcs


def _scale_pitch_classes(k: key.Key) -> set[int]:
    return {p.pitchClass for p in k.getScale().pitches}


def _chord_is_diatonic(unique_pcs: list[int], scale_pcs: set[int]) -> bool:
    return all(pc in scale_pcs for pc in unique_pcs)


def _normalize_figure(figure: str) -> str:
    """Strip inversion figures; keep quality markers like °."""
    base = re.sub(r"\d+$", "", figure)
    base = base.replace("o", "°")
    return base


def _has_modal_markers(key_analysis: KeyAnalysis, figures: list[str]) -> bool:
    if "bVII" in figures or "bVII7" in figures:
        return True
    if key_analysis.mode == "minor" and "IV" in figures:
        return True
    return False


def _has_dominant_resolution(chords: list[LabeledChord]) -> bool:
    tonic_figs = {"I", "i"}
    dominant_figs = _DOMINANT
    for i, ch in enumerate(chords):
        if not ch.roman_numeral:
            continue
        fig = _normalize_figure(ch.roman_numeral)
        if fig not in dominant_figs:
            continue
        for next_ch in chords[i + 1 : i + 3]:
            if not next_ch.roman_numeral:
                continue
            next_fig = _normalize_figure(next_ch.roman_numeral)
            if next_fig in tonic_figs:
                return True
    return False


def _format_pitch_name(p: Any) -> str:
    name = p.name
    if "-" in name:
        return name.replace("-", "b")
    return name


def _format_chord_string(ch: LabeledChord) -> str:
    if ch.pitch_class and ch.is_incomplete and not ch.roman_numeral:
        return f"{ch.pitch_class} @ {ch.time}"
    roman_part = ch.roman_numeral or "?"
    quality_part = f" ({ch.quality})" if ch.quality else ""
    return f"{roman_part}{quality_part} @ {ch.time}"
