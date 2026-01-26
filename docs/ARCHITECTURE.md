# Architecture Documentation

## Overview

Headless Orchestra implements a three-layer architecture designed for extensibility, testability, and DAW-agnosticism:

1. **AI Agents Layer** — Music-intelligent agents (LangGraph-based)
2. **API Abstraction Layer** — DAW-agnostic normalized interface
3. **DAW Bridge Layer** — Protocol-specific adapters (currently: Producer Pal MCP)

This design allows swapping DAW bridges without changing agent code, and adding new agents without touching infrastructure.

## System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      AI Agents Layer                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │ HarmonyAnalyzer│  │ RhythmAnalyzer │  │ Orchestrator   │     │
│  │                │  │                │  │                │     │
│  │ - Analyze      │  │ - Detect       │  │ - Coordinate   │     │
│  │   harmony      │  │   rhythm       │  │   agents       │     │
│  │ - Suggest      │  │   patterns     │  │ - Manage       │     │
│  │   corrections  │  │ - Fix timing   │  │   workflow     │     │
│  │ - Apply theory │  │ - Quantize     │  │ - Prioritize   │     │
│  └────────────────┘  └────────────────┘  └────────────────┘     │
│         │                    │                    │              │
│         └────────────────────┴────────────────────┘              │
│                              │                                   │
│                    ┌─────────▼──────────┐                        │
│                    │  LangGraph State   │                        │
│                    │  Management        │                        │
│                    └─────────┬──────────┘                        │
└──────────────────────────────┼───────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Skills (Markdown)  │
                    │  - harmony_theory   │
                    │  - rhythm_patterns  │
                    │  - orchestration    │
                    └──────────┬──────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                   API Abstraction Layer                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  ProducerPalClient                       │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │   │
│  │  │ get_project │  │  get_track  │  │ create_clip │     │   │
│  │  │    _info    │  │             │  │             │     │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘     │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Pydantic Models                             │   │
│  │  Note │ Clip │ Track │ ProjectInfo                      │   │
│  │  - Type safety                                           │   │
│  │  - Validation                                            │   │
│  │  - Serialization                                         │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTP/JSON
┌──────────────────────────────▼───────────────────────────────────┐
│                     DAW Bridge Layer                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Producer Pal (MCP Server)                   │   │
│  │  - Max for Live device (.amxd)                           │   │
│  │  - Node for Max runtime                                  │   │
│  │  - HTTP server (port 3350)                               │   │
│  │  - MCP protocol implementation                           │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬───────────────────────────────────┘
                               │ Max Messages
┌──────────────────────────────▼───────────────────────────────────┐
│                        Ableton Live                               │
│  - Live API (Python)                                              │
│  - MIDI/Audio tracks                                              │
│  - Clips, devices, parameters                                     │
└───────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. AI Agents Layer

**Purpose:** Provide music-intelligent decision making and automation.

**Key Components:**

#### HarmonyAnalyzer (Planned)
```python
class HarmonyAnalyzer:
    """Analyzes harmonic content and suggests corrections."""
    
    async def analyze_clip(self, clip: Clip) -> HarmonyAnalysis:
        """Analyze harmony in MIDI clip."""
        # - Extract note pitches
        # - Identify key/scale
        # - Detect chord progressions
        # - Find dissonances
        # - Suggest corrections
        
    async def apply_correction(self, clip: Clip, correction: HarmonicCorrection):
        """Apply harmonic correction to clip."""
```

#### RhythmAnalyzer (Planned)
```python
class RhythmAnalyzer:
    """Analyzes rhythmic patterns and timing."""
    
    async def analyze_timing(self, clip: Clip) -> RhythmAnalysis:
        """Analyze rhythmic structure."""
        # - Detect time signature
        # - Find syncopation
        # - Identify swing/groove
        # - Detect timing errors
        
    async def quantize_intelligent(self, clip: Clip, strength: float):
        """Quantize with musical intelligence."""
```

#### Orchestrator (Planned)
```python
class Orchestrator:
    """Coordinates multiple agents in workflows."""
    
    async def analyze_project(self, project: ProjectInfo):
        """Run multi-agent analysis."""
        # - Delegate to specialized agents
        # - Aggregate results
        # - Prioritize corrections
        # - Execute changes
```

**Technology Stack:**
- **LangGraph** — Agent state management and workflow orchestration
- **Claude API** — LLM for music reasoning
- **Skills** — Markdown files with music theory knowledge

**Skills Format:**
```markdown
# Harmony Analysis Skill

## Key Detection
...music theory rules...

## Chord Recognition
...chord patterns...

## Common Progressions
...progressions database...
```

---

### 2. API Abstraction Layer

**Purpose:** Provide DAW-agnostic, type-safe interface to underlying DAW bridges.

**Status:** ✅ **IMPLEMENTED & TESTED**

**Key Components:**

#### ProducerPalClient
HTTP client for Producer Pal MCP server.

```python
class ProducerPalClient:
    """Client for Producer Pal MCP API.
    
    Handles:
    - HTTP communication
    - Error handling
    - Response parsing
    - Type conversion
    """
    
    def __init__(self, base_url: str = "http://localhost:3350")
    def _call_tool(self, tool_name: str, arguments: dict) -> dict
    def get_project_info(self) -> dict
    def get_track(self, track_id: int) -> Track
    def create_midi_clip(self, track_id: int, notes: List[Note]) -> Clip
    def get_clip(self, track_id: int, clip_id: int) -> Clip
```

**Design Decisions:**

1. **Private `_call_tool` method** — Single point for all MCP communication
2. **Public methods return Pydantic models** — Type safety and validation
3. **Connection errors wrapped** — Consistent error handling
4. **Stateless client** — No session management, safe for concurrent use

#### Pydantic Models

Type-safe data models with validation:

```python
class Note(BaseModel):
    """MIDI note with bar|beat notation."""
    pitch: str           # "C3", "F#4", "Bb2"
    start: str           # "1|1" (bar|beat)
    duration: str        # "1:0" (bars:beats)
    velocity: int        # 0-127
    probability: float   # 0.0-1.0
    
    # Validators ensure correct format
    @field_validator("start")
    def validate_start_format(cls, v: str) -> str: ...

class Clip(BaseModel):
    """MIDI clip container."""
    id: int
    name: str
    notes: List[Note]
    length: str  # "4:0"

class Track(BaseModel):
    """Track with clips."""
    id: int
    name: str
    clips: List[Clip]

class ProjectInfo(BaseModel):
    """Project metadata."""
    tempo: float
    tracks: List[Track]
```

**Validation Benefits:**

- ✅ Catches format errors before sending to DAW
- ✅ Provides clear error messages
- ✅ Enables IDE autocomplete
- ✅ Documents expected data structure

#### Testing Strategy

**Unit Tests** (pytest + pytest-mock):
- Mock HTTP requests
- Test error handling
- Validate model serialization
- Ensure correct API calls

**Integration Tests**:
- Test against running Producer Pal
- Verify real data parsing
- Check end-to-end workflow

---

### 3. DAW Bridge Layer

**Purpose:** Translate normalized API calls to DAW-specific protocols.

**Current Implementation:** Producer Pal (MCP Server)

#### Producer Pal Architecture

```
┌─────────────────────────────────────┐
│  Max for Live Device (.amxd)        │
│  ┌───────────────────────────────┐  │
│  │  Node for Max (V8 Engine)    │  │
│  │  ┌─────────────────────────┐ │  │
│  │  │  Express.js HTTP Server │ │  │
│  │  │  (port 3350)            │ │  │
│  │  └─────────────────────────┘ │  │
│  │  ┌─────────────────────────┐ │  │
│  │  │  MCP Server (TypeScript)│ │  │
│  │  │  - Zod validation       │ │  │
│  │  │  - Tool definitions     │ │  │
│  │  └─────────────────────────┘ │  │
│  └───────────────────────────────┘  │
│           ↕ Max Messages            │
│  ┌───────────────────────────────┐  │
│  │  Max Patcher (visual)         │  │
│  │  - Live API interface         │  │
│  │  - Message routing            │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
            ↕ Live API
┌─────────────────────────────────────┐
│       Ableton Live (Python API)     │
└─────────────────────────────────────┘
```

**MCP Protocol:**

```json
POST http://localhost:3350/mcp
{
  "method": "tools/call",
  "params": {
    "name": "ppal-read-live-set",
    "arguments": {}
  }
}

Response:
{
  "tempo": 120.0,
  "tracks": [...]
}
```

**Why Producer Pal:**
1. ✅ HTTP API — language-agnostic, easy to wrap
2. ✅ Feature-rich — comprehensive Ableton Live coverage
3. ✅ TypeScript + Zod — production robustness
4. ✅ Well documented — official website, examples
5. ✅ Open source (MIT) — can extend if needed

**Alternative DAW Bridges (Future):**

To support other DAWs, implement new bridge adapters:

```python
class LogicProClient:
    """Future: Logic Pro via custom bridge."""
    def get_project_info(self) -> dict: ...
    
class FL_StudioClient:
    """Future: FL Studio via MIDI Script."""
    def get_project_info(self) -> dict: ...
```

Agents remain unchanged — they only use the normalized API.

---

## Data Flow Examples

### Example 1: Get Project Information

```
Agent                API Layer           DAW Bridge          Ableton
  │                     │                    │                 │
  │ get_project_info()  │                    │                 │
  ├────────────────────>│                    │                 │
  │                     │ POST /mcp          │                 │
  │                     │ ppal-read-live-set │                 │
  │                     ├───────────────────>│                 │
  │                     │                    │ Live.Song.tempo │
  │                     │                    ├────────────────>│
  │                     │                    │<────────────────┤
  │                     │                    │ track.name      │
  │                     │                    ├────────────────>│
  │                     │<───────────────────┤                 │
  │                     │ JSON response      │                 │
  │<────────────────────┤                    │                 │
  │ ProjectInfo model   │                    │                 │
```

### Example 2: Create MIDI Clip

```
Agent                API Layer           DAW Bridge          Ableton
  │                     │                    │                 │
  │ create_midi_clip()  │                    │                 │
  │ [Note(C3), ...]     │                    │                 │
  ├────────────────────>│                    │                 │
  │                     │ Validate notes     │                 │
  │                     │ (Pydantic)         │                 │
  │                     │                    │                 │
  │                     │ POST /mcp          │                 │
  │                     │ ppal-create-clip   │                 │
  │                     ├───────────────────>│                 │
  │                     │                    │ track.create()  │
  │                     │                    ├────────────────>│
  │                     │                    │ clip.set_notes()│
  │                     │                    ├────────────────>│
  │                     │<───────────────────┤                 │
  │<────────────────────┤                    │                 │
  │ Clip model          │                    │                 │
```

### Example 3: Multi-Agent Harmony Analysis

```
Orchestrator         HarmonyAnalyzer     API Layer         Ableton
  │                       │                  │                │
  │ analyze_project()     │                  │                │
  ├──────────────────────>│                  │                │
  │                       │ get_clip()       │                │
  │                       ├─────────────────>│                │
  │                       │                  ├───────────────>│
  │                       │<─────────────────┤                │
  │                       │ Clip with notes  │                │
  │                       │                  │                │
  │                       │ Analyze with     │                │
  │                       │ Claude API       │                │
  │                       │ + Music Theory   │                │
  │                       │ Skills           │                │
  │                       │                  │                │
  │<──────────────────────┤                  │                │
  │ HarmonyAnalysis       │                  │                │
  │ (corrections needed)  │                  │                │
```

---

## Error Handling

### API Layer Error Hierarchy

```
Exception
├─ ConnectionError              # Producer Pal not reachable
├─ requests.HTTPError           # HTTP 4xx/5xx errors
└─ pydantic.ValidationError     # Invalid data format
```

### Error Propagation

```python
# API Layer catches and wraps errors
try:
    response = requests.post(url, json=payload)
    response.raise_for_status()
except RequestsConnectionError as e:
    raise ConnectionError(
        f"Failed to connect to Producer Pal API at {self.base_url}: {e}"
    ) from e

# Agents handle gracefully
try:
    project = client.get_project_info()
except ConnectionError:
    logger.error("Producer Pal not running")
    # Fallback or user notification
```

---

## Scalability Considerations

### Current Limitations

1. **Single DAW support** — Only Ableton Live via Producer Pal
2. **Synchronous API** — Blocking HTTP calls
3. **No caching** — Every call hits DAW
4. **No batch operations** — One note at a time

### Future Improvements

1. **Async API Layer**
```python
class AsyncProducerPalClient:
    async def get_track(self, track_id: int) -> Track:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return Track.model_validate(await resp.json())
```

2. **Caching Layer**
```python
@lru_cache(maxsize=128)
def get_track(self, track_id: int) -> Track:
    # Cache track info for performance
```

3. **Batch Operations**
```python
def create_clips_batch(self, clips: List[ClipCreate]) -> List[Clip]:
    # Single HTTP call for multiple clips
```

---

## Testing Strategy

### Test Pyramid

```
         ┌─────────────┐
         │ Integration │  ← Few (test_integration.py)
         │   Tests     │     Real Producer Pal
         └─────────────┘
       ┌───────────────────┐
       │   API Layer       │  ← Many (test_client.py)
       │   Unit Tests      │     Mocked HTTP
       └───────────────────┘
     ┌───────────────────────┐
     │  Model Validation     │  ← Many (test_models.py, planned)
     │  Tests                │     Pydantic validators
     └───────────────────────┘
```

### Test Coverage Goals

- **API Layer:** 100% coverage of public methods
- **Models:** 100% coverage of validators
- **Agents:** 80%+ coverage (AI logic harder to test)

---

## Performance Characteristics

### API Layer Latency

| Operation | Latency | Notes |
|-----------|---------|-------|
| `get_project_info()` | ~50-100ms | Network + JSON parsing |
| `get_track()` | ~30-50ms | Single HTTP call |
| `create_midi_clip()` | ~100-200ms | Depends on note count |

### Bottlenecks

1. **HTTP round-trips** — Each API call = 1 network request
2. **Ableton Live API** — Single-threaded Python in Max for Live
3. **JSON serialization** — Large projects = large JSON payloads

### Optimization Strategies

1. Batch operations where possible
2. Cache static data (track names, etc.)
3. Use async for parallel agent workflows
4. Consider WebSocket for real-time updates (future)

---

## Security Considerations

### Current Security Model

- **Local-only communication** — HTTP to localhost:3350
- **No authentication** — Assumes trusted local environment
- **No encryption** — Plain HTTP (not HTTPS)

### Production Considerations (Future)

If exposing over network:

1. **Authentication** — API keys or OAuth
2. **Encryption** — HTTPS/TLS
3. **Rate limiting** — Prevent abuse
4. **Input validation** — Already have Pydantic (✅)

---

## Development Workflow

### Adding New API Method

1. **Define Pydantic model** (if needed)
```python
class NewModel(BaseModel):
    field: type
```

2. **Add method to client**
```python
def new_method(self, arg: Type) -> NewModel:
    response = self._call_tool("ppal-new-tool", {"arg": arg})
    return NewModel.model_validate(response)
```

3. **Write unit test**
```python
def test_new_method(client, mocker):
    mock_response = {...}
    mocker.patch("requests.post", return_value=mock_response)
    result = client.new_method(arg)
    assert isinstance(result, NewModel)
```

4. **Update integration test**
```python
print("\nTesting new_method()...")
result = client.new_method(arg)
print(f"  ✓ Result: {result}")
```

---

## Technology Stack Summary

| Layer | Technologies |
|-------|-------------|
| **AI Agents** | LangGraph, Claude API, Python 3.11+ |
| **API Layer** | Pydantic, requests, pytest |
| **DAW Bridge** | Producer Pal (TypeScript, Node for Max) |
| **DAW** | Ableton Live (Python API) |
| **Dev Tools** | Poetry, pytest, black, mypy, ruff, Cursor IDE |

---

## Conclusion

This architecture provides:

1. ✅ **Separation of concerns** — AI logic separate from DAW communication
2. ✅ **Testability** — Mocking at API boundary
3. ✅ **Type safety** — Pydantic models catch errors early
4. ✅ **Extensibility** — Easy to add new agents or DAW bridges
5. ✅ **Maintainability** — Clear component boundaries

The current implementation (API Layer) provides a solid foundation for building intelligent music production agents.
