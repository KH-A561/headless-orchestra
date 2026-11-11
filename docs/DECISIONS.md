# Architecture decisions

Short records of decisions that shape the project. Newest first.

## Open questions

Deferred on purpose; each has a trigger for when to come back to it.

- **Time representation: float quarters vs exact rationals.** Floats cannot represent 1/3 exactly.
  Analyzers use tolerances, so this is fine for now. *Revisit when:* we need comparison against an
  exact grid (e.g. "ideal" triplets) or accumulated rounding shows up in long clips.
- **Pitch: 12-TET MIDI int vs tunings / microtonality / MPE.** `pitch: int` cannot express Live 12
  tuning systems, MPE or pitch bend. *Revisit when:* the first real clip uses a tuning system,
  MPE or meaningful pitch bend. Deserves a dedicated deep dive.
- **Single tempo per clip** (no tempo map). *Revisit when:* a clip with tempo automation matters.

## 2026-11-11 — Libraries stay behind boundaries too

**Decision.** Third-party libraries are treated like DAWs: the core owns its model, libraries live
inside the component that uses them and convert at its edges.

- The core time unit is the **quarter note** because it is the common denominator of formats and
  DAWs (MIDI PPQ, MusicXML divisions, Live beats, Reaper QN, Bitwig beats) — not because a
  particular library uses it.
- music21 lives inside the harmony analyzer. Its `quarterLength`, `Fraction`s and octave numbering
  (C4 = 60) never leave that module. Replacing music21 must touch one analyzer, not the core.
- Pitch *names* are presentation: the core uses MIDI numbers; naming is a setting
  (`scientific`, C4 = 60, default; `ableton`, C3 = 60).

## 2026-11-11 — DAW-agnostic core with adapters

**Decision.** The core (analyzers, listening-loop graph, chat backend) depends only on a neutral
domain model and a DAW adapter interface. Everything DAW-specific lives inside an adapter.

- **Domain model** (neutral, no DAW conventions): `NoteEvent` (MIDI pitch int, start/duration in
  beats as float, velocity, probability, mute), `ClipData` (notes, analysis window, time signature,
  tempo), `PadMap` (note → name), `AudioRegion` (file path, start/end in seconds, sample rate).
- **Adapter interface:** `list_clips(query)`, `read_clip(ref, region)`, `read_pad_map(ref)`,
  `read_audio_region(ref, start, end)`.
- **Adapters:** Ableton Live (via the `mcp-server-ableton-live` Remote Script bridge) — first;
  File adapter (`.mid` / `.wav`, today's offline harness) — works with any DAW that can export.
  Later candidates: Reaper (ReaScript), Bitwig (Controller API).
- Ableton conventions (C3 = 60, `bar|beat` strings, `loop_start`, `DrumGroupDevice`) stay inside
  the Ableton adapter.

**Known debt.** Analyzers currently take `api_layer.models.Note` (Producer Pal client model,
Ableton pitch strings, `bar|beat` strings), and `clip_source.py` is Ableton-specific while acting
as the core. Both move behind the adapter boundary.

## 2026-11-11 — Two modes: development vs product

- **Development mode:** Claude in Claude Desktop + the `headless-orchestra` MCP server, used to
  inspect the DAW and test analyzers on real material. Stays as a dev/test harness.
- **Product mode:** the user opens their DAW and a small chat window. A LangGraph graph runs the
  listening loop (see `LISTENING_LOOP.md`) with an LLM as the reasoning node inside; the human
  answers via `interrupt()`. No Claude Desktop involved.
- The LLM provider must be swappable (user's own API key or a local model) — required, not optional.

## 2026-11-11 — Chat UI: standalone window, not inside the DAW

**Decision.** The chat is a standalone small window (local web page served by the graph's HTTP
backend; browser or a thin desktop wrapper, always-on-top next to the DAW).

**Rejected:** Max for Live `jweb` device and Ableton Extensions SDK webview — both tie the UI to one
DAW (and to Suite / Max for Live / a beta). Extensions webviews are also modal, which blocks the
DAW during the listen → answer → bounce cycle.

## 2026-11-10 — Bridge to Live: `mcp-server-ableton-live`, not Producer Pal / Extensions SDK

**Decision.** Read data from Live through the `mcp-server-ableton-live` Remote Script
(TCP 127.0.0.1:9877), using our own minimal read-only client (`live_bridge.py`, command whitelist).

- Producer Pal: not used; `api-layer` is frozen.
- Extensions SDK: no pad names in 1.0.0-beta (no `DrumChain.name`), no song time signature,
  not designed as a persistent bridge; Suite beta only.
- Bounce (render) is not in the Live API: the human bounces the fragment to listen to — this is
  part of the listening loop, not a workaround.
