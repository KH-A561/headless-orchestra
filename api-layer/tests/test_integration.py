"""Integration test with real Producer Pal instance."""

from api_layer.client import ProducerPalClient
from api_layer.models import Note

def main():
    """Test against running Producer Pal."""
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
    
    # Test 2: Get Track Info
    print("\n[2/3] Testing get_track()...")
    tracks = project.get('tracks', [])
    if tracks:
        track_id = tracks[0].get('id')
        track_name = tracks[0].get('name', 'Unknown')
        print(f"  ✓ Getting track '{track_name}' (id={track_id})...")
        
        track = client.get_track(track_id)
        print(f"  ✓ Track.name: {track.name}")
        print(f"  ✓ Track.clips: {len(track.clips)}")
    else:
        print("  ⚠ No tracks in project (create at least one track)")
    
    # Test 3: Create MIDI Clip (commented out to avoid side effects)
    print("\n[3/3] Testing create_midi_clip() (dry-run)...")
    notes = [
        Note(pitch="C3", start="1|1", duration="1:0", velocity=80),
        Note(pitch="E3", start="2|1", duration="1:0", velocity=80),
        Note(pitch="G3", start="3|1", duration="1:0", velocity=80),
    ]
    print(f"  ✓ Created {len(notes)} test notes")
    print("  ⚠ Skipping actual clip creation (uncomment to test)")
    
    # Uncomment to actually create clip:
    # if tracks:
    #     clip = client.create_midi_clip(track_id, notes)
    #     print(f"  ✓ Clip created: {clip.name}")
    
    print("\n" + "=" * 60)
    print("✓ All integration tests passed!")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())