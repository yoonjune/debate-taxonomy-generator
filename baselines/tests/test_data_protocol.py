from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from moderator_bench.audio import materialize_probe
from moderator_bench.config import read_config
from moderator_bench.data import Dataset
from moderator_bench.protocol import make_probe_plan


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data_sample"
CONFIG = REPO_ROOT / "baselines" / "configs" / "evaluation.json"


def test_current_development_dataset_contract() -> None:
    dataset = Dataset.load(DATA_ROOT)
    assert len(dataset.debates) == 10
    assert len(dataset.probes) == 143
    assert "{{" not in dataset.rendered_prompt("L000")


def test_clock_probe_releases_before_early_boundary() -> None:
    dataset = Dataset.load(DATA_ROOT)
    config = read_config(CONFIG)
    plan = make_probe_plan(dataset.probes["L000_p02"], config)
    assert plan.release_sec == 33.56
    assert plan.release_sec < plan.decision_earliest_sec
    assert plan.decision_deadline_sec == 38.56
    assert plan.decision_latest_sec == 41.56


def test_negative_probe_has_matched_observation_window() -> None:
    dataset = Dataset.load(DATA_ROOT)
    config = read_config(CONFIG)
    probe = next(probe for probe in dataset.probes.values() if probe["label"] == "none")
    plan = make_probe_plan(probe, config)
    assert plan.decision_earliest_sec is None
    assert plan.decision_deadline_sec is None
    assert plan.release_sec < plan.decision_latest_sec
    assert plan.observe_end_sec > plan.decision_latest_sec


def test_materialized_agent_stream_is_silent_after_release(tmp_path: Path) -> None:
    dataset = Dataset.load(DATA_ROOT)
    config = read_config(CONFIG)
    probe = dataset.probes["L000_p02"]
    plan = make_probe_plan(probe, config)
    manifest_path = materialize_probe(dataset, probe, plan, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    teacher, sample_rate = sf.read(manifest["input"]["agent_teacher_audio"], dtype="float32")
    release_sample = int(plan.release_sec * sample_rate)
    assert np.max(np.abs(teacher[release_sample:])) == 0.0

    user, user_rate = sf.read(manifest["input"]["user_audio"], dtype="float32")
    assert user_rate == sample_rate == 24000
    assert np.max(np.abs(user[release_sample:])) > 0.0
