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
| Neutral core (`agents/agents/domain.py`) + adapters (Ableton Live, MIDI file) | ✅ |
| Chord grouping — tolerant onset clustering, time-signature aware, anticipation flag | ✅ |
| Functional harmony Level 2 (slices A+B) — Krumhansl-Schmuckler key, roman numerals, T-S-D, `detect_tonal_mode` gating, incomplete chords | ✅ |
| Shared pipeline `run_deterministic_harmony_analysis` — used by the LangGraph workflow and the offline harness | ✅ |
| RhythmAnalyzer | ✅ |
| Harmony slice C (cadences, local key, secondary dominants, borrowed chords) | ⏳ planned |
| TimbreAnalyzer, swappable reasoning provider | ⏳ planned |

The `api-layer/` package (Producer Pal client) is frozen and not part of the working path.

## Architecture

```
adapters (Ableton Live / .mid)
        │
        ▼
harmony_pipeline.py  (chord_grouping + functional_labeling)
        │
        └─ run_deterministic_harmony_analysis  ← shared by MCP server and offline harness
```

The core (`agents/agents/domain.py`) owns a neutral `NoteEvent` model; DAW-specific
conventions live inside the adapters. The offline harness (`agents/scripts/analyze_midi_file.py`)
runs the same deterministic pipeline on a `.mid` file without Ableton.

## Project structure

```
headless-orchestra/
├── api-layer/                  # frozen (Producer Pal client, not used)
├── agents/
│   ├── agents/
│   │   ├── domain.py               # neutral core model + windowed()/pitch_name()
│   │   ├── adapters/
│   │   │   ├── ableton.py          # Ableton Live adapter (all DAW specifics)
│   │   │   └── midi_file.py        # .mid file adapter (mido, raw ticks)
│   │   ├── chord_grouping.py       # onset clustering, anticipation
│   │   ├── functional_labeling.py  # key, roman numerals, T-S-D, tonal mode
│   │   ├── harmony_pipeline.py     # deterministic pipeline + Claude reasoning call
│   │   ├── live_bridge.py          # read-only bridge client (mcp-server-ableton-live)
│   │   ├── mcp_server.py           # MCP tools find_midi_clips / analyze_clip
│   │   ├── rhythm_analyzer.py      # deterministic rhythm analysis
│   │   └── skills/harmony_theory.md      # theory knowledge base for the LLM
│   ├── scripts/analyze_midi_file.py      # offline harness
│   └── tests/                  # unit tests + synthetic MIDI fixtures (tests/midi/)
└── docs/
    ├── VISION.md, ARCHITECTURE.md, AI_AGENTS_GUIDE.md
    ├── rhythm_analyzer_notes.md
    ├── specs/                  # implementation specs
    ├── producer-pal/           # Producer Pal API reference
    └── ableton-extensions-sdk/ # local copy of the SDK beta + docs
```

## Running

Requires Python 3.11+ and Poetry 2.x (use `poetry run`; there is no `poetry shell`).

```bash
# Install (from agents/)
cd agents && poetry install

# Tests
poetry run pytest -v

# Offline harmony analysis of a .mid file (from agents/)
poetry run python scripts/analyze_midi_file.py FILE.mid [--track N] [--with-llm] [--json]
```

`--with-llm` needs `ANTHROPIC_API_KEY`. Live workflows need Ableton with the
`mcp-server-ableton-live` bridge running on TCP 127.0.0.1:9877.

## MCP server (Claude Desktop)

`agents/agents/mcp_server.py` exposes a read-only MCP server with two tools —
`find_midi_clips` and `analyze_clip`. It reads clip data from Live through the
`mcp-server-ableton-live` bridge (Remote Script, TCP `127.0.0.1:9877`) and runs the
deterministic pipelines locally, so raw notes never pass through the LLM context.

Prerequisites:

1. Install the bridge: `uvx mcp-server-ableton-live@1.8.1 install --replace`.
2. In Live: Settings → Tempo & MIDI, select the Control Surface `AbletonMCP`
   (a modal dialog open in Live blocks the bridge).
3. From `agents/`, get the Python path of the poetry env: `poetry env info --path`.

Then add a server entry to `claude_desktop_config.json` → `mcpServers`:

```json
{
  "mcpServers": {
    "headless-orchestra": {
      "command": "<poetry-env-path>/Scripts/python.exe",
      "args": ["-m", "agents.mcp_server"]
    }
  }
}
```

On Windows the `<poetry-env-path>` looks like
`C:\Users\<user>\AppData\Local\pypoetry\Cache\virtualenvs\agents-<hash>-py3.x`.

Alternatively use the installed console script `ho-mcp`
(`"command": "<poetry-env-path>\Scripts\ho-mcp.exe"`, no `args`). The bridge host and
port can be overridden with the `ABLETON_HOST` / `ABLETON_PORT` environment variables.

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

- [mcp-server-ableton-live](https://github.com/Simon-Kansara/mcp-server-ableton-live): bridge to Ableton Live
- [music21](https://web.mit.edu/music21/), [mido](https://mido.readthedocs.io/), [LangGraph](https://github.com/langchain-ai/langgraph)
