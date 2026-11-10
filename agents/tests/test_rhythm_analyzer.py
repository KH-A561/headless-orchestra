"""Tests for deterministic rhythm analysis (RhythmAnalyzer v1).

Синтетика строится напрямую списком ``Note`` — истина видна в коде.
Реальный клип — ``tests/midi/real_2_twin_peaks_drums.mid`` (эталон из ТЗ 6.1).
"""

from __future__ import annotations

import json
from pathlib import Path

import mido
import pytest
from api_layer.models import Note

from scripts.analyze_midi_file import (
    _load_lane_names,
    analyze_midi_file,
    load_midi_notes,
    main,
)

from agents.chord_grouping import beats_to_start
from agents.rhythm_analyzer import (
    DeterministicRhythmAnalysis,
    run_deterministic_rhythm_analysis,
)

_FIXTURES_DIR = Path(__file__).parent / "midi"


def _note(pitch: str, pos: float, velocity: int = 100, bpb: int = 4) -> Note:
    return Note(
        pitch=pitch,
        start=beats_to_start(pos, bpb),
        duration="1:0",
        velocity=velocity,
    )


def _codes(result: DeterministicRhythmAnalysis) -> set[str]:
    return {obs.code for obs in result.observations}


def _obs(result: DeterministicRhythmAnalysis, code: str, lane_id: str | None = None):
    return [
        o for o in result.observations if o.code == code and (lane_id is None or o.lane_id == lane_id)
    ]


class TestSyntheticCases:
    def test_even_16ths_uniform_velocity(self) -> None:
        notes = [_note("C3", i * 0.25) for i in range(16)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        codes = _codes(result)
        assert "UNIFORM_VELOCITY" in codes
        assert "LOOSE" not in codes
        assert "UNQUANTIZED" not in codes
        assert "SWING_8TH" not in codes

    def test_clap_every_3_beats_cycle(self) -> None:
        notes = [_note("C3", p) for p in (0.0, 3.0, 6.0, 9.0)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        cycles = _obs(result, "CYCLE")
        assert len(cycles) == 1
        assert cycles[0].value["period_beats"] == 3.0
        assert cycles[0].value["realign_bars"] == 3
        assert cycles[0].value["aligns_with_bar"] is False

    def test_backbeat_cycle_aligned(self) -> None:
        notes = [_note("C3", p) for p in (1.0, 3.0, 5.0, 7.0)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        cycles = _obs(result, "CYCLE")
        assert len(cycles) == 1
        assert cycles[0].value["period_beats"] == 2.0
        assert cycles[0].value["aligns_with_bar"] is True
        assert cycles[0].value["realign_bars"] == 1

    def test_swing_06_no_unquantized_no_loose(self) -> None:
        positions = [b + off for b in (0.0, 1.0, 2.0, 3.0) for off in (0.0, 0.6)]
        notes = [_note("C3", p) for p in positions]
        result = run_deterministic_rhythm_analysis(notes, 4)
        swing = _obs(result, "SWING_8TH")
        assert len(swing) == 1
        assert swing[0].value["ratio"] == pytest.approx(0.6, abs=1e-6)
        codes = _codes(result)
        assert "UNQUANTIZED" not in codes
        assert "LOOSE" not in codes

    def test_swing_triplet_feel_text(self) -> None:
        positions = [b + off for b in (0.0, 1.0, 2.0, 3.0) for off in (0.0, 0.6667)]
        notes = [_note("C3", p) for p in positions]
        result = run_deterministic_rhythm_analysis(notes, 4)
        swing = _obs(result, "SWING_8TH")
        assert len(swing) == 1
        assert "triplet" in swing[0].text
        assert "UNQUANTIZED" not in _codes(result)

    def test_laid_back_no_loose(self) -> None:
        notes = [_note("C3", p) for p in (0.03, 1.03, 2.03, 3.03)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        codes = _codes(result)
        assert "LAID_BACK" in codes
        assert "LOOSE" not in codes

    def test_pushed_no_loose(self) -> None:
        notes = [_note("C3", p) for p in (0.97, 1.97, 2.97, 3.97)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        codes = _codes(result)
        assert "PUSHED" in codes
        assert "LOOSE" not in codes
        assert "LAID_BACK" not in codes

    def test_deterministic_jitter_loose(self) -> None:
        base = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75]
        jitter = [0.05, -0.05, 0.05, -0.05, 0.05, -0.05, 0.05, -0.05]
        notes = [_note("C3", b + j) for b, j in zip(base, jitter)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        codes = _codes(result)
        assert "LOOSE" in codes
        assert "LAID_BACK" not in codes
        assert "PUSHED" not in codes

    def test_between_16ths_unquantized(self) -> None:
        positions = [b + off for b in (0.0, 1.0) for off in (0.125, 0.375, 0.625, 0.875)]
        notes = [_note("C3", p) for p in positions]
        result = run_deterministic_rhythm_analysis(notes, 4)
        codes = _codes(result)
        assert "UNQUANTIZED" in codes
        assert "LOOSE" not in codes
        assert "LAID_BACK" not in codes
        assert "SWING_8TH" not in codes

    def test_accents_and_ghost_notes(self) -> None:
        velocities = [50, 100, 100, 100, 127]
        positions = [0.0, 0.5, 1.0, 1.5, 2.0]
        notes = [_note("C3", p, v) for p, v in zip(positions, velocities)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        accents = _obs(result, "ACCENTS")
        ghosts = _obs(result, "GHOST_NOTES")
        assert len(accents) == 1
        assert accents[0].value["positions"] == [2.0]
        assert len(ghosts) == 1
        assert ghosts[0].value["positions"] == [0.0]

    def test_empty_bar_mid_clip(self) -> None:
        notes = [_note("C3", p) for p in (0.0, 1.0, 8.0, 9.0)]
        result = run_deterministic_rhythm_analysis(notes, 4, clip_length_beats=12)
        empty = _obs(result, "EMPTY_BARS")
        assert len(empty) == 1
        assert empty[0].value["bars"] == [2]
        assert not _obs(result, "TRAILING_EMPTY")

    def test_trailing_empty_with_given_length(self) -> None:
        notes = [_note("C3", p) for p in (0.0, 1.0)]
        result = run_deterministic_rhythm_analysis(notes, 4, clip_length_beats=8)
        trailing = _obs(result, "TRAILING_EMPTY")
        assert len(trailing) == 1
        assert trailing[0].value["bars"] == 1
        assert not _obs(result, "EMPTY_BARS")

    def test_trailing_empty_suppressed_when_inferred(self) -> None:
        notes = [_note("C3", p) for p in (0.0, 1.0)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        assert result.clip_length_inferred is True
        assert not _obs(result, "TRAILING_EMPTY")

    def test_clip_length_not_multiple_uses_ceil_bars(self) -> None:
        notes = [_note("C3", 12.5)]
        result = run_deterministic_rhythm_analysis(notes, 4, clip_length_beats=13)
        hits = result.lanes[0].hits_per_bar
        assert len(hits) == 4
        assert hits[3] == 1
        assert hits[0:3] == [0, 0, 0]

    def test_chords_auto_pitched_single_lane(self) -> None:
        notes = [_note(p, pos) for pos in (0.0, 1.0, 2.0) for p in ("C3", "E3", "G3")]
        result = run_deterministic_rhythm_analysis(notes, 4)
        assert result.routing.material == "pitched"
        assert len(result.lanes) == 1
        assert result.lanes[0].lane_id == "all"

    def test_below_thresholds_stats_but_no_observations(self) -> None:
        notes = [_note("C3", p) for p in (0.0, 1.0, 2.0)]
        result = run_deterministic_rhythm_analysis(notes, 4)
        lane = result.lanes[0]
        assert lane.count == 3
        assert lane.timing is not None
        assert lane.velocity is not None
        assert lane.timing.dev_mean == pytest.approx(0.0)
        timing_velocity_codes = {
            "SWING_8TH",
            "UNQUANTIZED",
            "LAID_BACK",
            "PUSHED",
            "LOOSE",
            "UNIFORM_VELOCITY",
            "ACCENTS",
            "GHOST_NOTES",
        }
        assert not (set(_codes(result)) & timing_velocity_codes)

    def test_empty_notes_raises(self) -> None:
        with pytest.raises(ValueError):
            run_deterministic_rhythm_analysis([], 4)

    def test_lane_names_labels(self) -> None:
        notes = [_note("C1", p) for p in (0.0, 2.0, 4.0, 6.0)]
        result = run_deterministic_rhythm_analysis(
            notes,
            4,
            material="percussion",
            lane_names={36: "bass chop"},
        )
        lane = next(l for l in result.lanes if l.lane_id == "36")
        assert lane.label == "bass chop"
        assert lane.pitch_name == "C1"


class TestRealClipTwinPeaks:
    def test_real_clip_matches_spec(self) -> None:
        path = _FIXTURES_DIR / "real_2_twin_peaks_drums.mid"
        load_result = load_midi_notes(path, skip_drum_channel=False)

        assert load_result.tempo_bpm is None
        assert load_result.track_name == "2-twin_peaks [2026-07-14 142341] 1"

        result = run_deterministic_rhythm_analysis(
            load_result.notes,
            load_result.beats_per_bar,
            clip_length_beats=16,
        )

        # Роутинг.
        assert result.routing.material == "percussion"
        assert result.routing.monophonic_ratio == pytest.approx(10 / 13, abs=1e-3)
        assert result.routing.distinct_pitches == 4
        assert result.routing.chromatic_neighbor_ratio == pytest.approx(0.5, abs=1e-3)

        # Лейны и счётчики.
        assert [l.lane_id for l in result.lanes] == ["all", "36", "41", "42", "44"]
        assert {l.lane_id: l.count for l in result.lanes} == {
            "all": 16,
            "36": 5,
            "41": 3,
            "42": 4,
            "44": 4,
        }

        # Лейн 42 — цикл.
        lane42 = next(l for l in result.lanes if l.lane_id == "42")
        assert lane42.cycle is not None
        assert lane42.cycle.period_beats == 3.0
        assert lane42.cycle.realign_bars == 3
        assert lane42.cycle.aligns_with_bar is False
        assert lane42.cycle.interval_cv == pytest.approx(0.043, abs=0.005)
        cycle42 = _obs(result, "CYCLE", "42")
        assert len(cycle42) == 1
        assert cycle42[0].confidence == pytest.approx(0.71, abs=0.02)

        # Лейн 44 — цикл.
        lane44 = next(l for l in result.lanes if l.lane_id == "44")
        assert lane44.cycle is not None
        assert lane44.cycle.period_beats == 3.0
        assert lane44.cycle.realign_bars == 3
        assert lane44.cycle.interval_cv == pytest.approx(0.127, abs=0.005)
        cycle44 = _obs(result, "CYCLE", "44")
        assert len(cycle44) == 1
        assert cycle44[0].confidence == pytest.approx(0.15, abs=0.03)

        # Лейны 36, 41 — цикла нет.
        assert next(l for l in result.lanes if l.lane_id == "36").cycle is None
        assert next(l for l in result.lanes if l.lane_id == "41").cycle is None

        # Плотность и форма.
        assert result.lanes[0].hits_per_bar == [6, 4, 6, 0]
        trailing = _obs(result, "TRAILING_EMPTY")
        assert len(trailing) == 1
        assert trailing[0].value["bars"] == 1
        assert not _obs(result, "EMPTY_BARS")

        # Тайминг лейна all.
        timing_all = result.lanes[0].timing
        assert timing_all.dev_std == pytest.approx(0.039, abs=0.003)
        codes = _codes(result)
        assert "LOOSE" in codes
        assert "UNQUANTIZED" not in codes
        assert "SWING_8TH" not in codes
        assert "LAID_BACK" not in codes
        assert "PUSHED" not in codes

        # Velocity — равномерности нет ни в одном лейне.
        assert not any(
            o.code == "UNIFORM_VELOCITY" for o in result.observations
        )


class TestHarness:
    def test_rhythm_report_shows_cycles_loose_trailing(self, capsys: pytest.CaptureFixture[str]) -> None:
        path = _FIXTURES_DIR / "real_2_twin_peaks_drums.mid"
        analyze_midi_file(path, analysis="rhythm", clip_bars=4)
        out = capsys.readouterr().out
        assert "CYCLE" in out
        assert "lane 42" in out
        assert "lane 44" in out
        assert "LOOSE" in out
        assert "TRAILING_EMPTY" in out

    def test_harmony_json_keys_unchanged(self, capsys: pytest.CaptureFixture[str]) -> None:
        path = _FIXTURES_DIR / "1_clean_functional.mid"
        analyze_midi_file(path, emit_json=True)
        out = capsys.readouterr().out
        data = json.loads(out[out.index("{") :])
        assert set(data.keys()) == {
            "key",
            "key_confidence",
            "key_alternate_gap",
            "confidence",
            "tonal_mode",
            "tonal_mode_reason",
            "chords",
            "scale_notes",
            "raw_notes",
            "chord_events",
        }

    def test_both_json_has_harmony_and_rhythm(self, capsys: pytest.CaptureFixture[str]) -> None:
        path = _FIXTURES_DIR / "1_clean_functional.mid"
        analyze_midi_file(path, analysis="both", emit_json=True)
        out = capsys.readouterr().out
        data = json.loads(out[out.index("{") :])
        assert set(data.keys()) == {"harmony", "rhythm"}
        assert "observations" in data["rhythm"]

    def test_both_harmony_matches_harmony_mode(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        midi_path = tmp_path / "mixed.mid"
        mid = mido.MidiFile(ticks_per_beat=96)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
        track.append(mido.Message("note_on", channel=9, note=36, velocity=100, time=0))
        track.append(mido.Message("note_off", channel=9, note=36, velocity=0, time=96))
        track.append(mido.Message("note_on", channel=0, note=60, velocity=100, time=0))
        track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=96))
        mid.save(str(midi_path))

        analyze_midi_file(midi_path, emit_json=True)
        harmony_out = capsys.readouterr().out
        harmony_data = json.loads(harmony_out[harmony_out.index("{") :])

        analyze_midi_file(midi_path, analysis="both", emit_json=True)
        both_out = capsys.readouterr().out
        both_data = json.loads(both_out[both_out.index("{") :])

        assert both_data["harmony"] == harmony_data

    @pytest.mark.parametrize("analysis", ["rhythm", "both"])
    def test_with_llm_requires_harmony_mode(
        self, analysis: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _FIXTURES_DIR / "1_clean_functional.mid"
        with pytest.raises(SystemExit) as exc:
            main([str(path), "--analysis", analysis, "--with-llm"])
        assert exc.value.code == 1
        assert "--with-llm" in capsys.readouterr().err

    def test_load_skips_drum_channel_by_default(self, tmp_path: Path) -> None:
        midi_path = tmp_path / "drums_ch9.mid"
        mid = mido.MidiFile(ticks_per_beat=96)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
        track.append(mido.Message("note_on", channel=9, note=36, velocity=100, time=0))
        track.append(mido.Message("note_off", channel=9, note=36, velocity=0, time=96))
        track.append(mido.Message("note_on", channel=0, note=60, velocity=100, time=0))
        track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=96))
        mid.save(str(midi_path))

        default_load = load_midi_notes(midi_path)
        assert len(default_load.notes) == 1

        keep_drums = load_midi_notes(midi_path, skip_drum_channel=False)
        assert len(keep_drums.notes) == 2

    def test_tempo_and_track_name_extracted(self, tmp_path: Path) -> None:
        midi_path = tmp_path / "tempo.mid"
        mid = mido.MidiFile(ticks_per_beat=96)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name="my drum loop"))
        track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(141)))
        track.append(mido.Message("note_on", channel=0, note=60, velocity=100, time=0))
        track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=96))
        mid.save(str(midi_path))

        load_result = load_midi_notes(midi_path)
        assert load_result.tempo_bpm == pytest.approx(141.0, abs=1e-3)
        assert load_result.track_name == "my drum loop"

    def test_lane_names_file(self, tmp_path: Path) -> None:
        path = tmp_path / "lanes.json"
        path.write_text('{"36": "bass chop", "42": "hat"}', encoding="utf-8")
        lane_names = _load_lane_names(path)
        assert lane_names == {36: "bass chop", 42: "hat"}

    def test_lane_names_file_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            _load_lane_names(path)

    def test_lane_names_file_bad_key(self, tmp_path: Path) -> None:
        path = tmp_path / "badkey.json"
        path.write_text('{"abc": "x"}', encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid pitch key"):
            _load_lane_names(path)
