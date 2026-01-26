"""Tests for ProducerPalClient."""

import pytest
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

from api_layer.client import ProducerPalClient
from api_layer.models import Clip, Note, Track


@pytest.fixture
def client() -> ProducerPalClient:
    """Create a ProducerPalClient instance for testing."""
    return ProducerPalClient(base_url="http://localhost:3350")


@pytest.fixture
def mock_response(mocker):
    """Create a mock response object."""
    response = mocker.Mock(spec=requests.Response)
    response.raise_for_status = mocker.Mock()
    return response


def test_get_project_info_success(client: ProducerPalClient, mock_response, mocker):
    """Test successful get_project_info call."""
    # Arrange
    expected_data = {"tempo": 120.0, "tracks": []}
    mock_response.json.return_value = expected_data
    mock_post = mocker.patch("api_layer.client.requests.post", return_value=mock_response)

    # Act
    result = client.get_project_info()

    # Assert
    assert result == expected_data
    assert isinstance(result, dict)
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "http://localhost:3350/mcp"
    assert call_args[1]["json"] == {
        "method": "tools/call",
        "params": {
            "name": "ppal-read-live-set",
            "arguments": {},
        },
    }
    assert call_args[1]["headers"] == {"Content-Type": "application/json"}
    assert call_args[1]["timeout"] == 30


def test_get_project_info_connection_error(client: ProducerPalClient, mocker):
    """Test get_project_info raises ConnectionError on connection failure."""
    # Arrange
    connection_error = RequestsConnectionError("Connection refused")
    mocker.patch("api_layer.client.requests.post", side_effect=connection_error)

    # Act & Assert
    with pytest.raises(ConnectionError) as exc_info:
        client.get_project_info()

    assert "Failed to connect to Producer Pal API" in str(exc_info.value)
    assert "http://localhost:3350" in str(exc_info.value)


def test_get_track_success(client: ProducerPalClient, mock_response, mocker):
    """Test successful get_track call returns Track model."""
    # Arrange
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
    mock_response.json.return_value = track_data
    mocker.patch("api_layer.client.requests.post", return_value=mock_response)

    # Act
    result = client.get_track(track_id=1)

    # Assert
    assert isinstance(result, Track)
    assert result.id == 1
    assert result.name == "Test Track"
    assert len(result.clips) == 1
    assert result.clips[0].id == 1
    assert result.clips[0].name == "Test Clip"


def test_create_midi_clip(client: ProducerPalClient, mock_response, mocker):
    """Test create_midi_clip properly serializes notes."""
    # Arrange
    notes = [
        Note(pitch="C3", start="1|1", duration="1:0", velocity=80, probability=1.0),
        Note(pitch="E3", start="2|1", duration="1:0", velocity=90, probability=0.8),
        Note(pitch="G3", start="3|1", duration="1:0", velocity=100),
    ]

    clip_data = {
        "id": 1,
        "name": "New Clip",
        "notes": [note.model_dump() for note in notes],
        "length": "4:0",
    }
    mock_response.json.return_value = clip_data
    mock_post = mocker.patch("api_layer.client.requests.post", return_value=mock_response)

    # Act
    result = client.create_midi_clip(track_id=1, notes=notes)

    # Assert
    assert isinstance(result, Clip)
    assert result.id == 1
    assert result.name == "New Clip"
    assert len(result.notes) == 3

    # Verify that notes were serialized correctly in the request
    call_args = mock_post.call_args
    request_payload = call_args[1]["json"]
    assert request_payload["params"]["name"] == "ppal-create-clip"
    assert request_payload["params"]["arguments"]["trackId"] == 1
    assert len(request_payload["params"]["arguments"]["notes"]) == 3
    assert request_payload["params"]["arguments"]["notes"][0]["pitch"] == "C3"
    assert request_payload["params"]["arguments"]["notes"][1]["pitch"] == "E3"
    assert request_payload["params"]["arguments"]["notes"][2]["pitch"] == "G3"
    assert request_payload["params"]["arguments"]["notes"][0]["velocity"] == 80
    assert request_payload["params"]["arguments"]["notes"][1]["velocity"] == 90
    assert request_payload["params"]["arguments"]["notes"][2]["velocity"] == 100
