"""Integration-style tests for Producer Pal client with JSON-RPC 2.0."""

import pytest
import requests
from unittest.mock import Mock, patch

from api_layer.client import ProducerPalClient
from api_layer.models import Note


@pytest.fixture
def client():
    """Create a ProducerPalClient instance for testing."""
    return ProducerPalClient(base_url="http://localhost:3350")


@pytest.fixture
def mock_response():
    """Create a mock response object (non-SSE Content-Type by default)."""
    response = Mock(spec=requests.Response)
    response.raise_for_status = Mock()
    response.headers = {"Content-Type": "application/json"}
    return response


@patch("api_layer.client.requests.post")
def test_get_project_info_success(mock_post, client, mock_response):
    """Test successful get_project_info returns result from JSON-RPC 2.0 response."""
    expected_data = {"tempo": 120.0, "tracks": []}
    mock_response.json.return_value = {
        "jsonrpc": "2.0",
        "result": expected_data,
        "id": 1,
    }
    mock_post.return_value = mock_response

    result = client.get_project_info()

    assert result == expected_data
    payload = mock_post.call_args[1]["json"]
    assert "jsonrpc" in payload
    assert payload["jsonrpc"] == "2.0"
    assert "id" in payload
    assert payload["id"] == 1


@patch("api_layer.client.requests.post")
def test_get_track_success(mock_post, client, mock_response):
    """Test successful get_track returns Track from JSON-RPC 2.0 result."""
    from api_layer.models import Track

    track_data = {
        "id": 1,
        "name": "Test Track",
        "clips": [
            {
                "id": 1,
                "name": "Test Clip",
                "notes": [
                    {
                        "pitch": "C3",
                        "start": "1|1",
                        "duration": "1:0",
                        "velocity": 80,
                        "probability": 1.0,
                    }
                ],
                "length": "4:0",
            }
        ],
    }
    mock_response.json.return_value = {
        "jsonrpc": "2.0",
        "result": track_data,
        "id": 1,
    }
    mock_post.return_value = mock_response

    result = client.get_track(track_id=1)

    assert isinstance(result, Track)
    assert result.id == 1
    assert result.name == "Test Track"
    payload = mock_post.call_args[1]["json"]
    assert "jsonrpc" in payload
    assert "id" in payload


@patch("api_layer.client.requests.post")
def test_create_midi_clip_success(mock_post, client, mock_response):
    """Test create_midi_clip sends JSON-RPC 2.0 and uses result."""
    from api_layer.models import Clip

    notes = [
        Note(pitch="C3", start="1|1", duration="1:0", velocity=80, probability=1.0),
        Note(pitch="E3", start="2|1", duration="1:0", velocity=90),
    ]
    clip_data = {
        "id": 1,
        "name": "New Clip",
        "notes": [note.model_dump() for note in notes],
        "length": "4:0",
    }
    mock_response.json.return_value = {
        "jsonrpc": "2.0",
        "result": clip_data,
        "id": 1,
    }
    mock_post.return_value = mock_response

    result = client.create_midi_clip(track_id=1, notes=notes)

    assert isinstance(result, Clip)
    assert result.id == 1
    payload = mock_post.call_args[1]["json"]
    assert "jsonrpc" in payload
    assert "id" in payload


@patch("api_layer.client.requests.post")
def test_json_rpc_error(mock_post, client, mock_response):
    """Test that JSON-RPC error response raises ValueError."""
    error_response = {
        "jsonrpc": "2.0",
        "error": {"code": -32600, "message": "Invalid params"},
        "id": 1,
    }
    mock_response.json.return_value = error_response
    mock_post.return_value = mock_response

    with pytest.raises(ValueError) as exc_info:
        client.get_project_info()

    assert "JSON-RPC error" in str(exc_info.value)
