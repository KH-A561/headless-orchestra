"""Тесты файлового адаптера: длительности, ref_id."""

from __future__ import annotations

from pathlib import Path

import mido
import pytest

from agents.adapters.midi_file import MidiFileAdapter


def _write_track(path: Path, messages: list[mido.Message | mido.MetaMessage]) -> None:
    mid = mido.MidiFile(ticks_per_beat=96)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
    for msg in messages:
        track.append(msg)
    mid.save(str(path))


def _read_notes(path: Path, track: int | None = None) -> list:
    adapter = MidiFileAdapter(path, track=track)
    clip = adapter.read_clip(adapter.list_clips()[0].ref.id)
    return list(clip.notes)


class TestDurations:
    def test_note_off(self, tmp_path: Path) -> None:
        path = tmp_path / "off.mid"
        _write_track(
            path,
            [
                mido.Message("note_on", channel=0, note=60, velocity=100, time=0),
                mido.Message("note_off", channel=0, note=60, velocity=0, time=96),
            ],
        )
        notes = _read_notes(path)
        assert len(notes) == 1
        assert notes[0].start == 0.0
        assert notes[0].duration == 1.0

    def test_note_on_velocity_zero_off(self, tmp_path: Path) -> None:
        path = tmp_path / "vel0.mid"
        _write_track(
            path,
            [
                mido.Message("note_on", channel=0, note=60, velocity=100, time=0),
                mido.Message("note_on", channel=0, note=60, velocity=0, time=48),
            ],
        )
        notes = _read_notes(path)
        assert len(notes) == 1
        assert notes[0].duration == 0.5

    def test_unclosed_note_runs_to_track_end(self, tmp_path: Path) -> None:
        path = tmp_path / "unclosed.mid"
        _write_track(
            path,
            [
                mido.Message("note_on", channel=0, note=60, velocity=100, time=0),
                mido.MetaMessage("end_of_track", time=192),
            ],
        )
        notes = _read_notes(path)
        assert len(notes) == 1
        assert notes[0].start == 0.0
        assert notes[0].duration == 2.0


class TestRefId:
    def test_all_when_merging(self, tmp_path: Path) -> None:
        path = tmp_path / "a.mid"
        _write_track(path, [mido.Message("note_on", channel=0, note=60, velocity=100, time=0)])
        adapter = MidiFileAdapter(path)
        summary = adapter.list_clips()[0]
        assert summary.ref.id == f"file:{path}#all"

    def test_track_suffix(self, tmp_path: Path) -> None:
        path = tmp_path / "a.mid"
        _write_track(path, [mido.Message("note_on", channel=0, note=60, velocity=100, time=0)])
        adapter = MidiFileAdapter(path, track=0)
        summary = adapter.list_clips()[0]
        assert summary.ref.id == f"file:{path}#t0"

    def test_garbage_ref_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "a.mid"
        _write_track(path, [mido.Message("note_on", channel=0, note=60, velocity=100, time=0)])
        adapter = MidiFileAdapter(path)
        with pytest.raises(ValueError):
            adapter.read_clip("ableton:t0/s0")


class TestNoTimeSignature:
    def test_no_time_signature_meta_warns_44(self, tmp_path: Path) -> None:
        mid = mido.MidiFile(ticks_per_beat=96)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.Message("note_on", channel=0, note=60, velocity=100, time=0))
        track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=96))
        mid.save(str(tmp_path / "no_ts.mid"))

        adapter = MidiFileAdapter(tmp_path / "no_ts.mid")
        clip = adapter.read_clip(adapter.list_clips()[0].ref.id)

        assert clip.time_signature.numerator == 4
        assert clip.time_signature.denominator == 4
        assert "no time_signature meta, assuming 4/4" in adapter.warnings
