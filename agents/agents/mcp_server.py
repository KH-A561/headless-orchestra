"""MCP-сервер Headless Orchestra (read-only анализ клипов из живого Live).

Сервер читает данные из Live через мост ``mcp-server-ableton-live``, прогоняет
их через детерминированные пайплайны и возвращает компактные посчитанные факты.
Ноты через LLM-контекст не проходят.

Запуск: ``python -m agents.mcp_server`` или консольный скрипт ``ho-mcp``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .adapters.ableton import AbletonAdapter, parse_ref_id
from .domain import ClipData, WindowedClip, beats_per_bar, windowed
from .harmony_pipeline import DeterministicHarmonyAnalysis, run_deterministic_harmony_analysis
from .live_bridge import LiveBridge
from .rhythm_analyzer import (
    DeterministicRhythmAnalysis,
    Observation,
    run_deterministic_rhythm_analysis,
)

AnalysisKind = Literal["rhythm", "harmony", "both"]
Region = Literal["loop", "clip"]
Material = Literal["auto", "percussion", "pitched"]
PitchNames = Literal["scientific", "ableton"]

_READ_ONLY = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP("Headless Orchestra")


def _round_floats(value: Any, ndigits: int = 4) -> Any:
    """Рекурсивно округлить все float в структуре до ``ndigits`` знаков."""
    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, dict):
        return {key: _round_floats(item, ndigits) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_floats(item, ndigits) for item in value]
    return value


def _pitch_names() -> PitchNames:
    """Конвенция имён питчей из ``HO_PITCH_NAMES`` (по умолчанию scientific)."""
    value = os.environ.get("HO_PITCH_NAMES", "scientific")
    if value in ("scientific", "ableton"):
        return value  # type: ignore[return-value]
    return "scientific"


def _build_context(
    clip_data: ClipData,
    win: WindowedClip,
    *,
    track_index: int,
    clip_index: int,
    region: Region,
    bpb: int,
    material_reason: str,
) -> dict[str, Any]:
    """Собрать ``context`` в прежнем формате ответа инструмента."""
    ts = clip_data.time_signature
    if region == "loop" and clip_data.window is not None:
        region_start, region_end = clip_data.window
    else:
        region_start, region_end = 0.0, None

    pad_names = clip_data.pad_map or {}

    return {
        "track_index": track_index,
        "track_name": clip_data.ref.track_name,
        "clip_index": clip_index,
        "clip_name": clip_data.ref.clip_name,
        "tempo_bpm": clip_data.tempo_bpm,
        "time_signature": f"{ts.numerator}/{ts.denominator}",
        "beats_per_bar": bpb,
        "region": region,
        "region_start": region_start,
        "region_end": region_end,
        "notes_total": win.total,
        "notes_in_region": win.in_region,
        "notes_outside_region": win.outside_region,
        "notes_muted_skipped": win.muted_skipped,
        "notes_with_probability_below_1": win.probability_below_1,
        "has_drum_rack": clip_data.pad_map is not None,
        "pad_names": pad_names,
        "pitches_without_pad": win.pitches_without_pad,
        "material_reason": material_reason,
    }


def _compact_observation(obs: Observation) -> dict[str, Any]:
    """Компактный вид наблюдения: ACCENTS/GHOST_NOTES без полного positions."""
    dumped = obs.model_dump()
    if obs.code in ("ACCENTS", "GHOST_NOTES"):
        positions = dumped["value"].get("positions", [])
        dumped["value"] = {
            "count": len(positions),
            "positions_head": positions[:8],
        }
    return dumped


def _rhythm_compact(result: DeterministicRhythmAnalysis) -> dict[str, Any]:
    """Компактный вид ритма: без onsets/intervals/buckets."""
    return {
        "routing": result.routing.model_dump(),
        "clip_length_beats": result.clip_length_beats,
        "clip_length_inferred": result.clip_length_inferred,
        "observations": [_compact_observation(obs) for obs in result.observations],
        "lanes": [
            {
                "lane_id": lane.lane_id,
                "label": lane.label,
                "pitch_name": lane.pitch_name,
                "count": lane.count,
                "interval_mean": lane.interval_mean,
                "interval_cv": lane.interval_cv,
                "timing": {
                    "dev_mean": lane.timing.dev_mean,
                    "dev_std": lane.timing.dev_std,
                    "swing_ratio": lane.timing.swing_ratio,
                },
                "velocity": {
                    "min": lane.velocity.min,
                    "max": lane.velocity.max,
                    "median": lane.velocity.median,
                },
                "hits_per_bar": lane.hits_per_bar,
            }
            for lane in result.lanes
        ],
    }


def _harmony_compact(result: DeterministicHarmonyAnalysis) -> dict[str, Any]:
    """Компактный вид гармонии: без raw_notes и лишних полей событий."""
    return {
        "key": result.key,
        "key_confidence": result.key_confidence,
        "tonal_mode": result.tonal_mode,
        "tonal_mode_reason": result.tonal_mode_reason,
        "chord_events": [
            {
                "nominal_pos": event["nominal_pos"],
                "roman_numeral": event.get("roman_numeral"),
                "function": event.get("function"),
                "is_possible_anticipation": event.get("is_possible_anticipation"),
                "is_diatonic": event.get("is_diatonic"),
                "is_incomplete": event.get("is_incomplete"),
            }
            for event in result.chord_events
        ],
    }


def _serialize_rhythm(result: DeterministicRhythmAnalysis | None, detail: bool) -> Any:
    if result is None:
        return None
    return result.model_dump() if detail else _rhythm_compact(result)


def _serialize_harmony(result: DeterministicHarmonyAnalysis | None, detail: bool) -> Any:
    if result is None:
        return None
    return result.model_dump() if detail else _harmony_compact(result)


@mcp.tool(annotations=_READ_ONLY)
def find_midi_clips(query: str = "") -> str:
    """Список MIDI-клипов Session view с фильтром по имени трека или клипа."""
    bridge = LiveBridge()
    adapter = AbletonAdapter(bridge)
    snapshot = bridge.call("get_session_snapshot")
    tempo = snapshot.get("tempo")
    time_signature = snapshot.get("time_signature", "4/4")

    clips: list[dict[str, Any]] = []
    for summary in adapter.list_clips(query):
        track_index, clip_index = parse_ref_id(summary.ref.id)
        clips.append(
            {
                "track_index": track_index,
                "track_name": summary.ref.track_name,
                "clip_index": clip_index,
                "clip_name": summary.ref.clip_name,
                "length": summary.length,
                "is_playing": summary.is_playing,
                "has_drum_rack": summary.has_kit,
            }
        )

    response = {"tempo": tempo, "time_signature": time_signature, "clips": clips}
    return json.dumps(_round_floats(response), ensure_ascii=False)


@mcp.tool(annotations=_READ_ONLY)
def analyze_clip(
    track_index: int,
    clip_index: int,
    analysis: AnalysisKind = "both",
    region: Region = "loop",
    material: Material = "auto",
    detail: bool = False,
) -> str:
    """Проанализировать клип: ритм и/или гармония поверх посчитанных фактов."""
    bridge = LiveBridge()
    adapter = AbletonAdapter(bridge)
    ref_id = f"ableton:t{track_index}/s{clip_index}"
    clip_data = adapter.read_clip(ref_id)
    win = windowed(clip_data, region)
    bpb = beats_per_bar(clip_data.time_signature)

    material_reason = (
        "explicit"
        if material != "auto"
        else ("drum_rack_on_track" if clip_data.pad_map is not None else "heuristic")
    )

    errors: dict[str, str] = {}
    rhythm_result: DeterministicRhythmAnalysis | None = None
    harmony_result: DeterministicHarmonyAnalysis | None = None

    if analysis in ("rhythm", "both"):
        try:
            material_hint: Literal["percussion", "pitched"] | None = (
                "percussion" if clip_data.pad_map is not None else None
            )
            rhythm_result = run_deterministic_rhythm_analysis(
                win.notes,
                bpb,
                clip_length_beats=win.length,
                material=material,
                material_hint=material_hint,
                lane_names=clip_data.pad_map,
                pitch_names=_pitch_names(),
            )
        except ValueError as error:
            rhythm_result = None
            errors["rhythm"] = str(error)

    if analysis in ("harmony", "both"):
        try:
            harmony_result = run_deterministic_harmony_analysis(win.notes, bpb)
        except ValueError as error:
            harmony_result = None
            errors["harmony"] = str(error)

    response = {
        "context": _build_context(
            clip_data,
            win,
            track_index=track_index,
            clip_index=clip_index,
            region=region,
            bpb=bpb,
            material_reason=material_reason,
        ),
        "rhythm": _serialize_rhythm(rhythm_result, detail),
        "harmony": _serialize_harmony(harmony_result, detail),
        "errors": errors,
    }
    return json.dumps(_round_floats(response), ensure_ascii=False)


def main() -> None:
    """Запустить MCP-сервер через stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
