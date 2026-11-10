#!/usr/bin/env python3
"""Оффлайн-харнесс: загрузка .mid и детерминированный анализ (гармония / ритм).

Запуск из каталога agents:
    poetry run python scripts/analyze_midi_file.py FILE.mid [--track N] [--with-llm] [--json]
        [--analysis {harmony,rhythm,both}] [--clip-bars N] [--material ...] [--lane-names PATH]

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
from agents.midi_utils import midi_to_ableton_pitch
from agents.rhythm_analyzer import (
    DeterministicRhythmAnalysis,
    run_deterministic_rhythm_analysis,
)

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
    tempo_bpm: float | None = None
    track_name: str | None = None


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


def _extract_tempo_and_track_name(
    mid: mido.MidiFile,
) -> tuple[float | None, str | None]:
    """Первое set_tempo (в BPM) и первый непустой track_name по всем трекам."""
    tempo_bpm: float | None = None
    track_name: str | None = None
    for track in mid.tracks:
        for msg in track:
            if tempo_bpm is None and msg.type == "set_tempo":
                tempo_bpm = mido.tempo2bpm(msg.tempo)
            if track_name is None and msg.type == "track_name" and msg.name:
                track_name = msg.name
        if tempo_bpm is not None and track_name is not None:
            break
    return tempo_bpm, track_name


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
    skip_drum_channel: bool | None = None,
) -> list[tuple[float, int, int, int]]:
    """Сырые note-on: (offset_quarters, midi_pitch, velocity, channel)."""
    ticks_per_beat = mid.ticks_per_beat
    if skip_drum_channel is None:
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
    skip_drum_channel: bool | None = None,
) -> MidiLoadResult:
    """Загрузить MIDI через mido и конвертировать ноты во внутренний формат Note.

    ``skip_drum_channel=None`` сохраняет текущее поведение (ударный канал
    пропускается при слиянии всех партий); ``False`` — ударные не выкидывать.
    """
    mid = mido.MidiFile(str(path))
    beats_per_bar, ts_str, warnings = _extract_time_signature_mido(mid)
    tempo_bpm, track_name = _extract_tempo_and_track_name(mid)
    raw_events = _load_raw_note_ons_mido(
        mid, track=track, skip_drum_channel=skip_drum_channel
    )

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
        tempo_bpm=tempo_bpm,
        track_name=track_name,
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


def _load_lane_names(path: Path) -> dict[int, str]:
    """Читает JSON-маппинг лейнов ``{"36": "bass chop"}`` → ``{36: "bass chop"}``."""
    if not path.is_file():
        raise ValueError(f"Lane names file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in lane names file {path}: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError(
            f"Lane names file {path} must contain a JSON object, e.g. "
            '{"36": "bass chop"}'
        )

    lane_names: dict[int, str] = {}
    for key, value in raw.items():
        try:
            pitch = int(key)
        except (TypeError, ValueError):
            raise ValueError(
                f"Invalid pitch key {key!r} in lane names file {path}: "
                "keys must be MIDI note numbers"
            ) from None
        if not isinstance(value, str):
            raise ValueError(
                f"Invalid label for pitch {key!r} in lane names file {path}: "
                "values must be strings"
            )
        lane_names[pitch] = value
    return lane_names


def _print_rhythm_report(
    path: Path,
    load_result: MidiLoadResult,
    result: DeterministicRhythmAnalysis,
) -> None:
    print("=" * 72)
    print("RHYTHM ANALYSIS (offline MIDI)")
    print("=" * 72)
    print(f"File:           {path}")
    if load_result.tempo_bpm is not None:
        print(f"Tempo:          {load_result.tempo_bpm:.1f} BPM")
    else:
        print("Tempo:          unknown (no tempo meta)")
    if load_result.track_name:
        print(f"Track:          {load_result.track_name}")
    print(f"Time signature: {load_result.time_signature_str}")
    num_bars = result.clip_length_beats / result.beats_per_bar
    print(
        f"Clip length:    {result.clip_length_beats:g} beats "
        f"({num_bars:g} bars, inferred={result.clip_length_inferred})"
    )
    routing = result.routing
    print(
        f"Routing:        {routing.material} ({routing.source}; "
        f"monophonic={routing.monophonic_ratio:.3f}, "
        f"distinct_pitches={routing.distinct_pitches}, "
        f"chromatic_neighbors={routing.chromatic_neighbor_ratio:.3f})"
    )
    print()

    header = (
        f"{'lane':>4}  {'name':<5}  {'label':<14}  {'count':>5}  "
        f"{'int_mean':>8}  {'cv':>6}  {'dev_mean':>8}  {'dev_std':>8}  "
        f"{'vel(min-max)':>12}"
    )
    print(header)
    print("-" * len(header))
    for lane in result.lanes:
        name = lane.pitch_name or "—"
        label = lane.label or "—"
        int_mean_str = f"{lane.interval_mean:.3f}" if lane.interval_mean is not None else "—"
        cv_str = f"{lane.interval_cv:.3f}" if lane.interval_cv is not None else "—"
        print(
            f"{lane.lane_id:>4}  {name:<5}  {label:<14}  {lane.count:>5}  "
            f"{int_mean_str:>8}  {cv_str:>6}  {lane.timing.dev_mean:>+8.3f}  "
            f"{lane.timing.dev_std:>8.3f}  "
            f"{lane.velocity.min}-{lane.velocity.max:>11}"
        )

    print()
    print("Hits per bar:")
    for lane in result.lanes:
        print(f"  {lane.lane_id:>4}: {lane.hits_per_bar}")

    print()
    print("Observations:")
    for obs in result.observations:
        lane = f"lane {obs.lane_id}" if obs.lane_id else "clip"
        print(
            f"  {obs.code:<16} ({lane}, confidence={obs.confidence:.2f}): {obs.text}"
        )
    print("=" * 72)


def analyze_midi_file(
    path: Path,
    *,
    track: int | None = None,
    with_llm: bool = False,
    emit_json: bool = False,
    analysis: str = "harmony",
    clip_bars: int | None = None,
    material: str = "auto",
    lane_names: dict[int, str] | None = None,
) -> tuple[DeterministicHarmonyAnalysis | DeterministicRhythmAnalysis, str | None]:
    """Полный прогон: загрузка → анализ (гармония и/или ритм).

    ``analysis``: "harmony" | "rhythm" | "both". В режиме "both" файл грузится
    дважды: гармония получает ноты как в режиме "harmony" (skip_drum_channel=None),
    ритм — с skip_drum_channel=False. ``with_llm`` допустим только в режиме "harmony".
    """
    if with_llm and analysis != "harmony":
        raise ValueError("--with-llm is only supported with --analysis harmony")

    harmony_load: MidiLoadResult | None = None
    rhythm_load: MidiLoadResult | None = None

    if analysis in ("harmony", "both"):
        harmony_load = load_midi_notes(path, track=track, skip_drum_channel=None)
    if analysis in ("rhythm", "both"):
        rhythm_load = load_midi_notes(path, track=track, skip_drum_channel=False)

    seen_warnings: set[str] = set()
    for load in (harmony_load, rhythm_load):
        if load is None:
            continue
        for warning in load.warnings:
            if warning not in seen_warnings:
                print(f"Warning: {warning}", file=sys.stderr)
                seen_warnings.add(warning)

    harmony_result: DeterministicHarmonyAnalysis | None = None
    rhythm_result: DeterministicRhythmAnalysis | None = None
    reasoning: str | None = None

    if harmony_load is not None:
        harmony_result = run_deterministic_harmony_analysis(
            harmony_load.notes,
            harmony_load.beats_per_bar,
        )
        if with_llm:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                print(
                    "ERROR: --with-llm requires ANTHROPIC_API_KEY environment variable.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print("Calling Claude API for reasoning...", file=sys.stderr)
            reasoning = fetch_claude_harmony_reasoning(harmony_result, api_key)
            print()
            print("REASONING")
            print("-" * 40)
            print(reasoning)
            print()
        _print_report(path, harmony_load, harmony_result)

    if rhythm_load is not None:
        clip_length_beats = None
        if clip_bars is not None:
            clip_length_beats = clip_bars * rhythm_load.beats_per_bar
        rhythm_result = run_deterministic_rhythm_analysis(
            rhythm_load.notes,
            rhythm_load.beats_per_bar,
            clip_length_beats=clip_length_beats,
            material=material,  # type: ignore[arg-type]
            lane_names=lane_names,
        )
        _print_rhythm_report(path, rhythm_load, rhythm_result)

    if emit_json:
        if analysis == "rhythm":
            assert rhythm_result is not None
            payload: dict[str, Any] = rhythm_result.model_dump()
        elif analysis == "both":
            assert harmony_result is not None and rhythm_result is not None
            payload = {
                "harmony": harmony_result.model_dump(),
                "rhythm": rhythm_result.model_dump(),
            }
        else:
            assert harmony_result is not None
            payload = harmony_result.model_dump()
            if reasoning is not None:
                payload["reasoning"] = reasoning
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    primary = rhythm_result if analysis == "rhythm" else harmony_result
    assert primary is not None
    return primary, reasoning


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Offline MIDI analysis (deterministic pipeline: harmony/rhythm)."
    )
    parser.add_argument("midi_file", type=Path, help="Path to .mid file")
    parser.add_argument(
        "--track",
        type=int,
        default=None,
        help="Restrict to one note-bearing track by 0-based index (default: merge all)",
    )
    parser.add_argument(
        "--analysis",
        choices=["harmony", "rhythm", "both"],
        default="harmony",
        help="Which deterministic analysis to run (default: harmony)",
    )
    parser.add_argument(
        "--clip-bars",
        type=int,
        default=None,
        help="Clip length in bars for rhythm analysis (clip_length_beats = N * beats_per_bar)",
    )
    parser.add_argument(
        "--material",
        choices=["auto", "percussion", "pitched"],
        default="auto",
        help="Material routing for rhythm analysis (default: auto)",
    )
    parser.add_argument(
        "--lane-names",
        type=Path,
        default=None,
        help='JSON file mapping MIDI pitches to labels, e.g. {"36": "bass chop"}',
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Run Claude reasoning on top of deterministic harmony result (requires API key)",
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

    if args.clip_bars is not None and args.clip_bars <= 0:
        print("ERROR: --clip-bars must be a positive integer", file=sys.stderr)
        sys.exit(1)

    if args.with_llm and args.analysis != "harmony":
        print(
            "ERROR: --with-llm is only supported with --analysis harmony",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        lane_names = None
        if args.lane_names is not None:
            lane_names = _load_lane_names(args.lane_names)

        analyze_midi_file(
            args.midi_file,
            track=args.track,
            with_llm=args.with_llm,
            emit_json=args.json,
            analysis=args.analysis,
            clip_bars=args.clip_bars,
            material=args.material,
            lane_names=lane_names,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
