"""Агент анализа гармонии в MIDI клипах."""

from typing import Any, Literal

from pydantic import BaseModel

from api_layer.client import ProducerPalClient

from .workflows.analyze_harmony import create_analysis_workflow


class HarmonyAnalysis(BaseModel):
    """Результат гармонического анализа клипа."""

    key: str
    key_confidence: float
    key_alternate_gap: float
    confidence: float  # alias key_confidence для обратной совместимости
    tonal_mode: Literal["functional", "modal", "ambiguous"]
    tonal_mode_reason: str
    chords: list[str]
    scale_notes: list[str]
    reasoning: str
    raw_notes: list[dict[str, Any]]
    chord_events: list[dict[str, Any]]


class HarmonyAnalyzer:
    """Агент для анализа гармонии в MIDI клипах.

    Детерминированная разметка (тональность, ступени, T-S-D) — music21.
    Claude — только reasoning/интерпретация поверх готовых полей.
    """

    def __init__(self, client: ProducerPalClient, api_key: str) -> None:
        """Инициализация агента.

        Args:
            client: ProducerPalClient для доступа к Ableton.
            api_key: Anthropic API key для Claude.
        """
        self.client = client
        self.api_key = api_key
        self.workflow = create_analysis_workflow(client, api_key).compile()

    async def analyze_clip(
        self,
        track_index: int,
        scene_index: int,
    ) -> HarmonyAnalysis:
        """Анализирует гармонию в MIDI клипе по позиции в Session View.

        Args:
            track_index: Индекс трека (trackIndex) в проекте.
            scene_index: Индекс сцены (scene) — первый клип = 0.

        Returns:
            HarmonyAnalysis с результатами анализа.

        Raises:
            ValueError: Если клип не содержит нот или workflow завершился с ошибкой.
        """
        initial_state = {
            "track_index": track_index,
            "scene_index": scene_index,
            "clip": None,
            "time_signature": None,
            "skill_content": None,
            "functional_harmony": None,
            "claude_response": None,
            "chord_events": None,
            "analysis_result": None,
            "error": None,
        }
        try:
            result = self.workflow.invoke(initial_state)
        except Exception as e:
            raise ValueError(f"Workflow invocation failed: {e}") from e

        if result.get("error"):
            raise ValueError(result["error"])

        analysis_result = result.get("analysis_result")
        if analysis_result is None:
            raise ValueError("Workflow failed to produce analysis_result")

        try:
            return HarmonyAnalysis.model_validate(analysis_result)
        except Exception as e:
            raise ValueError(
                f"Invalid analysis result shape: {e}"
            ) from e
