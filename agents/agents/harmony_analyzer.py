"""Агент анализа гармонии в MIDI клипах."""

from typing import Any

from pydantic import BaseModel

from api_layer.client import ProducerPalClient

from .workflows.analyze_harmony import create_analysis_workflow


class HarmonyAnalysis(BaseModel):
    """Результат гармонического анализа клипа."""

    key: str  # Например: "C major", "A minor"
    confidence: float  # 0.0 - 1.0
    chords: list[str]  # Список аккордов: ["Cmaj", "Fmaj", "G7"]
    scale_notes: list[str]  # Ноты гаммы: ["C", "D", "E", "F", "G", "A", "B"]
    reasoning: str  # Объяснение от Claude
    raw_notes: list[dict[str, Any]]  # Исходные ноты из клипа


class HarmonyAnalyzer:
    """Агент для анализа гармонии в MIDI клипах.

    Использует Claude API + music theory skills для:
    - Определения тональности
    - Распознавания аккордов
    - Анализа гармонических прогрессий
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
            "skill_content": None,
            "claude_response": None,
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
