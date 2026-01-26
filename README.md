# Headless Orchestra

AI-powered music production agents for Ableton Live with deep musical intelligence.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Poetry](https://img.shields.io/badge/poetry-1.8+-purple.svg)](https://python-poetry.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 🎯 Vision

Headless Orchestra is an AI agent platform that brings **musical intelligence** to DAW automation. Unlike existing MCP servers that only execute commands, Headless Orchestra provides:

- 🎼 **Deep music analysis** — harmony, rhythm, orchestration understanding
- 🤖 **Multi-agent orchestration** — specialized agents working together
- 🎵 **Music theory knowledge** — contextual corrections based on music principles
- 🔊 **Audio analysis** — spectral, timbral, and structural analysis
- 🔄 **DAW-agnostic design** — abstraction layer for future multi-DAW support

**Current Focus:** Ableton Live via Producer Pal MCP bridge

See [docs/VISION.md](docs/VISION.md) for full project vision.

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│   Headless AI Agents (LangGraph)        │
│   ├─ HarmonyAnalyzer (planned)          │
│   ├─ RhythmAnalyzer (planned)           │
│   └─ OrchestrationAgent (planned)       │
└─────────────────────────────────────────┘
            ↓ Normalized API
┌─────────────────────────────────────────┐
│   API Abstraction Layer (✅ READY)      │
│   - ProducerPalClient                   │
│   - Pydantic models with validation     │
│   - Type-safe interface                 │
└─────────────────────────────────────────┘
            ↓ HTTP (MCP protocol)
┌─────────────────────────────────────────┐
│   Producer Pal (MCP Bridge)             │
│   - Max for Live device                 │
│   - HTTP server on port 3350            │
└─────────────────────────────────────────┘
            ↓ Max Messages
┌─────────────────────────────────────────┐
│   Ableton Live                          │
└─────────────────────────────────────────┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture documentation.

## 📦 Project Structure

```
headless-orchestra/
├── api-layer/              # API Abstraction Layer (✅ READY)
│   ├── api_layer/
│   │   ├── client.py      # ProducerPalClient
│   │   └── models.py      # Pydantic models
│   └── tests/             # Unit tests (pytest + mocking)
│
├── agents/                 # AI Agents (planned)
│   ├── agents/
│   │   └── skills/        # Music theory knowledge base
│   └── tests/
│
├── shared/                 # Common utilities
│   └── shared/
│
├── docs/                   # Documentation
│   ├── ARCHITECTURE.md    # Architecture details
│   ├── VISION.md          # Project vision & goals
│   └── producer-pal/      # Producer Pal API reference
│
└── .cursor/               # Cursor IDE rules
    └── rules.md
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/) for dependency management
- Ableton Live (for integration testing)
- Producer Pal Max for Live device

### Installation

```bash
# Clone repository
git clone <your-repo-url>
cd headless-orchestra

# Install dependencies (uses Poetry workspace)
poetry install

# Run unit tests
cd api-layer
poetry run pytest tests/ -v
```

### Integration Test

```bash
# 1. Start Ableton Live
# 2. Load Producer Pal Max for Live device
# 3. Ensure Producer Pal shows "Server running on port 3350"

# Run integration test
cd api-layer
poetry run python test_integration.py
```

## 💻 Usage Example

```python
from api_layer.client import ProducerPalClient
from api_layer.models import Note

# Initialize client
client = ProducerPalClient()

# Get project information
project = client.get_project_info()
print(f"Tempo: {project['tempo']} BPM")

# Get track details
track = client.get_track(track_id=0)
print(f"Track name: {track.name}")

# Create MIDI clip with chord
notes = [
    Note(pitch="C3", start="1|1", duration="1:0", velocity=80),
    Note(pitch="E3", start="1|1", duration="1:0", velocity=80),
    Note(pitch="G3", start="1|1", duration="1:0", velocity=80),
]
clip = client.create_midi_clip(track_id=0, notes=notes)
print(f"Created clip: {clip.name}")
```

## 🧪 Testing

### Unit Tests

```bash
cd api-layer
poetry run pytest tests/ -v           # All tests
poetry run pytest tests/ -v -k track  # Tests matching "track"
poetry run pytest tests/ --cov        # With coverage
```

### Integration Tests

```bash
cd api-layer
poetry run python test_integration.py
```

## 🛠️ Development

### Setup Development Environment

```bash
# Install all dev dependencies
poetry install

# Activate virtual environment (Poetry 2.0+)
poetry run python  # Prefix commands with 'poetry run'

# Or activate manually
# Windows: <poetry-env-path>\Scripts\Activate.ps1
# Find path: poetry env info --path
```

### Code Style

```bash
# Format code
poetry run black api-layer/ agents/ shared/

# Type checking
poetry run mypy api-layer/

# Linting
poetry run ruff check api-layer/
```

### Cursor IDE

This project uses Cursor AI IDE with custom rules defined in `.cursor/rules.md`. Key patterns:

- Type hints everywhere (Python 3.11+ syntax)
- Pydantic for all data models
- pytest + mocking for tests
- Google-style docstrings

## 📚 Documentation

- [Architecture Overview](docs/ARCHITECTURE.md) — System design and component interaction
- [Project Vision](docs/VISION.md) — Goals, motivation, and roadmap
- [Producer Pal API Reference](docs/producer-pal/api-reference.md) — MCP bridge API documentation

## 🗺️ Roadmap

### Phase 1: Foundation (✅ COMPLETED)
- [x] Project structure setup
- [x] API Layer implementation
- [x] Pydantic models with validation
- [x] Unit tests with mocking
- [x] Integration test skeleton

### Phase 2: First AI Agent (In Progress)
- [ ] HarmonyAnalyzer agent implementation
- [ ] Claude API integration
- [ ] Music theory skills (markdown knowledge base)
- [ ] Agent testing framework

### Phase 3: Multi-Agent System
- [ ] LangGraph integration
- [ ] Agent orchestration
- [ ] State management
- [ ] Multi-agent workflows

### Phase 4: Advanced Features
- [ ] Audio analysis capabilities
- [ ] Real-time MIDI processing
- [ ] Extended music theory reasoning
- [ ] Performance optimization

## 🤝 Contributing

This is currently a personal research project. Contribution guidelines will be added once the project matures.

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Producer Pal](https://producer-pal.org) by Adam Murray — MCP bridge for Ableton Live
- [Anthropic](https://anthropic.com) — Claude API and MCP protocol
- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent orchestration framework

## 📞 Contact

Alexander — Senior Java Backend Developer exploring AI in music production

---

**Status:** Phase 1 Complete ✅ | API Layer Ready | Agent Development Starting Soon
