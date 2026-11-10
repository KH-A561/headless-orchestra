# Cursor Rules for Headless Orchestra

## Core principle (do not violate)
- The deterministic layer (music21 / mido) computes facts and owns ALL classification
  (chords, key, roman numerals, functions, tonal mode, rhythm metrics).
- The LLM only reasons and explains on top of computed facts. Never move classification into prompts.
- Analysis is descriptive, not prescriptive. Ambiguous/modal material: suppress functions, don't guess.
- Flags are neutral observations with a metric (e.g. `OFF_GRID(0.24 beat)`), never `ERROR`.
  Intentional strangeness is described, not "fixed".

## Code Style
- Always use type hints (Python 3.11+ syntax)
- Use Pydantic for all data models
- Docstrings in Google style
- pytest for all tests
- Keep functions small and focused

## Music data gotchas
- Ableton `C3 = 60`, music21 `C4 = 60`. Convert at the boundary only.
- Read MIDI note-ons with mido (raw ticks), NOT `music21.converter.parse` (it quantizes off-grid notes
  and creates phantom duplicates).
- `note_on` with velocity 0 is a note-off.
- Ableton exports Drum Rack clips on channel 0, not GM channel 10. Never detect drums by channel.
- `end_of_track` in `.mid` is not the clip length; take the length from Ableton.

## Producer Pal Integration

Producer Pal MCP server runs at `http://localhost:3350/mcp`.
Use `api_layer.client.ProducerPalClient`; don't call the HTTP endpoint directly from agents.

### Key Tools
- `ppal-read-live-set` - Get project info
- `ppal-read-track` - Get track details
- `ppal-create-clip` - Create MIDI clip
- `ppal-read-clip` - Read clip notes

### Note Format
```python
{
    "pitch": "C3",      # Middle C (Ableton convention)
    "start": "1|1",     # bar|beat
    "duration": "1:0",  # bars:beats
    "velocity": 80,
    "probability": 1.0
}
```

## Project Structure

### api-layer/
Python client for Producer Pal MCP server.
- `api_layer/client.py` - ProducerPalClient class
- `api_layer/models.py` - Pydantic models
- `tests/` - pytest tests (mocked HTTP)

### agents/
Deterministic analysis + LangGraph agents.
- `agents/chord_grouping.py` - onset clustering, anticipation flag
- `agents/functional_labeling.py` - key detection, roman numerals, T-S-D, tonal mode gating
- `agents/harmony_pipeline.py` - `run_deterministic_harmony_analysis` (single entry point, shared by
  the LangGraph workflow and the offline harness) + Claude reasoning call
- `agents/harmony_analyzer.py` - HarmonyAnalyzer agent
- `agents/workflows/analyze_harmony.py` - LangGraph graph
- `agents/skills/` - music theory knowledge base (markdown) for the LLM
- `scripts/analyze_midi_file.py` - offline harness: `poetry run python scripts/analyze_midi_file.py FILE.mid`
- `tests/` - unit tests; `tests/midi/` - synthetic fixtures with known ground truth
- New analyzers (e.g. RhythmAnalyzer) go next to the harmony modules as `agents/<name>_*.py`;
  design notes in `docs/rhythm_analyzer_notes.md`.

### shared/
Placeholder package, currently empty.

## Development Workflow

1. Write tests first (TDD), preferably on synthetic MIDI fixtures with known ground truth
2. Implement minimal code to pass tests
3. Refactor with type safety
4. Document in docstrings
5. When diagnosing a bug, state the hypothesis and evidence before changing code
   (precedent: "duplicate notes" came from music21 quantization, not from the MIDI file)
6. Poetry 2.x: use `poetry run`, not `poetry shell`

## Testing Guidelines

- Mock external dependencies (Producer Pal, LLM APIs)
- Test both success and error cases
- Use fixtures for common test data
- Don't commit debug logs or scratch scripts
