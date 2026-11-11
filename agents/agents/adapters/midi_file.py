"""Файловый адаптер: загрузка ``.mid`` через mido (сырые тики) в ``ClipData``.

Переносит загрузку из ``scripts/analyze_midi_file.py``: сырые тики, первый
``time_signature``, первый ``set_tempo``, ``track_name``, логика
``skip_drum_channel``. Новое: реальные длительности (note_on → ближайший
последующий note_off / note_on vel 0 того же питча и канала; незакрытая нота —
до конца трека).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import mido

from ..domain import ClipData, ClipRef, ClipSummary, NoteEvent, TimeSignature

# GM drum channel (1-based channel 10 → 0-based index 9).
_DRUM_CHANNEL = 9

_FILE_REF_ID_RE = re.compile(r"^file:.+#(all|t\d+)$")


def _validate_file_ref_id(ref_id: str) -> None:
    """Понятная ошибка на мусорный ``ref_id`` файлового адаптера."""
    if not _FILE_REF_ID_RE.match(ref_id):
        raise ValueError(
            f"Invalid file clip ref id: {ref_id!r}; "
            "expected 'file:<path>#all' or 'file:<path>#t<N>'"
        )


def _extract_time_signature(mid: mido.MidiFile) -> tuple[TimeSignature, list[str]]:
    """Первый ``time_signature`` по всем трекам; предупреждения о сменах/отсутствии."""
    warnings: list[str] = []
    numerator, denominator = 4, 4
    ts_count = 0

    for track in mid.tracks:
        for msg in track:
            if msg.type != "time_signature":
                continue
            ts_count += 1
            if ts_count == 1:
                numerator, denominator = msg.numerator, msg.denominator
            elif ts_count == 2:
                warnings.append(
                    "Multiple time signatures in file; using first only "
                    f"({numerator}/{denominator}). Tempo/size changes are not supported in v1."
                )
                return TimeSignature(numerator=numerator, denominator=denominator), warnings

    if ts_count == 0:
        warnings.append("no time_signature meta, assuming 4/4")

    return TimeSignature(numerator=numerator, denominator=denominator), warnings


def _extract_tempo_and_track_name(mid: mido.MidiFile) -> tuple[float | None, str | None]:
    """Первое ``set_tempo`` (BPM) и первый непустой ``track_name``."""
    tempo_bpm: float | None = None
    track_name: str | None = None
    for track in mid.tracks:
        for msg in track:
            if tempo_bpm is None and msg.type == "set_tempo":
                tempo_bpm = mido.tempo2bpm(msg.tempo)
            if track_name is None and msg.type == "track_name" and msg.name:
                track_name = msg.name
        if tempo_bpm is not None and track_name is not None:
            break
    return tempo_bpm, track_name


def _track_has_note_on(track: mido.MidiTrack) -> bool:
    """Есть ли в треке хотя бы один note_on с velocity > 0."""
    for msg in track:
        if msg.type == "note_on" and msg.velocity > 0:
            return True
    return False


def _track_note_events(
    track: mido.MidiTrack,
    ticks_per_beat: int,
    *,
    skip_drum_channel: bool,
) -> list[tuple[float, int, int, float]]:
    """Ноты одного трека: ``(start, pitch, velocity, duration)`` в четвертях.

    note_on (velocity > 0) открывает ноту; ближайший последующий note_off /
    note_on с velocity 0 того же питча и канала закрывает её. Незакрытые ноты
    длятся до конца трека (суммарный тик всех сообщений трека).
    """
    events: list[tuple[float, int, int, float]] = []
    open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
    tick_pos = 0

    for msg in track:
        tick_pos += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            if skip_drum_channel and msg.channel == _DRUM_CHANNEL:
                continue
            open_notes.setdefault((msg.note, msg.channel), []).append(
                (tick_pos, msg.velocity)
            )
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.note, msg.channel)
            starts = open_notes.get(key)
            if starts:
                start_tick, velocity = starts.pop(0)
                duration = (tick_pos - start_tick) / ticks_per_beat
                events.append(
                    (start_tick / ticks_per_beat, msg.note, velocity, duration)
                )

    track_end = tick_pos
    for (note, _channel), starts in open_notes.items():
        for start_tick, velocity in starts:
            duration = (track_end - start_tick) / ticks_per_beat
            events.append((start_tick / ticks_per_beat, note, velocity, duration))

    return events


def _load_note_events(
    mid: mido.MidiFile,
    *,
    track: int | None = None,
    skip_drum_channel: bool | None = None,
) -> list[NoteEvent]:
    """Все ноты файла (или одного трека) с реальными длительностями."""
    ticks_per_beat = mid.ticks_per_beat
    if skip_drum_channel is None:
        skip_drum_channel = track is None

    note_track_indices = [i for i, tr in enumerate(mid.tracks) if _track_has_note_on(tr)]
    if not note_track_indices:
        return []

    if track is not None:
        if track < 0 or track >= len(note_track_indices):
            raise ValueError(
                f"Track index {track} out of range "
                f"(file has {len(note_track_indices)} note-bearing track(s))"
            )
        selected = [note_track_indices[track]]
    else:
        selected = note_track_indices

    raw: list[tuple[float, int, int, float]] = []
    for idx in selected:
        raw.extend(
            _track_note_events(
                mid.tracks[idx],
                ticks_per_beat,
                skip_drum_channel=skip_drum_channel,
            )
        )
    raw.sort(key=lambda item: item[0])

    return [
        NoteEvent(
            pitch=pitch,
            start=start,
            duration=duration,
            velocity=float(velocity),
        )
        for start, pitch, velocity, duration in raw
    ]


class MidiFileAdapter:
    """Читает ``.mid`` как нейтральный ``ClipData`` (без Ableton-специфики)."""

    def __init__(
        self,
        path: Path | str,
        track: int | None = None,
        skip_drum_channel: bool | None = None,
    ) -> None:
        self.path = Path(path)
        self.track = track
        self.skip_drum_channel = skip_drum_channel
        self.warnings: list[str] = []

        self._loaded = False
        self._notes: list[NoteEvent] = []
        self._time_signature = TimeSignature(numerator=4, denominator=4)
        self._tempo_bpm: float | None = None
        self._track_name: str | None = None

    def _ref_id(self) -> str:
        suffix = "all" if self.track is None else f"t{self.track}"
        return f"file:{self.path}#{suffix}"

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        mid = mido.MidiFile(str(self.path))
        self._time_signature, ts_warnings = _extract_time_signature(mid)
        self.warnings.extend(ts_warnings)
        self._tempo_bpm, self._track_name = _extract_tempo_and_track_name(mid)
        self._notes = _load_note_events(
            mid,
            track=self.track,
            skip_drum_channel=self.skip_drum_channel,
        )

    def list_clips(self, query: str = "") -> list[ClipSummary]:
        """Один ``ClipSummary`` для файла."""
        self._load()
        return [
            ClipSummary(
                ref=ClipRef(
                    id=self._ref_id(),
                    track_name=self._track_name or "",
                    clip_name=self.path.name,
                ),
                length=None,
                is_playing=None,
                has_kit=False,
            )
        ]

    def read_clip(self, ref_id: str) -> ClipData:
        """``ClipData`` с ``window=None``, ``pad_map=None``."""
        _validate_file_ref_id(ref_id)
        self._load()
        return ClipData(
            ref=ClipRef(
                id=ref_id,
                track_name=self._track_name or "",
                clip_name=self.path.name,
            ),
            notes=tuple(self._notes),
            window=None,
            time_signature=self._time_signature,
            tempo_bpm=self._tempo_bpm,
            pad_map=None,
        )
