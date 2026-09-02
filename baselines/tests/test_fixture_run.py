from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from moderator_bench.audio import materialize_probe
from moderator_bench.config import read_config
from moderator_bench.data import Dataset
from moderator_bench.protocol import make_probe_plan
from moderator_bench.run import run_probe


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data_sample"
EVAL_CONFIG = REPO_ROOT / "baselines" / "configs" / "evaluation.json"
MODEL_CONFIG = REPO_ROOT / "baselines" / "configs" / "models" / "personaplex_base.json"


def test_oracle_fixture_emits_after_release_at_deadline(tmp_path: Path) -> None:
    dataset = Dataset.load(DATA_ROOT)
    probe = dataset.probes["L000_p02"]
    plan = make_probe_plan(probe, read_config(EVAL_CONFIG))
    manifest = materialize_probe(dataset, probe, plan, tmp_path / "prepared")
    generation_path = run_probe(manifest, MODEL_CONFIG, tmp_path / "runs", "oracle_tone")
    generation = json.loads(generation_path.read_text(encoding="utf-8"))
    waveform, sample_rate = sf.read(generation["generation"]["output_audio"], dtype="float32")
    before = waveform[: int(plan.decision_deadline_sec * sample_rate)]
    after = waveform[int(plan.decision_deadline_sec * sample_rate) :]
    assert np.max(np.abs(before)) == 0.0
    assert np.max(np.abs(after)) > 0.0
    assert generation["status"] == "GENERATED_NOT_SCORED"
