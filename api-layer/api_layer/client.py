"""Producer Pal API client."""

import json
import re
from typing import List

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

from api_layer.models import Clip, Note, Track


def parse_notes_string(notes_str: str) -> list[dict]:
    """Парсит строку notes из Producer Pal в список словарей для модели Note.

    Формат Producer Pal: "C3 E3 G3 1|1 E3 G3 B3 1|2 t2 D4 1|2.998" — pitch'и подряд,
    затем позиция bar|beat; модификаторы (например t2) пропускаются.

    Args:
        notes_str: Строка вида "C3 E3 G3 1|1 E3 1|2"

    Returns:
        Список словарей с ключами pitch, start, duration, velocity для Note.
    """
    if not notes_str or not notes_str.strip():
        return []
    tokens = notes_str.strip().split()
    result: list[dict] = []
    current_pitches: list[str] = []
    default_duration = "1:0"
    default_velocity = 80

    for token in tokens:
        if "|" in token:
            # Позиция start (bar|beat); все накопленные pitch'и относятся к ней
            start = token
            for pitch in current_pitches:
                result.append({
                    "pitch": pitch,
                    "start": start,
                    "duration": default_duration,
                    "velocity": default_velocity,
                })
            current_pitches = []
        elif len(token) > 1 and token[0] == "t" and token[1:].isdigit():
            # Модификатор (t2 и т.д.) — пока пропускаем
            continue
        else:
            # Считаем токен pitch'ем (C3, E3, G#4 и т.д.)
            current_pitches.append(token)

    return result


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

    def _extract_json_from_sse(self, sse_text: str) -> dict:
        """Layer 1: Extract JSON from SSE format (event: message\\ndata: {...})."""
        if not sse_text or not sse_text.strip():
            raise ValueError("Empty SSE response")
        for line in sse_text.strip().split("\n"):
            if line.startswith("data: "):
                json_str = line[6:].strip()
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    print(f"[DEBUG] SSE data line (first 300 chars): {json_str[:300]}")
                    raise ValueError(f"Invalid JSON in SSE data: {e}") from e
        print(f"[DEBUG] No 'data: ' line in SSE. Lines: {[l[:80] for l in sse_text.strip().split(chr(10))[:5]]}")
        raise ValueError("No 'data: ' line in SSE response")

    def _js_notation_to_json(self, js_text: str) -> dict:
        """Layer 3: Convert JavaScript notation (unquoted keys) to valid JSON."""
        if not js_text or not js_text.strip():
            raise ValueError("Empty text for JS notation parse")
        # Keys after { or , and before : → add quotes around key
        # Pattern: ([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)
        json_str = re.sub(
            r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)",
            r'\1"\2"\3',
            js_text,
        )
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] JS notation snippet (first 400 chars): {js_text[:400]}")
            raise ValueError(f"Invalid JSON after JS notation conversion: {e}") from e

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
            raw_text = response.text
            print(f"[DEBUG] Raw response text (first 500 chars):\n{raw_text[:500]}")
            print(f"[DEBUG] Response headers: {dict(response.headers)}")

            # Layer 1: Extract JSON from SSE or plain JSON-RPC
            try:
                if "data: " in raw_text:
                    json_rpc_response = self._extract_json_from_sse(raw_text)
                    print(f"[DEBUG] Layer 1 OK: parsed SSE -> JSON-RPC keys: {list(json_rpc_response.keys()) if isinstance(json_rpc_response, dict) else 'not dict'}")
                else:
                    json_rpc_response = json.loads(raw_text)
                    print(f"[DEBUG] Layer 1 OK: parsed as plain JSON -> keys: {list(json_rpc_response.keys()) if isinstance(json_rpc_response, dict) else 'not dict'}")
            except json.JSONDecodeError as e:
                print(f"[DEBUG] Layer 1 failed: {e}")
                raise

            if isinstance(json_rpc_response, dict) and json_rpc_response.get("error"):
                raise ValueError(f"JSON-RPC error: {json_rpc_response['error']}")

            # Producer Pal API error: result.isError == True
            result = json_rpc_response.get("result") if isinstance(json_rpc_response, dict) else None
            if isinstance(result, dict) and result.get("isError") is True:
                error_text = "Unknown error"
                try:
                    content = result.get("content")
                    if content and isinstance(content, list) and len(content) > 0:
                        first = content[0]
                        if isinstance(first, dict) and first.get("text") is not None:
                            error_text = first.get("text", error_text)
                except (KeyError, IndexError, TypeError):
                    pass
                print(f"[DEBUG] Producer Pal isError=True: {error_text[:200]!r}")
                raise ValueError(f"Producer Pal error: {error_text}")

            # Layer 2: Extract text from JSON-RPC result.content[0].text
            try:
                result = json_rpc_response.get("result")
                if result is None:
                    raise ValueError("JSON-RPC result is missing")
                content = result.get("content") if isinstance(result, dict) else None
                if not content or not isinstance(content, list):
                    raise ValueError("result.content missing or not a list")
                first = content[0]
                if not isinstance(first, dict):
                    raise ValueError("result.content[0] is not an object")
                inner_text = first.get("text")
                if inner_text is None:
                    raise ValueError("result.content[0].text is missing")
                print(f"[DEBUG] Layer 2 OK: inner text length = {len(inner_text)}, first 200 chars: {inner_text[:200]!r}")
            except (KeyError, IndexError, TypeError, ValueError) as e:
                result = json_rpc_response.get("result") if isinstance(json_rpc_response, dict) else None
                print(f"[DEBUG] Layer 2 failed: {e}. result keys: {list(result.keys()) if isinstance(result, dict) else result!r}")
                raise ValueError(f"Could not get result.content[0].text: {e}") from e

            # Layer 3: Convert JS notation to JSON and parse
            try:
                final_obj = self._js_notation_to_json(inner_text)
                print(f"[DEBUG] Layer 3 OK: final object keys: {list(final_obj.keys()) if isinstance(final_obj, dict) else type(final_obj).__name__}")
                return final_obj
            except ValueError as e:
                print(f"[DEBUG] Layer 3 failed: {e}")
                raise
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

    def get_track(self, track_id: int | str) -> Track:
        """Get information about a specific track.

        Calls the ppal-read-track tool to retrieve track details.

        Args:
            track_id: Either a Producer Pal track ID (string, e.g. "2", "3")
                or a 0-based track index (int). String uses parameter "trackId",
                int uses "trackIndex".

        Returns:
            Track model containing track information including clips.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
            pydantic.ValidationError: If the response cannot be parsed into Track model.
        """
        if isinstance(track_id, str):
            arguments = {"trackId": track_id}
        else:
            arguments = {"trackIndex": track_id}
        response = self._call_tool("ppal-read-track", arguments)

        # Producer Pal returns sessionClips (Session View) and arrangementClips
        # (Arrangement View) separately; our Track model expects a single "clips" list.
        session_clips = response.get("sessionClips", [])
        arrangement_clips = response.get("arrangementClips", [])
        response["clips"] = session_clips + arrangement_clips
        response.pop("sessionClips", None)
        response.pop("arrangementClips", None)

        # Преобразовать notes из строки Producer Pal в список dict для модели Note
        for clip in response["clips"]:
            if isinstance(clip.get("notes"), str):
                clip["notes"] = parse_notes_string(clip["notes"])
            if "name" not in clip:
                clip["name"] = f"Clip {clip.get('id', 'Unknown')}"

        return Track.model_validate(response)

    def create_midi_clip(self, track_id: int | str, notes: List[Note]) -> Clip:
        """Create a new MIDI clip on the specified track.

        Calls the ppal-create-clip tool to create a clip with the given notes.

        Args:
            track_id: Either a Producer Pal track ID (string, e.g. "2", "3")
                or a 0-based track index (int). String uses "trackId", int uses "trackIndex".
            notes: List of Note objects to include in the clip.

        Returns:
            Clip model containing information about the created clip.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
            pydantic.ValidationError: If the response cannot be parsed into Clip model.
        """
        if isinstance(track_id, str):
            arguments = {"trackId": track_id, "notes": [n.model_dump() for n in notes]}
        else:
            arguments = {"trackIndex": track_id, "notes": [n.model_dump() for n in notes]}
        data = self._call_tool("ppal-create-clip", arguments)
        return Clip.model_validate(data)

    def get_clip(
        self,
        track_id: int | str,
        clip_id: int | str | None = None,
        scene_index: int | None = None,
    ) -> Clip:
        """Get clip by ID or by track/scene position.

        Calls the ppal-read-clip tool. Producer Pal accepts:
        - Variant A: clipId (str) — direct clip ID (e.g. "26").
        - Variant B: trackIndex (int) + sceneIndex (int) — session view position.

        Args:
            track_id: Track ID (str) or 0-based track index (int).
            clip_id: Clip ID (str) or scene index (int). If None, use scene_index.
            scene_index: Scene index (int) for session view. Used only if clip_id is None.

        Either clip_id OR scene_index must be provided.
        When using clip index or scene_index, track_id must be numeric (trackIndex).

        Returns:
            Clip model containing clip information including notes.

        Raises:
            ValueError: If neither clip_id nor scene_index provided, or invalid combination.
            ConnectionError: If connection to the API server fails.
            pydantic.ValidationError: If the response cannot be parsed into Clip model.
        """
        if clip_id is not None:
            if isinstance(clip_id, str):
                arguments = {"clipId": clip_id}
            else:
                if isinstance(track_id, str):
                    raise ValueError(
                        "When using clip index (int), track_id must be numeric trackIndex"
                    )
                arguments = {
                    "trackIndex": track_id,
                    "sceneIndex": clip_id,
                }
        elif scene_index is not None:
            if isinstance(track_id, str):
                raise ValueError(
                    "When using scene_index, track_id must be numeric trackIndex"
                )
            arguments = {
                "trackIndex": track_id,
                "sceneIndex": scene_index,
            }
        else:
            raise ValueError("Either clip_id or scene_index must be provided")

        response = self._call_tool("ppal-read-clip", arguments)

        # Преобразовать notes из строки Producer Pal в список dict для модели Note
        if isinstance(response.get("notes"), str):
            response["notes"] = parse_notes_string(response["notes"])
        if "name" not in response:
            response["name"] = f"Clip {response.get('id', 'Unknown')}"

        return Clip.model_validate(response)
