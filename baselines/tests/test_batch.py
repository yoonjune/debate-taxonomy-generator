from __future__ import annotations

import json
from pathlib import Path

from moderator_bench.batch import prepare_batch, run_batch, score_batch


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data_sample"
EVAL_CONFIG = REPO_ROOT / "baselines" / "configs" / "evaluation.json"
MODEL_CONFIG = REPO_ROOT / "baselines" / "configs" / "models" / "personaplex_base.json"


def test_two_probe_fixture_batch(tmp_path: Path) -> None:
    prepared = prepare_batch(DATA_ROOT, EVAL_CONFIG, tmp_path / "prepared", limit=2)
    prepared_value = json.loads(prepared.read_text(encoding="utf-8"))
    assert prepared_value["n"] == 2

    batch_run = run_batch(prepared, MODEL_CONFIG, tmp_path / "runs", "oracle_tone")
    run_value = json.loads(batch_run.read_text(encoding="utf-8"))
    assert [row["status"] for row in run_value["rows"]] == ["GENERATED", "GENERATED"]

    batch_scores = score_batch(batch_run, EVAL_CONFIG)
    scores_value = json.loads(batch_scores.read_text(encoding="utf-8"))
    assert [row["status"] for row in scores_value["rows"]] == ["SCORED", "SCORED"]
