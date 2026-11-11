"""Детерминированный конвейер гармонического анализа (группировка + разметка)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal, Sequence

from anthropic import Anthropic
from pydantic import BaseModel

from .chord_grouping import ChordGroupingConfig, beats_to_start, group_notes_into_chords
from .domain import NoteEvent
from .functional_labeling import (
    FunctionalHarmonyResult,
    analyze_functional_harmony,
    labeled_chord_to_dict,
)

logger = logging.getLogger(__name__)

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


def extract_chord_events(
    notes: Sequence[NoteEvent],
    beats_per_bar: int,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Группировка нот и извлечение MIDI pitches."""
    grouping_config = ChordGroupingConfig(beats_per_bar=beats_per_bar)
    grouped_events = group_notes_into_chords(notes, grouping_config)

    chord_events: list[dict[str, Any]] = []
    all_pitches: list[int] = []

    for event in grouped_events:
        midi_pitches = [note_obj.pitch for note_obj in event.notes]
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
                "notes": [note_obj.model_dump() for note_obj in event.notes],
            }
        )

    return chord_events, all_pitches


def _notes_to_raw_dicts(notes: Sequence[NoteEvent]) -> list[dict[str, Any]]:
    return [note_obj.model_dump() for note_obj in notes]


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
    notes: Sequence[NoteEvent],
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
