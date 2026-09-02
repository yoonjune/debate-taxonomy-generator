from __future__ import annotations

import json
from pathlib import Path

from moderator_bench.audio import materialize_probe
from moderator_bench.config import read_config
from moderator_bench.data import Dataset
from moderator_bench.evaluation.temporal import _generated_text_after_release, score_generation
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


def test_generated_text_excludes_forced_rows_at_release_boundary(tmp_path: Path) -> None:
    text_path = tmp_path / "output_text.json"
    text_path.write_text(
        json.dumps([
            {"time_sec": 10.0, "piece": " forced", "agent_text_forced": True},
            {"time_sec": 10.0, "piece": " free", "agent_text_forced": False},
            {"time_sec": 10.08, "piece": " text", "agent_text_forced": False},
        ]),
        encoding="utf-8",
    )
    generation = {"generation": {"output_text": str(text_path)}}
    assert _generated_text_after_release(generation, 10.0) == "free text"


def test_runtime_output_release_boundary_controls_scoring(tmp_path: Path) -> None:
    generation_path = _prepare_and_run("L000_p02", tmp_path, "oracle_tone")
    generation = json.loads(generation_path.read_text(encoding="utf-8"))
    manifest = json.loads(Path(generation["input_manifest"]).read_text(encoding="utf-8"))
    effective_release = float(manifest["plan"]["release_sec"]) + 0.08
    generation["generation"]["runtime_metadata"]["release_sec_effective_output"] = effective_release
    generation_path.write_text(json.dumps(generation), encoding="utf-8")

    score = json.loads(score_generation(generation_path, EVAL_CONFIG).read_text(encoding="utf-8"))
    assert score["speech_detection"]["start_sec"] == effective_release
