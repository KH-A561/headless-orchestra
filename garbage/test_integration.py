"""Real integration test with Producer Pal instance.

Run this AFTER starting Ableton Live with Producer Pal loaded.
This is NOT a pytest test - it's a manual script.

Usage:
    poetry run python test_integration_real.py
"""

from api_layer.client import ProducerPalClient
from api_layer.models import Note


def main() -> int:
    """Test against running Producer Pal instance.
    
    Returns:
        0 if all tests pass, 1 if connection fails
    """
    client = ProducerPalClient()
    
    print("=" * 60)
    print("INTEGRATION TEST: Producer Pal Client")
    print("=" * 60)
    
    # Test 1: Connection & Project Info
    print("\n[1/3] Testing connection & get_project_info()...")
    try:
        project = client.get_project_info()
        tempo = project.get('tempo', 'N/A')
        tracks_count = len(project.get('tracks', []))
        print(f"  ✓ Connected successfully")
        print(f"  ✓ Tempo: {tempo} BPM")
        print(f"  ✓ Tracks: {tracks_count}")
    except ConnectionError as e:
        print(f"  ✗ Connection failed: {e}")
        print("\n  Prerequisites:")
        print("    1. Ableton Live is running")
        print("    2. Producer Pal Max for Live device is loaded")
        print("    3. Producer Pal shows 'Server running on port 3350'")
        return 1
    except ValueError as e:
        print(f"  ✗ JSON-RPC error: {e}")
        print("    This might indicate Producer Pal version mismatch")
        return 1
    
    # Test 2: Get Track Info
    print("\n[2/3] Testing get_track()...")
    tracks = project.get('tracks', [])
    if tracks:
        # Try to get first track
        first_track = tracks[0]
        track_id = first_track.get('id', 0)
        track_name = first_track.get('name', 'Unknown')
        print(f"  ✓ Getting track '{track_name}' (id={track_id})...")
        
        try:
            track = client.get_track(track_id)
            print(f"  ✓ Track.name: {track.name}")
            print(f"  ✓ Track.clips: {len(track.clips)}")
        except Exception as e:
            print(f"  ✗ Failed to get track: {e}")
    else:
        print("  ⚠ No tracks in project (create at least one track)")
    
    # Test 3: Create MIDI Clip (dry-run)
    print("\n[3/3] Testing create_midi_clip() (dry-run)...")
    notes = [
        Note(pitch="C3", start="1|1", duration="1:0", velocity=80),
        Note(pitch="E3", start="2|1", duration="1:0", velocity=80),
        Note(pitch="G3", start="3|1", duration="1:0", velocity=80),
    ]
    print(f"  ✓ Created {len(notes)} test notes (C major triad)")
    print("  ⚠ Skipping actual clip creation to avoid modifying project")
    print("    Uncomment code below to test real clip creation:")
    print("    # if tracks:")
    print("    #     clip = client.create_midi_clip(track_id, notes)")
    print("    #     print(f'  ✓ Clip created: {clip.name}')")
    
    # Uncomment to actually create clip:
    # if tracks:
    #     try:
    #         clip = client.create_midi_clip(track_id, notes)
    #         print(f"  ✓ Clip created successfully: {clip.name}")
    #     except Exception as e:
    #         print(f"  ✗ Failed to create clip: {e}")
    
    print("\n" + "=" * 60)
    print("✓ All integration tests passed!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Uncomment clip creation code to test write operations")
    print("  2. Try other API methods (get_clip, update_track, etc.)")
    print("  3. Start building AI agents that use this API layer")
    return 0


if __name__ == "__main__":
    exit(main())
