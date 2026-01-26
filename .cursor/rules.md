# Cursor Rules for Headless Orchestra

## Code Style
- Always use type hints (Python 3.11+ syntax)
- Use Pydantic for all data models
- Docstrings in Google style
- pytest for all tests
- Keep functions small and focused

## Producer Pal Integration

Producer Pal MCP server runs at `http://localhost:3350/mcp`

### API Call Pattern
```python
import requests

response = requests.post(
    "http://localhost:3350/mcp",
    json={
        "method": "tools/call",
        "params": {
            "name": "ppal-{tool-name}",
            "arguments": {...}
        }
    }
)
```

### Key Tools
- `ppal-read-live-set` - Get project info
- `ppal-read-track` - Get track details
- `ppal-create-clip` - Create MIDI clip
- `ppal-read-clip` - Read clip notes

### Note Format
```python
{
    "pitch": "C3",      # Middle C
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
- `tests/` - pytest tests

### agents/
LangGraph AI agents for music analysis.
- `agents/harmony/` - Harmony analyzer
- `agents/rhythm/` - Rhythm analyzer
- `agents/skills/` - Music theory knowledge base (markdown)
- `tests/` - Agent tests

### shared/
Common types and utilities used by both api-layer and agents.

## Development Workflow

1. Write tests first (TDD)
2. Implement minimal code to pass tests
3. Refactor with type safety
4. Document in docstrings

## Testing Guidelines

- Mock external dependencies (Producer Pal, LLM APIs)
- Test both success and error cases
- Use fixtures for common test data
