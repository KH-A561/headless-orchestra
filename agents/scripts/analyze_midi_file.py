#!/usr/bin/env python3
"""Оффлайн-харнесс: загрузка .mid и детерминированный гармонический анализ.

Запуск из каталога agents:
    poetry run python scripts/analyze_midi_file.py FILE.mid [--track N] [--with-llm] [--json]

Gotchas:
- Note-on читаются через mido (сырые тики), НЕ converter.parse — music21 дублирует на сетку.
- PPQ: mid.ticks_per_beat; TS: первый MetaMessage time_signature.
- note_on с velocity==0 — note-off; только velocity > 0.
- Ableton C3 = MIDI 60; octave = midi // 12 - 2.
- Первый time signature / tempo; смены не учитываются (v1).
- При слиянии всех партий channel 9 (GM drums) пропускается.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mido

from api_layer.models import Note

from agents.chord_grouping import beats_to_start
from agents.harmony_pipeline import (
    DeterministicHarmonyAnalysis,
    fetch_claude_harmony_reasoning,
    run_deterministic_harmony_analysis,
)

# Sharp-default pitch-class names (Ableton convention).
_PC_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# GM drum channel (1-based channel 10 → 0-based index 9).
_DRUM_CHANNEL = 9

_DEFAULT_DURATION = "1:0"


@dataclass(frozen=True)
class MidiLoadResult:
    """Результат загрузки MIDI-файла."""

    notes: list[Note]
    beats_per_bar: int
    time_signature_str: str
    warnings: list[str]


def midi_to_ableton_pitch(midi: int) -> str:
    """MIDI номер → строка pitch в конвенции Ableton (C3 = MIDI 60).

    Ableton C3 = music21 C4 = MIDI 60.
    """
    pc = midi % 12
    octave = midi // 12 - 2
    return f"{_PC_NAMES[pc]}{octave}"


def _extract_time_signature_mido(mid: mido.MidiFile) -> tuple[int, str, list[str]]:
    """Первый time_signature meta по всем трекам."""
    warnings: list[str] = []
    beats_per_bar = 4
    ts_str = "?/4"
    ts_count = 0

    for track in mid.tracks:
        for msg in track:
            if msg.type != "time_signature":
                continue
            ts_count += 1
            if ts_count == 1:
                beats_per_bar = msg.numerator
                ts_str = f"{msg.numerator}/{msg.denominator}"
            elif ts_count == 2:
                warnings.append(
                    "Multiple time signatures in file; using first only "
                    f"({ts_str}). Tempo/size changes are not supported in v1."
                )
                return beats_per_bar, ts_str, warnings

    return beats_per_bar, ts_str, warnings


def _track_has_note_on(track: mido.MidiTrack) -> bool:
    for msg in track:
        if msg.type == "note_on" and msg.velocity > 0:
            return True
    return False


def _iter_track_note_ons(
    track: mido.MidiTrack,
    ticks_per_beat: int,
    *,
    skip_drum_channel: bool,
) -> list[tuple[float, int, int, int]]:
    """Собрать note-on из одного трека; время накапливается внутри трека."""
    events: list[tuple[float, int, int, int]] = []
    tick_pos = 0
    for msg in track:
        tick_pos += msg.time
        if msg.type != "note_on" or msg.velocity == 0:
            continue
        if skip_drum_channel and msg.channel == _DRUM_CHANNEL:
            continue
        offset_quarters = tick_pos / ticks_per_beat
        events.append((offset_quarters, msg.note, msg.velocity, msg.channel))
    return events


def _load_raw_note_ons_mido(
    mid: mido.MidiFile,
    *,
    track: int | None = None,
) -> list[tuple[float, int, int, int]]:
    """Сырые note-on: (offset_quarters, midi_pitch, velocity, channel)."""
    ticks_per_beat = mid.ticks_per_beat
    skip_drum_channel = track is None

    note_track_indices = [i for i, tr in enumerate(mid.tracks) if _track_has_note_on(tr)]
    if not note_track_indices:
        return []

    if track is not None:
        if track < 0 or track >= len(note_track_indices):
            raise ValueError(
                f"Track index {track} out of range "
                f"(file has {len(note_track_indices)} note-bearing track(s))"
            )
        selected = [note_track_indices[track]]
    else:
        selected = note_track_indices

    events: list[tuple[float, int, int, int]] = []
    for idx in selected:
        events.extend(
            _iter_track_note_ons(
                mid.tracks[idx],
                ticks_per_beat,
                skip_drum_channel=skip_drum_channel,
            )
        )
    events.sort(key=lambda item: item[0])
    return events


def load_midi_notes(
    path: Path,
    *,
    track: int | None = None,
) -> MidiLoadResult:
    """Загрузить MIDI через mido и конвертировать ноты во внутренний формат Note."""
    mid = mido.MidiFile(str(path))
    beats_per_bar, ts_str, warnings = _extract_time_signature_mido(mid)
    raw_events = _load_raw_note_ons_mido(mid, track=track)

    notes: list[Note] = []
    for offset, midi, velocity, _channel in raw_events:
        notes.append(
            Note(
                pitch=midi_to_ableton_pitch(midi),
                start=beats_to_start(offset, beats_per_bar),
                duration=_DEFAULT_DURATION,
                velocity=velocity,
            )
        )

    if not notes:
        raise ValueError(f"No notes found in {path}")

    return MidiLoadResult(
        notes=notes,
        beats_per_bar=beats_per_bar,
        time_signature_str=ts_str,
        warnings=warnings,
    )


def _format_flags(event: dict[str, Any]) -> str:
    flags: list[str] = []
    if event.get("is_possible_anticipation"):
        flags.append("ANTICIP")
    if event.get("is_incomplete"):
        flags.append("INCOMPL")
    if not event.get("is_diatonic", True):
        flags.append("OUT-OF-KEY")
    return ",".join(flags) if flags else "—"


def _print_report(
    path: Path,
    load_result: MidiLoadResult,
    result: DeterministicHarmonyAnalysis,
) -> None:
    print("=" * 72)
    print("HARMONY ANALYSIS (offline MIDI)")
    print("=" * 72)
    print(f"File:           {path}")
    print(f"Time signature: {load_result.time_signature_str}")
    print(f"Key:            {result.key} (confidence={result.key_confidence:.3f})")
    print(f"Tonal mode:     {result.tonal_mode} — {result.tonal_mode_reason}")
    print()

    header = f"{'nominal_pos':>12}  {'pitches':<20}  {'roman':<8}  {'quality':<12}  {'func':<4}  flags"
    print(header)
    print("-" * len(header))

    for event in result.chord_events:
        nominal = event.get("nominal_pos", 0.0)
        pitches = event.get("pitches", [])
        pitches_str = str(pitches)
        roman = event.get("roman_numeral") or "—"
        quality = event.get("quality") or "—"
        function = event.get("function") or "—"
        flags = _format_flags(event)
        print(
            f"{nominal:>12.2f}  {pitches_str:<20}  {roman:<8}  {quality:<12}  {function:<4}  {flags}"
        )

    print()
    total = len(result.chord_events)
    anticip = sum(1 for e in result.chord_events if e.get("is_possible_anticipation"))
    incomple = sum(1 for e in result.chord_events if e.get("is_incomplete"))
    out_of_key = sum(1 for e in result.chord_events if not e.get("is_diatonic", True))
    print(f"Summary: {total} chord event(s)")
    print(f"  ANTICIP:     {anticip}")
    print(f"  INCOMPL:     {incomple}")
    print(f"  OUT-OF-KEY:  {out_of_key}")
    print("=" * 72)


def analyze_midi_file(
    path: Path,
    *,
    track: int | None = None,
    with_llm: bool = False,
    emit_json: bool = False,
) -> tuple[DeterministicHarmonyAnalysis, str | None]:
    """Полный прогон: загрузка → анализ → опционально LLM reasoning."""
    load_result = load_midi_notes(path, track=track)

    for warning in load_result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    result = run_deterministic_harmony_analysis(
        load_result.notes,
        load_result.beats_per_bar,
    )

    reasoning: str | None = None
    if with_llm:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ERROR: --with-llm requires ANTHROPIC_API_KEY environment variable.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("Calling Claude API for reasoning...", file=sys.stderr)
        reasoning = fetch_claude_harmony_reasoning(result, api_key)
        print()
        print("REASONING")
        print("-" * 40)
        print(reasoning)
        print()

    _print_report(path, load_result, result)

    if emit_json:
        payload: dict[str, Any] = result.model_dump()
        if reasoning is not None:
            payload["reasoning"] = reasoning
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return result, reasoning


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Offline MIDI harmony analysis (deterministic pipeline)."
    )
    parser.add_argument("midi_file", type=Path, help="Path to .mid file")
    parser.add_argument(
        "--track",
        type=int,
        default=None,
        help="Restrict to one note-bearing track by 0-based index (default: merge all)",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Run Claude reasoning on top of deterministic result (requires API key)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also emit full result as JSON",
    )
    args = parser.parse_args(argv)

    if not args.midi_file.is_file():
        print(f"ERROR: File not found: {args.midi_file}", file=sys.stderr)
        sys.exit(1)

    try:
        analyze_midi_file(
            args.midi_file,
            track=args.track,
            with_llm=args.with_llm,
            emit_json=args.json,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
