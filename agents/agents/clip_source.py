"""Превращение данных клипа из Live в ``list[Note]`` + контекст анализа.

Мост отдаёт ноты в долях от начала клипа. Здесь выбирается окно анализа
(петля или весь клип), ноты конвертируются в Ableton-конвенцию
(``api_layer.models.Note``), а позиции окна сдвигаются к нулю.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from api_layer.models import Note

from .chord_grouping import beats_to_start, parse_time_signature
from .live_bridge import LiveBridge
from .midi_utils import midi_to_ableton_pitch

_DRUM_GROUP_DEVICE = "DrumGroupDevice"


class ClipContext(BaseModel):
    """Контекст клипа: источник нот, окно анализа, пэды и причина выбора material."""

    track_index: int
    track_name: str
    clip_index: int
    clip_name: str
    tempo_bpm: float
    time_signature: str  # из клипа (signature_*), иначе из сета
    beats_per_bar: int
    region: Literal["loop", "clip"]
    region_start: float  # в долях клипа
    region_end: float | None  # в долях клипа; None для "clip"
    notes_total: int
    notes_in_region: int
    notes_outside_region: int
    notes_muted_skipped: int
    notes_with_probability_below_1: int
    has_drum_rack: bool
    pad_names: dict[int, str]  # пусто, если Drum Rack нет
    pitches_without_pad: list[int]  # питчи в анализируемых нотах без пэда
    material_reason: str  # почему выбран material


def _beats_to_bars_beats(duration_beats: float, beats_per_bar: int) -> str:
    """Длительность в долях → строка ``bars:beats`` (формат ``Note.duration``)."""
    bars = int(duration_beats // beats_per_bar)
    beats = duration_beats - bars * beats_per_bar
    if abs(beats - round(beats)) < 1e-9:
        return f"{bars}:{int(round(beats))}"
    return f"{bars}:{beats}"


def _find_drum_rack_device(devices: list[dict]) -> int | None:
    """Индекс первого устройства с ``class_name == DrumGroupDevice`` или None."""
    for device in devices:
        if device.get("class_name") == _DRUM_GROUP_DEVICE:
            return device.get("index")
    return None


def _clip_name(clip_slots: list[dict], clip_index: int) -> str:
    """Имя клипа из ``clip_slots`` по индексу; пустая строка, если нет."""
    if 0 <= clip_index < len(clip_slots):
        slot = clip_slots[clip_index]
        if slot.get("has_clip") and slot.get("clip"):
            return slot["clip"].get("name", "")
    return ""


def _resolve_window(
    clip_info: dict,
    region: Literal["loop", "clip"],
) -> tuple[float, float | None, float | None]:
    """Окно анализа и длина клипа для ритма.

    Returns:
        (region_start, region_end, clip_length_beats); для ``"clip"``
        ``region_end`` и ``clip_length_beats`` равны None.
    """
    if region == "clip":
        return 0.0, None, None

    if clip_info.get("looping"):
        start = float(clip_info["loop_start"])
        end = float(clip_info["loop_end"])
    else:
        start = float(clip_info["start_marker"])
        end = float(clip_info["end_marker"])
    return start, end, end - start


def load_clip(
    bridge: LiveBridge,
    track_index: int,
    clip_index: int,
    region: Literal["loop", "clip"] = "loop",
) -> tuple[list[Note], ClipContext, float | None]:
    """Загрузить клип из Live и превратить в ноты для анализа + контекст.

    Args:
        bridge: клиент моста Ableton.
        track_index: индекс MIDI-трека.
        clip_index: индекс клипа на треке.
        region: ``"loop"`` — окно петли (или маркеров), ``"clip"`` — все ноты.

    Returns:
        (ноты для анализа, контекст, clip_length_beats для ритма или None).
    """
    snapshot = bridge.call("get_session_snapshot")
    tempo_bpm = float(snapshot["tempo"])
    set_time_signature = snapshot.get("time_signature", "4/4")
    tracks = snapshot.get("tracks", [])
    track_name = tracks[track_index].get("name", "") if track_index < len(tracks) else ""

    clip_info = bridge.call(
        "get_clip_info", {"track_index": track_index, "clip_index": clip_index}
    )
    track_info = bridge.call("get_track_info", {"track_index": track_index})
    notes_raw = bridge.call(
        "get_clip_notes", {"track_index": track_index, "clip_index": clip_index}
    )

    clip_name = _clip_name(track_info.get("clip_slots", []), clip_index)

    numerator = clip_info.get("signature_numerator")
    denominator = clip_info.get("signature_denominator")
    if numerator and denominator:
        time_signature = f"{int(numerator)}/{int(denominator)}"
    else:
        time_signature = set_time_signature
    beats_per_bar = parse_time_signature(time_signature)

    drum_device_index = _find_drum_rack_device(track_info.get("devices", []))
    has_drum_rack = drum_device_index is not None
    pad_names: dict[int, str] = {}
    if has_drum_rack:
        pads = bridge.call(
            "get_drum_pads",
            {"track_index": track_index, "device_index": drum_device_index},
        )
        for pad in pads.get("pads", []):
            pad_names[int(pad["note"])] = pad.get("name", "")

    region_start, region_end, clip_length_beats = _resolve_window(clip_info, region)

    notes: list[Note] = []
    notes_total = 0
    notes_in_region = 0
    notes_outside_region = 0
    notes_muted_skipped = 0
    notes_with_probability_below_1 = 0
    analyzed_pitches: set[int] = set()

    for raw in notes_raw.get("notes", []):
        notes_total += 1
        if bool(raw.get("mute", False)):
            notes_muted_skipped += 1
            continue

        start_time = float(raw["start_time"])
        if region_end is not None and (start_time < region_start or start_time >= region_end):
            notes_outside_region += 1
            continue

        notes_in_region += 1
        midi_pitch = int(raw["pitch"])
        analyzed_pitches.add(midi_pitch)

        probability = float(raw.get("probability", 1.0))
        if probability < 1.0:
            notes_with_probability_below_1 += 1

        pos = start_time if region == "clip" else start_time - region_start
        velocity = int(round(float(raw.get("velocity", 100.0))))
        velocity = max(1, min(127, velocity))

        notes.append(
            Note(
                pitch=midi_to_ableton_pitch(midi_pitch),
                start=beats_to_start(pos, beats_per_bar),
                duration=_beats_to_bars_beats(float(raw.get("duration", 0.0)), beats_per_bar),
                velocity=velocity,
            )
        )

    pitches_without_pad = sorted(p for p in analyzed_pitches if p not in pad_names)

    context = ClipContext(
        track_index=track_index,
        track_name=track_name,
        clip_index=clip_index,
        clip_name=clip_name,
        tempo_bpm=tempo_bpm,
        time_signature=time_signature,
        beats_per_bar=beats_per_bar,
        region=region,
        region_start=region_start,
        region_end=region_end,
        notes_total=notes_total,
        notes_in_region=notes_in_region,
        notes_outside_region=notes_outside_region,
        notes_muted_skipped=notes_muted_skipped,
        notes_with_probability_below_1=notes_with_probability_below_1,
        has_drum_rack=has_drum_rack,
        pad_names=pad_names,
        pitches_without_pad=pitches_without_pad,
        material_reason="drum_rack_on_track" if has_drum_rack else "heuristic",
    )

    return notes, context, clip_length_beats
