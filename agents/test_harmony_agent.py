"""Интеграционный тест HarmonyAnalyzer."""

import asyncio
import os

# Запуск: из папки agents — poetry run python test_harmony_agent.py
#         из корня репо — poetry run python -m agents.test_harmony_agent
from api_layer.client import ProducerPalClient

from agents.harmony_analyzer import HarmonyAnalyzer


async def test_harmony_analyzer():
    """Тестирует HarmonyAnalyzer на реальном клипе из Ableton."""
    print("=" * 60)
    print("MAKE SURE:")
    print("1. Ableton Live is running")
    print("2. Producer Pal is loaded and showing port 3350")
    print("3. At least one MIDI clip with notes exists")
    print("4. ANTHROPIC_API_KEY environment variable is set")
    print("=" * 60)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        return

    print("\nInitializing clients...")
    client = ProducerPalClient()
    analyzer = HarmonyAnalyzer(client, api_key)

    print("Getting project info...")
    project_info = client.get_project_info()
    tracks = project_info.get("tracks", [])

    if not tracks:
        print("ERROR: No tracks in project")
        return

    # Взять первый трек с клипами
    track_to_analyze = None
    for track in tracks:
        if track.get("sessionClipCount", 0) > 0:
            track_to_analyze = track
            break

    if not track_to_analyze:
        print("ERROR: No tracks with clips found")
        print("Create a MIDI clip in Ableton first")
        return

    track_index = track_to_analyze.get("trackIndex", tracks.index(track_to_analyze))
    scene_index = 0  # первый клип в сессии

    print(f"Found track: {track_to_analyze['name']} (trackIndex={track_index})")
    print(f"\nAnalyzing clip: track_index={track_index}, scene_index={scene_index}")
    print("[DEBUG] Calling analyzer.analyze_clip()...")

    try:
        result = await analyzer.analyze_clip(track_index, scene_index)
        print("[DEBUG] analyze_clip() returned successfully")

        print("\n" + "=" * 60)
        print("HARMONY ANALYSIS RESULT")
        print("=" * 60)
        print(f"Key: {result.key}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Scale notes: {', '.join(result.scale_notes)}")
        print(f"Chords: {', '.join(result.chords)}")
        print(f"\nReasoning:")
        print(result.reasoning)
        print(f"\nRaw notes count: {len(result.raw_notes)}")
        print("=" * 60)

    except ValueError as e:
        print(f"\nERROR (ValueError): {e}")
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(test_harmony_analyzer())
