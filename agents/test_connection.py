"""Диагностика подключения к Producer Pal."""

# Запуск: из папки agents — poetry run python test_connection.py
#         из корня репо — poetry run python -m agents.test_connection
from api_layer.client import ProducerPalClient


def test_connection():
    """Проверяет базовое подключение к Producer Pal."""
    
    print("="*60)
    print("PRODUCER PAL CONNECTION TEST")
    print("="*60)
    
    client = ProducerPalClient()
    
    # Тест 1: Получить информацию о проекте
    print("\n[TEST 1] Getting project info...")
    try:
        project = client.get_project_info()
        print(f"✓ Success! Tempo: {project.get('tempo', 'N/A')} BPM")
        
        tracks = project.get("tracks", [])
        print(f"✓ Tracks count: {len(tracks)}")
        
        if tracks:
            print("\nAvailable tracks:")
            for i, tr in enumerate(tracks):
                track_name = tr.get("name", f"Track {i}")
                track_id = tr.get("id", "?")
                clips_count = len(tr.get("clips", []))
                print(f"  [{i}] id={track_id}: {track_name} ({clips_count} clips)")
        else:
            print("⚠ No tracks found in project")
            
    except Exception as e:
        print(f"✗ Failed: {e}")
        print("\nPossible issues:")
        print("  1. Producer Pal not running in Ableton")
        print("  2. Producer Pal not on port 3350")
        print("  3. Ableton project not open")
        return
    
    # Тест 2: Получить первый трек по ID из project info
    if not tracks:
        print("\n[TEST 2] Skipped (no tracks)")
    else:
        first_track_id = tracks[0].get("id", "2")  # fallback "2"
        print(f"\n[TEST 2] Getting track [0] id={first_track_id!r}...")
        try:
            track = client.get_track(first_track_id)
            print(f"✓ Track [0] id={first_track_id}: {track.name}")
            print(f"✓ Clips: {len(track.clips)}")
            
            if track.clips:
                print(f"\nClips on track [0] id={first_track_id}:")
                for i, clip in enumerate(track.clips):
                    notes_count = len(clip.notes) if clip.notes else 0
                    print(f"  Clip {i}: {clip.name} ({notes_count} notes)")
            else:
                print(f"⚠ No clips on track [0] id={first_track_id}")
                print("  → Create a MIDI clip on this track in Ableton")
                
        except Exception as e:
            print(f"✗ Failed: {e}")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    test_connection()
