from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from moderator_bench.alignment import align_moderator_turns
from moderator_bench.audio import materialize_probe
from moderator_bench.config import read_config
from moderator_bench.data import Dataset
from moderator_bench.protocol import make_probe_plan
from moderator_bench.text_replay import build_text_replay_schedule

from test_alignment import FakeAligner


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data_sample"
ALIGNER_CONFIG = ROOT / "baselines" / "configs" / "aligners" / "qwen3_forced_aligner.json"
EVALUATION_CONFIG = ROOT / "baselines" / "configs" / "evaluation.json"


@dataclass(frozen=True)
class FakePiece:
    id: int
    piece: str
    begin: int
    end: int


@dataclass(frozen=True)
class FakeProto:
    pieces: list[FakePiece]


class WordTokenizer:
    def encode(self, text: str, *, out_type: str):
        assert out_type == "immutable_proto"
        pieces = []
        cursor = 0
        for token_id, surface in enumerate(text.split(), 100):
            begin = text.index(surface, cursor)
            end = begin + len(surface)
            pieces.append(FakePiece(token_id, "▁" + surface, begin, end))
            cursor = end
        return FakeProto(pieces)


def _prepared_with_alignment(tmp_path: Path) -> tuple[Path, dict]:
    alignment_index = align_moderator_turns(
        DATA_ROOT,
        ALIGNER_CONFIG,
        tmp_path / "alignments",
        debate_id="L000",
        limit=1,
        aligner_override=FakeAligner(),
    )
    dataset = Dataset.load(DATA_ROOT)
    probe = dataset.probes["L000_p02"]
    plan = make_probe_plan(probe, read_config(EVALUATION_CONFIG))
    manifest_path = materialize_probe(
        dataset,
        probe,
        plan,
        tmp_path / "prepared",
        alignment_index_path=alignment_index,
    )
    return manifest_path, json.loads(manifest_path.read_text())


def test_alignment_is_attached_only_for_moderator_history_before_release(tmp_path: Path) -> None:
    manifest_path, manifest = _prepared_with_alignment(tmp_path)
    assert manifest["schema_version"] == "0.2"
    alignment = manifest["input"]["moderator_text_alignment"]
    assert [turn["turn_index"] for turn in alignment["turns"]] == [0]
    assert Path(alignment["turns"][0]["artifact"]).is_file()
    assert manifest_path.is_file()


def test_dense_schedule_forces_padding_and_ordered_lexical_tokens(tmp_path: Path) -> None:
    _, manifest = _prepared_with_alignment(tmp_path)
    release = manifest["input"]["teacher_forcing_until_sec"]
    schedule = build_text_replay_schedule(
        manifest["input"]["moderator_text_alignment"],
        WordTokenizer(),
        frame_rate_hz=12.5,
        release_sec=release,
    )
    assert len(schedule.token_ids) == int(release * 12.5)
    assert len(schedule.lexical_rows) > 1
    frames = [row["frame_index"] for row in schedule.lexical_rows]
    assert frames == sorted(set(frames))
    assert all(frame < schedule.release_frame for frame in frames)
    assert [schedule.token_ids[frame] for frame in frames] == [
        row["token_id"] for row in schedule.lexical_rows
    ]
    assert 3 in schedule.token_ids


def test_changed_alignment_artifact_is_rejected(tmp_path: Path) -> None:
    _, manifest = _prepared_with_alignment(tmp_path)
    alignment = manifest["input"]["moderator_text_alignment"]
    artifact_path = Path(alignment["turns"][0]["artifact"])
    artifact_path.write_text(artifact_path.read_text() + " ")
    try:
        build_text_replay_schedule(
            alignment,
            WordTokenizer(),
            frame_rate_hz=12.5,
            release_sec=manifest["input"]["teacher_forcing_until_sec"],
        )
    except ValueError as exc:
        assert "hash changed" in str(exc)
    else:
        raise AssertionError("modified alignment artifact was accepted")
