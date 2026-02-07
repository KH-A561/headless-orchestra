"""LangGraph workflow для гармонического анализа."""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph
from anthropic import Anthropic

from api_layer.client import ProducerPalClient
from api_layer.models import Clip

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


def pitch_to_midi(pitch: str) -> int:
    """Конвертирует строку pitch (например 'C3', 'F#4', 'Bb2') в MIDI номер.
    C4 = 60, A4 = 69.
    """
    pitch = pitch.strip().upper()
    if not pitch:
        raise ValueError("Empty pitch string")
    # Отделяем буквенную часть от октавы (цифры в конце, возможно с минусом)
    match = re.match(r"^([A-G][#B]?)(-?\d+)$", pitch)
    if not match:
        raise ValueError(f"Invalid pitch format: {pitch}")
    note_part, octave_part = match.group(1), match.group(2)
    # Bb -> BB для словаря
    if len(note_part) == 2 and note_part[1] == "B":
        note_part = f"{note_part[0]}B"
    if note_part not in _PITCH_TO_SEMITONE:
        raise ValueError(f"Unknown note name: {note_part}")
    octave = int(octave_part)
    semitone = _PITCH_TO_SEMITONE[note_part]
    # MIDI: (octave + 1) * 12 + semitone => C4 = 5*12+0 = 60
    return (octave + 1) * 12 + semitone


class AnalysisState(TypedDict):
    """Состояние workflow анализа гармонии."""

    track_index: int
    scene_index: int
    clip: Clip | None
    skill_content: str | None
    claude_response: dict | None
    analysis_result: dict | None
    error: str | None


def create_analysis_workflow(
    client: ProducerPalClient,
    api_key: str,
) -> StateGraph:
    """Создает LangGraph workflow для анализа гармонии.

    Workflow structure:
    START → fetch_clip → load_skill → analyze_with_claude → format_result → END

    Args:
        client: ProducerPalClient для доступа к Ableton
        api_key: Anthropic API key

    Returns:
        Configured StateGraph ready to compile
    """

    def fetch_clip(state: AnalysisState) -> AnalysisState:
        """Node 1: Получить клип из Ableton по trackIndex и sceneIndex."""
        try:
            clip = client.get_clip(
                state["track_index"],
                clip_id=None,
                scene_index=state["scene_index"],
            )
            if not clip.notes:
                return {**state, "error": "Clip contains no notes"}
            return {**state, "clip": clip, "error": None}
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

    def analyze_with_claude(state: AnalysisState) -> AnalysisState:
        """Node 3: Анализ через Claude API."""
        if state.get("error"):
            return state

        clip = state.get("clip")
        skill_content = state.get("skill_content") or ""

        if not clip or not clip.notes:
            return {**state, "error": "No clip or notes to analyze"}

        try:
            # 2. Сгруппировать ноты по start (времени)
            notes_by_time: dict[str, list[str]] = defaultdict(list)
            for note in clip.notes:
                notes_by_time[note.start].append(note.pitch)

            # Преобразовать в список временных точек с MIDI pitch
            chord_progression: list[dict] = []
            sort_key = lambda s: tuple(float(x) for x in s.split("|"))
            for start_time in sorted(notes_by_time.keys(), key=sort_key):
                pitches = notes_by_time[start_time]
                midi_pitches = []
                for p in pitches:
                    try:
                        midi_pitches.append(pitch_to_midi(p))
                    except ValueError as e:
                        print(f"Warning: skip invalid pitch {p}: {e}")
                if midi_pitches:
                    chord_progression.append({
                        "time": start_time,
                        "pitches": sorted(midi_pitches),
                    })
            if not chord_progression:
                return {**state, "error": "No valid pitches extracted from clip notes"}

            print(f"Extracted chord progression: {len(chord_progression)} time points")

            # 3. Подготовить prompt для Claude
            system_message = (
                "You are a music theory expert. Analyze the harmony using the provided skill knowledge."
            )
            user_message = (
                f"{skill_content}\n\n"
                "Analyze this chord progression:\n"
            )
            for chord in chord_progression:
                user_message += f"  At {chord['time']}: {chord['pitches']}\n"
            user_message += (
                "\nReturn a single JSON object with:\n"
                '"key", "confidence", "chords" (list of chord symbols with timing, e.g. "Cmaj @ 1|1"), '
                '"scale_notes", "reasoning".'
            )

            # 4. Вызвать Anthropic API
            print("Calling Claude API...")
            anthropic_client = Anthropic(api_key=api_key)
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                temperature=0,
                system=system_message,
                messages=[{"role": "user", "content": user_message}],
            )

            # 5. Распарсить ответ
            if not response.content or not hasattr(response.content[0], "text"):
                return {
                    **state,
                    "error": "Empty or invalid response from Claude API",
                }
            text = response.content[0].text

            # Убрать markdown-обертку ```json ... ``` если есть
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if json_match:
                text = json_match.group(1).strip()
            else:
                text = text.strip()

            result = json.loads(text)

            # Проверка ожидаемой структуры
            required_keys = {"key", "confidence", "chords", "scale_notes", "reasoning"}
            if not required_keys.issubset(result.keys()):
                missing = required_keys - result.keys()
                return {
                    **state,
                    "error": f"Claude response missing keys: {missing}",
                }

            print("Claude analysis successful.")
            return {
                **state,
                "claude_response": result,
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
        """Node 4: Форматировать результат в HarmonyAnalysis."""
        if state.get("error"):
            return state

        claude_response = state.get("claude_response")
        clip = state.get("clip")

        required_keys = {"key", "confidence", "chords", "scale_notes", "reasoning"}
        if not claude_response or not isinstance(claude_response, dict):
            return {**state, "error": "Missing or invalid claude_response"}
        if not required_keys.issubset(claude_response.keys()):
            missing = required_keys - claude_response.keys()
            return {**state, "error": f"claude_response missing keys: {missing}"}
        if not clip or not clip.notes:
            return {**state, "error": "Missing clip or notes for raw_notes"}

        raw_notes = [
            {
                "pitch": note.pitch,
                "start": note.start,
                "duration": note.duration,
                "velocity": note.velocity,
            }
            for note in clip.notes
        ]

        analysis_result = {
            "key": claude_response["key"],
            "confidence": claude_response["confidence"],
            "chords": claude_response["chords"],
            "scale_notes": claude_response["scale_notes"],
            "reasoning": claude_response["reasoning"],
            "raw_notes": raw_notes,
        }

        return {**state, "analysis_result": analysis_result}

    # Создаем граф
    workflow = StateGraph(AnalysisState)

    # Добавляем узлы
    workflow.add_node("fetch_clip", fetch_clip)
    workflow.add_node("load_skill", load_skill)
    workflow.add_node("analyze_with_claude", analyze_with_claude)
    workflow.add_node("format_result", format_result)

    # Определяем edges
    workflow.set_entry_point("fetch_clip")
    workflow.add_edge("fetch_clip", "load_skill")
    workflow.add_edge("load_skill", "analyze_with_claude")
    workflow.add_edge("analyze_with_claude", "format_result")
    workflow.add_edge("format_result", END)

    return workflow
