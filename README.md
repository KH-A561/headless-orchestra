# Headless Orchestra

Music analysis assistant for Ableton Live: a deterministic "music linter" plus an LLM explainer.

## Principle

- **The deterministic layer (music21 / mido) computes the facts and owns all classification**:
  chord events, key, roman numerals, T-S-D functions, tonal-mode gating.
- **Claude only reasons and explains** on top of those computed facts. It never classifies on its own.
- **Analysis is descriptive, not prescriptive.** For ambiguous or modal material, functions are
  *suppressed rather than guessed*. Intentional strangeness is flagged, not "fixed".

See [docs/VISION.md](docs/VISION.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Status (November 2026)

| Component | State |
|---|---|
| `api-layer` — Producer Pal client (MCP over HTTP :3350), Pydantic models | ✅ unit-tested with mocks; ⚠️ live Ableton integration not verified |
| Chord grouping — tolerant onset clustering, time-signature aware, anticipation flag | ✅ |
| Functional harmony Level 2 (slices A+B) — Krumhansl-Schmuckler key, roman numerals, T-S-D, `detect_tonal_mode` gating, incomplete chords | ✅ |
| Shared pipeline `run_deterministic_harmony_analysis` — used by the LangGraph workflow and the offline harness | ✅ |
| RhythmAnalyzer | 📝 design only — [docs/rhythm_analyzer_notes.md](docs/rhythm_analyzer_notes.md) |
| Harmony slice C (cadences, local key, secondary dominants, borrowed chords) | ⏳ planned |
| TimbreAnalyzer, swappable reasoning provider | ⏳ planned |

Open decision: stay on Producer Pal or move to the Ableton Extensions SDK
(beta, local copy in `docs/ableton-extensions-sdk/`).

## Architecture

```
LangGraph workflow (agents/agents/workflows/analyze_harmony.py)
  fetch_clip → load_skill → deterministic_analysis → analyze_with_claude → format_result
        │                          │
        │                          └─ harmony_pipeline.py  (chord_grouping + functional_labeling)
        ▼
api-layer: ProducerPalClient ──HTTP/MCP──► Producer Pal (Max for Live, :3350) ──► Ableton Live
```

The offline harness (`agents/scripts/analyze_midi_file.py`) runs the same deterministic pipeline
on a `.mid` file without Ableton.

## Project structure

```
headless-orchestra/
├── api-layer/                  # Producer Pal client
│   ├── api_layer/client.py     # ProducerPalClient
│   ├── api_layer/models.py     # Pydantic models (Note, Clip, Track)
│   └── tests/                  # pytest, mocked HTTP
├── agents/
│   ├── agents/
│   │   ├── chord_grouping.py       # onset clustering, anticipation
│   │   ├── functional_labeling.py  # key, roman numerals, T-S-D, tonal mode
│   │   ├── harmony_pipeline.py     # deterministic pipeline + Claude reasoning call
│   │   ├── harmony_analyzer.py     # HarmonyAnalyzer agent
│   │   ├── workflows/analyze_harmony.py  # LangGraph graph
│   │   └── skills/harmony_theory.md      # theory knowledge base for the LLM
│   ├── scripts/analyze_midi_file.py      # offline harness
│   ├── tests/                  # unit tests + synthetic MIDI fixtures (tests/midi/)
│   └── test_*.py               # manual diagnostics (Producer Pal, Anthropic API, live agent)
├── shared/                     # placeholder package (empty)
└── docs/
    ├── VISION.md, ARCHITECTURE.md, AI_AGENTS_GUIDE.md
    ├── rhythm_analyzer_notes.md
    ├── producer-pal/           # Producer Pal API reference
    └── ableton-extensions-sdk/ # local copy of the SDK beta + docs
```

## Running

Requires Python 3.11+ and Poetry 2.x (use `poetry run` / `poetry env activate`; there is no `poetry shell`).

```bash
# Tests
cd agents && poetry run pytest tests/ -v
cd api-layer && poetry run pytest tests/ -v

# Offline harmony analysis of a .mid file (from agents/)
poetry run python scripts/analyze_midi_file.py FILE.mid [--track N] [--with-llm] [--json]
```

`--with-llm` needs `ANTHROPIC_API_KEY`. Live workflows need Ableton with the Producer Pal device running on port 3350.

## Gotchas

- Octaves: Ableton `C3 = 60`, music21 `C4 = 60`. Convert at the boundary.
- Read note-ons with mido (raw ticks), not `converter.parse`: music21 quantizes off-grid notes
  and creates phantom duplicates.
- Ableton exports Drum Rack clips on MIDI channel 0, not GM channel 10. Don't rely on the channel
  to detect drums. Track names do survive as meta events.
- `end_of_track` in an exported `.mid` is the last event plus a tail, not the clip length.

## Workflow

Claude plans and writes specs; Cursor (agent mode) implements. Diagnoses get verified before a
fix is accepted. Changes are validated on synthetic fixtures with known ground truth.

## Acknowledgments

- [Producer Pal](https://producer-pal.org) by Adam Murray: MCP bridge for Ableton Live
- [music21](https://web.mit.edu/music21/), [mido](https://mido.readthedocs.io/), [LangGraph](https://github.com/langchain-ai/langgraph)
