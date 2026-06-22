"""LangGraph workflow для гармонического анализа."""

import json
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from api_layer.client import ProducerPalClient
from api_layer.models import Clip

from ..chord_grouping import parse_time_signature
from ..harmony_pipeline import (
    DeterministicHarmonyAnalysis,
    fetch_claude_harmony_reasoning,
    run_deterministic_harmony_analysis,
)


class AnalysisState(TypedDict):
    """Состояние workflow анализа гармонии."""

    track_index: int
    scene_index: int
    clip: Clip | None
    time_signature: str | None
    skill_content: str | None
    functional_harmony: dict[str, Any] | None
    claude_response: dict | None
    chord_events: list[dict[str, Any]] | None
    analysis_result: dict | None
    error: str | None


def create_analysis_workflow(
    client: ProducerPalClient,
    api_key: str,
) -> StateGraph:
    """Создает LangGraph workflow для анализа гармонии.

    Workflow structure:
    START → fetch_clip → load_skill → deterministic_analysis
          → analyze_with_claude → format_result → END
    """

    def fetch_clip(state: AnalysisState) -> AnalysisState:
        """Node 1: Получить клип из Ableton по trackIndex и sceneIndex."""
        try:
            project = client.get_project_info()
            time_signature = (
                project.get("timeSignature")
                or project.get("time_signature")
                or ""
            )
            clip = client.get_clip(
                state["track_index"],
                clip_id=None,
                scene_index=state["scene_index"],
            )
            if not clip.notes:
                return {**state, "error": "Clip contains no notes"}
            return {
                **state,
                "clip": clip,
                "time_signature": time_signature,
                "error": None,
            }
        except Exception as e:
            return {**state, "error": f"Failed to fetch clip: {e}"}

    def load_skill(state: AnalysisState) -> AnalysisState:
        """Node 2: Загрузить skill файл."""
        if state.get("error"):
            return state

        skill_path = Path(__file__).parent.parent / "skills" / "harmony_theory.md"
        try:
            skill_content = skill_path.read_text(encoding="utf-8")
            return {**state, "skill_content": skill_content}
        except Exception as e:
            return {**state, "error": f"Failed to load skill: {e}"}

    def deterministic_analysis(state: AnalysisState) -> AnalysisState:
        """Node 3: Группировка + детерминированная разметка (music21)."""
        if state.get("error"):
            return state

        clip = state.get("clip")
        if not clip or not clip.notes:
            return {**state, "error": "No clip or notes to analyze"}

        try:
            beats_per_bar = parse_time_signature(state.get("time_signature") or "")
            result = run_deterministic_harmony_analysis(clip.notes, beats_per_bar)

            print(
                f"Deterministic analysis: key={result.key}, "
                f"mode={result.tonal_mode}, chords={len(result.chord_events)}"
            )

            return {
                **state,
                "functional_harmony": {
                    "key": result.key,
                    "key_confidence": result.key_confidence,
                    "key_alternate_gap": result.key_alternate_gap,
                    "tonal_mode": result.tonal_mode,
                    "tonal_mode_reason": result.tonal_mode_reason,
                    "scale_notes": result.scale_notes,
                    "chords": result.chords,
                },
                "chord_events": result.chord_events,
                "error": None,
            }
        except ValueError as e:
            return {**state, "error": str(e)}
        except Exception as e:
            return {**state, "error": f"Deterministic analysis failed: {e}"}

    def analyze_with_claude(state: AnalysisState) -> AnalysisState:
        """Node 4: Claude — только reasoning поверх готовой разметки."""
        if state.get("error"):
            return state

        skill_content = state.get("skill_content") or ""
        functional = state.get("functional_harmony")
        chord_events = state.get("chord_events") or []

        if not functional:
            return {**state, "error": "Missing functional_harmony from deterministic step"}

        try:
            clip = state.get("clip")
            raw_notes = []
            if clip and clip.notes:
                raw_notes = [
                    {
                        "pitch": n.pitch,
                        "start": n.start,
                        "duration": n.duration,
                        "velocity": n.velocity,
                    }
                    for n in clip.notes
                ]

            deterministic = DeterministicHarmonyAnalysis(
                key=functional["key"],
                key_confidence=functional["key_confidence"],
                key_alternate_gap=functional["key_alternate_gap"],
                confidence=functional["key_confidence"],
                tonal_mode=functional["tonal_mode"],
                tonal_mode_reason=functional["tonal_mode_reason"],
                chords=functional["chords"],
                scale_notes=functional["scale_notes"],
                raw_notes=raw_notes,
                chord_events=chord_events,
            )

            print("Calling Claude API for reasoning...")
            reasoning = fetch_claude_harmony_reasoning(
                deterministic,
                api_key,
                skill_content=skill_content,
            )

            print("Claude reasoning successful.")
            return {
                **state,
                "claude_response": {"reasoning": reasoning},
                "error": None,
            }

        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            return {
                **state,
                "error": f"Failed to parse Claude response as JSON: {e}",
            }
        except Exception as e:
            print(f"Claude API error: {e}")
            return {
                **state,
                "error": f"Claude API failed: {e}",
            }

    def format_result(state: AnalysisState) -> AnalysisState:
        """Node 5: Собрать HarmonyAnalysis из deterministic + Claude reasoning."""
        if state.get("error"):
            return state

        functional = state.get("functional_harmony")
        claude_response = state.get("claude_response")
        clip = state.get("clip")

        if not functional:
            return {**state, "error": "Missing functional_harmony"}
        if not claude_response or "reasoning" not in claude_response:
            return {**state, "error": "Missing or invalid claude_response"}
        if not clip or not clip.notes:
            return {**state, "error": "Missing clip or notes for raw_notes"}

        raw_notes = [
            {
                "pitch": note_obj.pitch,
                "start": note_obj.start,
                "duration": note_obj.duration,
                "velocity": note_obj.velocity,
            }
            for note_obj in clip.notes
        ]

        key_confidence = functional["key_confidence"]
        analysis_result = {
            "key": functional["key"],
            "key_confidence": key_confidence,
            "key_alternate_gap": functional["key_alternate_gap"],
            "confidence": key_confidence,
            "tonal_mode": functional["tonal_mode"],
            "tonal_mode_reason": functional["tonal_mode_reason"],
            "chords": functional["chords"],
            "scale_notes": functional["scale_notes"],
            "reasoning": claude_response["reasoning"],
            "raw_notes": raw_notes,
            "chord_events": state.get("chord_events") or [],
        }

        return {**state, "analysis_result": analysis_result}

    workflow = StateGraph(AnalysisState)

    workflow.add_node("fetch_clip", fetch_clip)
    workflow.add_node("load_skill", load_skill)
    workflow.add_node("deterministic_analysis", deterministic_analysis)
    workflow.add_node("analyze_with_claude", analyze_with_claude)
    workflow.add_node("format_result", format_result)

    workflow.set_entry_point("fetch_clip")
    workflow.add_edge("fetch_clip", "load_skill")
    workflow.add_edge("load_skill", "deterministic_analysis")
    workflow.add_edge("deterministic_analysis", "analyze_with_claude")
    workflow.add_edge("analyze_with_claude", "format_result")
    workflow.add_edge("format_result", END)

    return workflow
