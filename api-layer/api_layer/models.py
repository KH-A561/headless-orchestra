"""Pydantic models for Producer Pal API."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class Note(BaseModel):
    """Note model representing a MIDI note.

    Attributes:
        pitch: Note pitch as string (e.g., "C3", "F#4", "Bb2").
        start: Start position in format "bar|beat" (e.g., "1|1").
        duration: Duration in format "bars:beats" (e.g., "1:0").
        velocity: Note velocity (0-127). Defaults to 80.
        probability: Note probability (0.0-1.0). Defaults to 1.0.
    """

    pitch: str
    start: str
    duration: str
    velocity: int = Field(default=80, ge=0, le=127)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("start")
    @classmethod
    def validate_start_format(cls, v: str) -> str:
        """Validate start is in format 'bar|beat' where both are numeric.

        Examples: "1|1", "2|3", "1|2.998"
        """
        if not isinstance(v, str):
            raise ValueError("start must be a string")

        parts = v.split("|")
        if len(parts) != 2:
            raise ValueError("start must be in format 'bar|beat'")

        try:
            bar = float(parts[0])
            beat = float(parts[1])
            if bar <= 0 or beat <= 0:
                raise ValueError("bar and beat must be positive")
        except ValueError as e:
            if "must be positive" in str(e):
                raise
            raise ValueError("start must be in format 'bar|beat' with numeric values") from e

        return v

    @field_validator("duration")
    @classmethod
    def validate_duration_format(cls, v: str) -> str:
        """Validate duration is in format 'bars:beats' where both are numeric.

        Examples: "1:0", "0:1", "1:0.5"
        """
        if not isinstance(v, str):
            raise ValueError("duration must be a string")

        if ":" not in v:
            raise ValueError('duration must be in format "bars:beats" (e.g., "1:0")')
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError('duration must be in format "bars:beats" (e.g., "1:0")')

        try:
            bars = float(parts[0])
            beats = float(parts[1])
            if bars < 0 or beats < 0:
                raise ValueError("bars and beats must be non-negative")
        except ValueError as e:
            if "non-negative" in str(e):
                raise
            raise ValueError('duration must be in format "bars:beats" with numeric values') from e

        return v


class Clip(BaseModel):
    """Clip model representing a MIDI clip.

    Attributes:
        id: Clip identifier.
        name: Clip name.
        notes: List of notes in the clip.
        length: Clip length in format "bars:beats".
    """

    id: int
    name: str
    notes: List[Note]
    length: str

    @field_validator("length")
    @classmethod
    def validate_length_format(cls, v: str) -> str:
        """Validate length format is 'bars:beats'."""
        if ":" not in v:
            raise ValueError('length must be in format "bars:beats" (e.g., "1:0")')
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError('length must be in format "bars:beats" (e.g., "1:0")')
        try:
            int(parts[0])
            int(parts[1])
        except ValueError:
            raise ValueError('length must be in format "bars:beats" with numeric values')
        return v


class Track(BaseModel):
    """Track model representing an audio/MIDI track.

    Attributes:
        id: Track identifier.
        name: Track name.
        clips: List of clips on the track.
        type: Track type ("midi" or "audio"). Optional.
        trackIndex: Index of the track. Optional.
        sessionClipCount: Number of clips in session view. Optional.
        arrangementClipCount: Number of clips in arrangement view. Optional.
    """

    id: int
    name: str
    clips: List[Clip] = []

    # Дополнительные поля (опциональные)
    type: Optional[str] = None  # "midi" или "audio"
    trackIndex: Optional[int] = None
    sessionClipCount: Optional[int] = None
    arrangementClipCount: Optional[int] = None


class ProjectInfo(BaseModel):
    """Project information model.

    Attributes:
        tempo: Project tempo in BPM.
        tracks: List of tracks in the project.
    """

    tempo: float = Field(gt=0.0)
    tracks: List[Track]
