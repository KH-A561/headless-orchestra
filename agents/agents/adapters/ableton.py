"""Адаптер Ableton Live: всё Ableton-специфичное живёт здесь.

Переносит логику ``clip_source.py`` (snapshot/track/clip/notes/pads) и
``find_midi_clips`` из ``mcp_server.py``. Конвертация Ableton-конвенций
(``C3=60``, ``loop_start``/``start_marker``, ``DrumGroupDevice``) происходит
только на границе этого модуля; ядро получает нейтральный ``ClipData``.
"""

from __future__ import annotations

import re
from typing import Any

from ..domain import ClipData, ClipRef, ClipSummary, NoteEvent, TimeSignature
from ..live_bridge import LiveBridge

_DRUM_GROUP_DEVICE = "DrumGroupDevice"

_REF_ID_RE = re.compile(r"^ableton:t(\d+)/s(\d+)$")

_DEFAULT_TS = TimeSignature(numerator=4, denominator=4)


def parse_ref_id(ref_id: str) -> tuple[int, int]:
    """Разобрать ``ref_id`` вида ``ableton:t{track_index}/s{clip_index}``.

    Raises:
        ValueError: если формат не соответствует.
    """
    match = _REF_ID_RE.match(ref_id)
    if not match:
        raise ValueError(
            f"Invalid Ableton clip ref id: {ref_id!r}; "
            "expected 'ableton:t<track_index>/s<clip_index>'"
        )
    return int(match[1]), int(match[2])


def _parse_time_signature(ts_str: str) -> TimeSignature:
    """Строка ``"4/4"`` → ``TimeSignature``; при мусоре — 4/4."""
    match = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", ts_str or "")
    if not match:
        return _DEFAULT_TS
    return TimeSignature(numerator=int(match[1]), denominator=int(match[2]))


def _clip_name(clip_slots: list[dict[str, Any]], clip_index: int) -> str:
    """Имя клипа из ``clip_slots`` по индексу; пустая строка, если нет."""
    if 0 <= clip_index < len(clip_slots):
        slot = clip_slots[clip_index]
        if slot.get("has_clip") and slot.get("clip"):
            return slot["clip"].get("name", "")
    return ""


def _find_drum_rack_device(devices: list[dict[str, Any]]) -> int | None:
    """Индекс первого устройства с ``class_name == DrumGroupDevice`` или None."""
    for device in devices:
        if device.get("class_name") == _DRUM_GROUP_DEVICE:
            return device.get("index")
    return None


class AbletonAdapter:
    """Читает клипы из Live через мост ``mcp-server-ableton-live``."""

    def __init__(self, bridge: LiveBridge | None = None) -> None:
        self.bridge = bridge or LiveBridge()

    def _resolve_window(self, clip_info: dict[str, Any]) -> tuple[float, float]:
        """``(loop_start, loop_end)`` если looping, иначе ``(start_marker, end_marker)``."""
        if clip_info.get("looping"):
            return float(clip_info["loop_start"]), float(clip_info["loop_end"])
        return float(clip_info["start_marker"]), float(clip_info["end_marker"])

    def _resolve_time_signature(
        self,
        snapshot: dict[str, Any],
        clip_info: dict[str, Any],
    ) -> TimeSignature:
        """Размер клипа, при отсутствии — из сета, при мусоре — 4/4."""
        numerator = clip_info.get("signature_numerator")
        denominator = clip_info.get("signature_denominator")
        if numerator and denominator:
            return TimeSignature(numerator=int(numerator), denominator=int(denominator))
        return _parse_time_signature(snapshot.get("time_signature", "4/4"))

    def _read_pad_map(
        self,
        track_info: dict[str, Any],
        track_index: int,
    ) -> dict[int, str] | None:
        """Drum Rack → ``{note: name}``; нет кита → ``None``."""
        device_index = _find_drum_rack_device(track_info.get("devices", []))
        if device_index is None:
            return None
        pads = self.bridge.call(
            "get_drum_pads",
            {"track_index": track_index, "device_index": device_index},
        )
        return {int(pad["note"]): pad.get("name", "") for pad in pads.get("pads", [])}

    def list_clips(self, query: str = "") -> list[ClipSummary]:
        """MIDI-клипы Session view с фильтром по имени трека или клипа."""
        snapshot = self.bridge.call("get_session_snapshot")
        needle = (query or "").lower()
        clips: list[ClipSummary] = []

        for track in snapshot.get("tracks", []):
            if track.get("type") != "midi":
                continue
            if int(track.get("clips", 0)) <= 0:
                continue

            track_index = int(track["index"])
            track_name = track.get("name", "")
            track_info = self.bridge.call("get_track_info", {"track_index": track_index})
            has_kit = _find_drum_rack_device(track_info.get("devices", [])) is not None

            for slot in track_info.get("clip_slots", []):
                if not slot.get("has_clip"):
                    continue
                clip = slot.get("clip") or {}
                clip_name = clip.get("name", "")
                if needle and needle not in track_name.lower() and needle not in clip_name.lower():
                    continue
                clip_index = int(slot.get("index", 0))
                clips.append(
                    ClipSummary(
                        ref=ClipRef(
                            id=f"ableton:t{track_index}/s{clip_index}",
                            track_name=track_name,
                            clip_name=clip_name,
                        ),
                        length=clip.get("length"),
                        is_playing=clip.get("is_playing"),
                        has_kit=has_kit,
                    )
                )

        return clips

    def read_clip(self, ref_id: str) -> ClipData:
        """Прочитать клип по ``ableton:t{track_index}/s{clip_index}``."""
        track_index, clip_index = parse_ref_id(ref_id)

        snapshot = self.bridge.call("get_session_snapshot")

        clip_info = self.bridge.call(
            "get_clip_info", {"track_index": track_index, "clip_index": clip_index}
        )
        track_info = self.bridge.call("get_track_info", {"track_index": track_index})
        notes_raw = self.bridge.call(
            "get_clip_notes", {"track_index": track_index, "clip_index": clip_index}
        )

        track_name = track_info.get("name", "")
        clip_name = _clip_name(track_info.get("clip_slots", []), clip_index)
        time_signature = self._resolve_time_signature(snapshot, clip_info)
        window = self._resolve_window(clip_info)
        pad_map = self._read_pad_map(track_info, track_index)

        notes = [
            NoteEvent(
                pitch=int(raw["pitch"]),
                start=float(raw["start_time"]),
                duration=float(raw.get("duration", 0.0)),
                velocity=float(raw.get("velocity", 100.0)),
                probability=float(raw.get("probability", 1.0)),
                mute=bool(raw.get("mute", False)),
            )
            for raw in notes_raw.get("notes", [])
        ]

        return ClipData(
            ref=ClipRef(id=ref_id, track_name=track_name, clip_name=clip_name),
            notes=tuple(notes),
            window=window,
            time_signature=time_signature,
            tempo_bpm=float(snapshot["tempo"]),
            pad_map=pad_map,
        )
