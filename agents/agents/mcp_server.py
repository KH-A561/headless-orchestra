"""MCP-сервер Headless Orchestra (read-only анализ клипов из живого Live).

Сервер читает данные из Live через мост ``mcp-server-ableton-live``, прогоняет
их через детерминированные пайплайны и возвращает компактные посчитанные факты.
Ноты через LLM-контекст не проходят.

Запуск: ``python -m agents.mcp_server`` или консольный скрипт ``ho-mcp``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .clip_source import ClipContext, load_clip
from .harmony_pipeline import DeterministicHarmonyAnalysis, run_deterministic_harmony_analysis
from .live_bridge import LiveBridge
from .rhythm_analyzer import DeterministicRhythmAnalysis, run_deterministic_rhythm_analysis

AnalysisKind = Literal["rhythm", "harmony", "both"]
Region = Literal["loop", "clip"]
Material = Literal["auto", "percussion", "pitched"]

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


def _resolve_material(
    material: Material,
    context: ClipContext,
) -> Literal["auto", "percussion", "pitched"]:
    """Решить ``material`` для ритма и зафиксировать причину в контексте."""
    if material != "auto":
        context.material_reason = "explicit"
        return material
    if context.has_drum_rack:
        return "percussion"
    return "auto"


def _rhythm_compact(result: DeterministicRhythmAnalysis) -> dict[str, Any]:
    """Компактный вид ритма: без onsets/intervals/buckets."""
    return {
        "routing": result.routing.model_dump(),
        "clip_length_beats": result.clip_length_beats,
        "clip_length_inferred": result.clip_length_inferred,
        "observations": [obs.model_dump() for obs in result.observations],
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
    snapshot = bridge.call("get_session_snapshot")
    tempo = snapshot.get("tempo")
    time_signature = snapshot.get("time_signature", "4/4")

    needle = (query or "").lower()
    clips: list[dict[str, Any]] = []

    for track in snapshot.get("tracks", []):
        if track.get("type") != "midi":
            continue
        if int(track.get("clips", 0)) <= 0:
            continue

        track_index = int(track["index"])
        track_name = track.get("name", "")
        track_info = bridge.call("get_track_info", {"track_index": track_index})
        has_drum_rack = any(
            device.get("class_name") == "DrumGroupDevice"
            for device in track_info.get("devices", [])
        )

        for slot in track_info.get("clip_slots", []):
            if not slot.get("has_clip"):
                continue
            clip = slot.get("clip") or {}
            clip_name = clip.get("name", "")
            if needle and needle not in track_name.lower() and needle not in clip_name.lower():
                continue
            clips.append(
                {
                    "track_index": track_index,
                    "track_name": track_name,
                    "clip_index": int(slot.get("index", 0)),
                    "clip_name": clip_name,
                    "length": clip.get("length"),
                    "is_playing": clip.get("is_playing"),
                    "has_drum_rack": has_drum_rack,
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
    notes, context, clip_length_beats = load_clip(bridge, track_index, clip_index, region)

    errors: dict[str, str] = {}
    rhythm_result: DeterministicRhythmAnalysis | None = None
    harmony_result: DeterministicHarmonyAnalysis | None = None

    if analysis in ("rhythm", "both"):
        try:
            resolved_material = _resolve_material(material, context)
            rhythm_result = run_deterministic_rhythm_analysis(
                notes,
                context.beats_per_bar,
                clip_length_beats=clip_length_beats,
                material=resolved_material,
                lane_names=context.pad_names,
            )
        except ValueError as error:
            rhythm_result = None
            errors["rhythm"] = str(error)

    if analysis in ("harmony", "both"):
        try:
            harmony_result = run_deterministic_harmony_analysis(notes, context.beats_per_bar)
        except ValueError as error:
            harmony_result = None
            errors["harmony"] = str(error)

    response = {
        "context": context.model_dump(),
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
