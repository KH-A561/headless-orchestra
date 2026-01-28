"""Producer Pal API client."""

from typing import List

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

from api_layer.models import Clip, Note, Track


class ProducerPalClient:
    """Client for interacting with Producer Pal API.

    This client provides methods to communicate with the Producer Pal service
    running on a specified base URL. It handles tool calls and error handling.
    
     TODO (Phase 3+): Consider migration to official MCP Python SDK
    
    Current implementation uses manual HTTP + parsing for simplicity and control.
    When to migrate:
    - Phase 3+ when multi-agent system requires advanced MCP features
    - If Producer Pal fixes JavaScript object notation (unquoted keys)
    - When we need to integrate with multiple MCP servers
    
    MCP SDK would handle:
    - SSE parsing (Layer 1) ✓
    - MCP content extraction (Layer 2) ✓
    - But NOT JavaScript notation conversion (Layer 3) - still needed
    
    Migration effort: ~2-3 hours (convert to async API)
    Benefit: Protocol updates, better error handling, community support
    
    References:
    - MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
    - Decision rationale: docs/ARCHITECTURE.md#why-manual-parsing
    """

    def __init__(self, base_url: str = "http://localhost:3350") -> None:
        """Initialize Producer Pal client.

        Args:
            base_url: Base URL of the Producer Pal API server.
                Defaults to "http://localhost:3350".
        """
        self.base_url = base_url.rstrip("/")

    def _parse_sse(self, sse_text: str) -> dict:
        """Parse Server-Sent Events format."""
        import json

        lines = sse_text.strip().split("\n")
        for line in lines:
            if line.startswith("data: "):
                return json.loads(line[6:])
        raise ValueError("No data in SSE response")

    def _parse_js_object(self, js_text: str) -> dict:
        """Convert JavaScript object notation to proper JSON."""
        import json
        import re

        # Add quotes to unquoted keys: {id:"1"} → {"id":"1"}
        json_text = re.sub(r"(\w+):", r'"\1":', js_text)
        return json.loads(json_text)

    def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a Producer Pal tool with given arguments.

        NOTE: Manual 3-layer parsing (SSE → MCP → JS notation)
        This could be replaced with MCP SDK in Phase 3+.
        See class docstring for migration considerations.
        
        Args:
            tool_name: Name of the tool to call (e.g., "ppal-read-live-set").
            arguments: Dictionary of arguments to pass to the tool.

        Returns:
            Dictionary containing the tool's response.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
            ValueError: If the JSON-RPC response contains an error object.
        """
        url = f"{self.base_url}/mcp"
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": 1,
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=30,
            )
            response.raise_for_status()

            # Layer 1: Parse SSE
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                json_rpc_response = self._parse_sse(response.text)
            else:
                json_rpc_response = response.json()

            # Check for error
            if isinstance(json_rpc_response, dict) and json_rpc_response.get("error"):
                raise ValueError(f"JSON-RPC error: {json_rpc_response['error']}")

            # Layer 2: Extract MCP content
            result = json_rpc_response.get("result", {}) if isinstance(json_rpc_response, dict) else {}
            content = result.get("content", [])

            if content and len(content) > 0 and content[0].get("type") == "text":
                # Layer 3: Parse JS object
                js_text = content[0].get("text", "{}")
                return self._parse_js_object(js_text)

            return result
        except RequestsConnectionError as e:
            raise ConnectionError(
                f"Failed to connect to Producer Pal API at {self.base_url}: {e}"
            ) from e

    def get_project_info(self) -> dict:
        """Get information about the current Live Set project.

        Calls the ppal-read-live-set tool to retrieve project information.

        Returns:
            Dictionary containing project information including tracks,
            structure, and general project parameters.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
        """
        return self._call_tool("ppal-read-live-set", {})

    def get_track(self, track_id: int) -> Track:
        """Get information about a specific track.

        Calls the ppal-read-track tool to retrieve track details.

        Args:
            track_id: Identifier of the track to retrieve.

        Returns:
            Track model containing track information including clips.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
            pydantic.ValidationError: If the response cannot be parsed into Track model.
        """
        data = self._call_tool("ppal-read-track", {"trackId": track_id})
        return Track.model_validate(data)

    def create_midi_clip(self, track_id: int, notes: List[Note]) -> Clip:
        """Create a new MIDI clip on the specified track.

        Calls the ppal-create-clip tool to create a clip with the given notes.

        Args:
            track_id: Identifier of the track to create the clip on.
            notes: List of Note objects to include in the clip.

        Returns:
            Clip model containing information about the created clip.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
            pydantic.ValidationError: If the response cannot be parsed into Clip model.
        """
        arguments = {
            "trackId": track_id,
            "notes": [note.model_dump() for note in notes],
        }
        data = self._call_tool("ppal-create-clip", arguments)
        return Clip.model_validate(data)

    def get_clip(self, track_id: int, clip_id: int) -> Clip:
        """Get information about a specific clip including its notes.

        Calls the ppal-read-clip tool to retrieve clip details.

        Args:
            track_id: Identifier of the track containing the clip.
            clip_id: Identifier of the clip to retrieve.

        Returns:
            Clip model containing clip information including notes.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
            pydantic.ValidationError: If the response cannot be parsed into Clip model.
        """
        data = self._call_tool(
            "ppal-read-clip", {"trackId": track_id, "clipId": clip_id}
        )
        return Clip.model_validate(data)
