"""Producer Pal API client."""

from typing import List

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

from api_layer.models import Clip, Note, Track


class ProducerPalClient:
    """Client for interacting with Producer Pal API.

    This client provides methods to communicate with the Producer Pal service
    running on a specified base URL. It handles tool calls and error handling.
    """

    def __init__(self, base_url: str = "http://localhost:3350") -> None:
        """Initialize Producer Pal client.

        Args:
            base_url: Base URL of the Producer Pal API server.
                Defaults to "http://localhost:3350".
        """
        self.base_url = base_url.rstrip("/")

    def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a Producer Pal tool with given arguments.

        Args:
            tool_name: Name of the tool to call (e.g., "ppal-read-live-set").
            arguments: Dictionary of arguments to pass to the tool.

        Returns:
            Dictionary containing the tool's response.

        Raises:
            ConnectionError: If connection to the API server fails.
            requests.RequestException: For other HTTP-related errors.
        """
        url = f"{self.base_url}/mcp"
        payload = {
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
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
        response = self._call_tool("ppal-read-track", {"trackId": track_id})
        # Extract data from MCP response if needed
        data = response.get("result", response) if isinstance(response, dict) else response
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
        response = self._call_tool("ppal-create-clip", arguments)
        # Extract data from MCP response if needed
        data = response.get("result", response) if isinstance(response, dict) else response
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
        response = self._call_tool(
            "ppal-read-clip", {"trackId": track_id, "clipId": clip_id}
        )
        # Extract data from MCP response if needed
        data = response.get("result", response) if isinstance(response, dict) else response
        return Clip.model_validate(data)
