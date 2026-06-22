"""Детерминированный конвейер гармонического анализа (группировка + разметка)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from anthropic import Anthropic
from pydantic import BaseModel

from api_layer.models import Note

from .chord_grouping import ChordGroupingConfig, beats_to_start, group_notes_into_chords
from .functional_labeling import (
    FunctionalHarmonyResult,
    analyze_functional_harmony,
    labeled_chord_to_dict,
)

logger = logging.getLogger(__name__)

# MIDI: C4=60, A4=69. Ноты в октаве: C=0, C#/Db=1, D=2, ..., B=11
_PITCH_TO_SEMITONE: dict[str, int] = {
    "C": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
}

_SKILL_PATH = Path(__file__).parent / "skills" / "harmony_theory.md"


class DeterministicHarmonyAnalysis(BaseModel):
    """Результат детерминированного гармонического анализа (без LLM reasoning)."""

    key: str
    key_confidence: float
    key_alternate_gap: float
    confidence: float  # alias key_confidence для обратной совместимости
    tonal_mode: Literal["functional", "modal", "ambiguous"]
    tonal_mode_reason: str
    chords: list[str]
    scale_notes: list[str]
    raw_notes: list[dict[str, Any]]
    # LabeledChord сериализован через labeled_chord_to_dict — dict для JSON/workflow state.
    chord_events: list[dict[str, Any]]


def pitch_to_midi(pitch: str) -> int:
    """Конвертирует строку pitch (например 'C3', 'F#4', 'Bb2') в MIDI номер.

    Ableton convention: C3 = MIDI 60 (not scientific C4=60).
    """
    pitch = pitch.strip().upper()
    if not pitch:
        raise ValueError("Empty pitch string")
    match = re.match(r"^([A-G][#B]?)(-?\d+)$", pitch)
    if not match:
        raise ValueError(f"Invalid pitch format: {pitch}")
    note_part, octave_part = match.group(1), match.group(2)
    if len(note_part) == 2 and note_part[1] == "B":
        note_part = f"{note_part[0]}B"
    if note_part not in _PITCH_TO_SEMITONE:
        raise ValueError(f"Unknown note name: {note_part}")
    octave = int(octave_part)
    semitone = _PITCH_TO_SEMITONE[note_part]
    return (octave + 2) * 12 + semitone


def extract_chord_events(
    notes: list[Note],
    beats_per_bar: int,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Группировка нот и извлечение MIDI pitches."""
    grouping_config = ChordGroupingConfig(beats_per_bar=beats_per_bar)
    grouped_events = group_notes_into_chords(notes, grouping_config)

    chord_events: list[dict[str, Any]] = []
    all_pitches: list[int] = []

    for event in grouped_events:
        midi_pitches: list[int] = []
        for note_obj in event.notes:
            try:
                midi_pitches.append(pitch_to_midi(note_obj.pitch))
            except ValueError as e:
                logger.warning("skip invalid pitch %s: %s", note_obj.pitch, e)
        if not midi_pitches:
            continue

        all_pitches.extend(midi_pitches)
        time_str = beats_to_start(event.nominal_pos, grouping_config.beats_per_bar)
        chord_events.append(
            {
                "time": time_str,
                "raw_pos": event.raw_pos,
                "nominal_pos": event.nominal_pos,
                "pitches": sorted(midi_pitches),
                "is_possible_anticipation": event.is_possible_anticipation,
                "notes": [
                    {
                        "pitch": note_obj.pitch,
                        "start": note_obj.start,
                        "velocity": note_obj.velocity,
                    }
                    for note_obj in event.notes
                ],
            }
        )

    return chord_events, all_pitches


def _notes_to_raw_dicts(notes: list[Note]) -> list[dict[str, Any]]:
    return [
        {
            "pitch": note_obj.pitch,
            "start": note_obj.start,
            "duration": note_obj.duration,
            "velocity": note_obj.velocity,
        }
        for note_obj in notes
    ]


def _enrich_chord_events(
    raw_events: list[dict[str, Any]],
    harmony: FunctionalHarmonyResult,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for raw, labeled in zip(raw_events, harmony.labeled_chords, strict=True):
        event_dict = labeled_chord_to_dict(labeled)
        event_dict["notes"] = raw.get("notes", [])
        enriched.append(event_dict)
    return enriched


def run_deterministic_harmony_analysis(
    notes: list[Note],
    beats_per_bar: int,
) -> DeterministicHarmonyAnalysis:
    """Единая точка входа: группировка + функциональная разметка."""
    if not notes:
        raise ValueError("No notes to analyze")

    raw_events, all_pitches = extract_chord_events(notes, beats_per_bar)
    if not raw_events:
        raise ValueError("No valid pitches extracted from notes")

    harmony = analyze_functional_harmony(raw_events, all_pitches)
    enriched_events = _enrich_chord_events(raw_events, harmony)
    ka = harmony.key_analysis
    tm = harmony.tonal_mode

    return DeterministicHarmonyAnalysis(
        key=ka.key,
        key_confidence=ka.key_confidence,
        key_alternate_gap=ka.alternate_gap,
        confidence=ka.key_confidence,
        tonal_mode=tm.mode,
        tonal_mode_reason=tm.reason,
        chords=harmony.chords,
        scale_notes=harmony.scale_notes,
        raw_notes=_notes_to_raw_dicts(notes),
        chord_events=enriched_events,
    )


def _build_claude_user_message(
    result: DeterministicHarmonyAnalysis,
    skill_content: str,
) -> str:
    user_message = (
        f"{skill_content}\n\n"
        "The harmonic analysis below was computed deterministically. "
        "Do NOT recompute key, roman numerals, or T-S-D functions.\n"
    )
    if result.tonal_mode in ("modal", "ambiguous"):
        user_message += (
            "tonal_mode is \""
            f"{result.tonal_mode}\" — do NOT interpret harmonic functions; "
            "function fields are intentionally null.\n"
        )
    user_message += (
        f"\nKey: {result.key} "
        f"(confidence={result.key_confidence:.3f}, "
        f"alternate_gap={result.key_alternate_gap:.3f})\n"
        f"Tonal mode: {result.tonal_mode} — {result.tonal_mode_reason}\n"
        f"Scale notes: {', '.join(result.scale_notes)}\n\n"
        "Labeled chord progression:\n"
    )
    for ch in result.chord_events:
        line = (
            f"  At {ch['time']}: pitches={ch['pitches']}, "
            f"roman={ch.get('roman_numeral')}, quality={ch.get('quality')}, "
            f"function={ch.get('function')}, is_diatonic={ch.get('is_diatonic')}, "
            f"is_incomplete={ch.get('is_incomplete')}"
        )
        if ch.get("is_possible_anticipation"):
            line += " (possible anticipation)"
        user_message += line + "\n"

    user_message += (
        "\nProvide a concise musical interpretation of this progression "
        "(voice-leading, character, suggestions). "
        "Return a single JSON object: {\"reasoning\": \"...\"} only."
    )
    return user_message


def fetch_claude_harmony_reasoning(
    result: DeterministicHarmonyAnalysis,
    api_key: str,
    *,
    skill_content: str | None = None,
) -> str:
    """Claude — только reasoning поверх готовой детерминированной разметки."""
    if skill_content is None:
        skill_content = _SKILL_PATH.read_text(encoding="utf-8")

    user_message = _build_claude_user_message(result, skill_content)

    anthropic_client = Anthropic(api_key=api_key)
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        temperature=0,
        system=(
            "You are a music theory expert. Interpret pre-computed harmonic analysis. "
            "Never override the provided key, roman numerals, or functions."
        ),
        messages=[{"role": "user", "content": user_message}],
    )

    if not response.content or not hasattr(response.content[0], "text"):
        raise ValueError("Empty or invalid response from Claude API")
    text = response.content[0].text

    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if json_match:
        text = json_match.group(1).strip()
    else:
        text = text.strip()

    parsed = json.loads(text)
    if "reasoning" not in parsed:
        raise ValueError("Claude response missing key: reasoning")
    return parsed["reasoning"]
