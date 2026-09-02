from __future__ import annotations

import json
from pathlib import Path

from moderator_bench.audio import materialize_probe
from moderator_bench.config import read_config
from moderator_bench.data import Dataset
from moderator_bench.evaluation.temporal import score_generation
from moderator_bench.protocol import make_probe_plan
from moderator_bench.run import run_probe


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data_sample"
EVAL_CONFIG = REPO_ROOT / "baselines" / "configs" / "evaluation.json"
MODEL_CONFIG = REPO_ROOT / "baselines" / "configs" / "models" / "personaplex_base.json"


def _prepare_and_run(probe_id: str, tmp_path: Path, fixture: str) -> Path:
    dataset = Dataset.load(DATA_ROOT)
    probe = dataset.probes[probe_id]
    plan = make_probe_plan(probe, read_config(EVAL_CONFIG))
    manifest = materialize_probe(dataset, probe, plan, tmp_path / "prepared")
    return run_probe(manifest, MODEL_CONFIG, tmp_path / "runs", fixture)


def test_oracle_tone_passes_positive_temporal_window(tmp_path: Path) -> None:
    generation = _prepare_and_run("L000_p02", tmp_path, "oracle_tone")
    score_path = score_generation(generation, EVAL_CONFIG)
    score = json.loads(score_path.read_text(encoding="utf-8"))
    assert score["temporal"]["status"] == "ON_TIME"
    assert score["temporal"]["pass"] is True
    assert score["content"]["status"] == "NOT_JUDGED"
    assert score["joint_pass"] is None
    assert (score_path.parent / "judge_packet.json").is_file()


def test_silence_fixture_misses_positive_probe(tmp_path: Path) -> None:
    generation = _prepare_and_run("L000_p02", tmp_path, "silence")
    score = json.loads(score_generation(generation, EVAL_CONFIG).read_text(encoding="utf-8"))
    assert score["temporal"]["status"] == "MISSED"
    assert score["temporal"]["pass"] is False


def test_oracle_fixture_stays_silent_for_negative_probe(tmp_path: Path) -> None:
    dataset = Dataset.load(DATA_ROOT)
    negative_id = next(p["probe_id"] for p in dataset.probes.values() if p["label"] == "none")
    generation = _prepare_and_run(negative_id, tmp_path, "oracle_tone")
    score = json.loads(score_generation(generation, EVAL_CONFIG).read_text(encoding="utf-8"))
    assert score["temporal"]["status"] == "CORRECT_SILENCE"
    assert score["joint_pass"] is True
