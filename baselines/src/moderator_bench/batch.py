from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from .adapters import FixtureAdapter, PersonaPlexAdapter
from .audio import materialize_probe
from .config import read_config
from .data import Dataset, sha256_file
from .evaluation.temporal import score_generation
from .protocol import make_probe_plan
from .run import run_probe


def prepare_batch(
    data_root: str | Path,
    evaluation_config_path: str | Path,
    output_dir: str | Path,
    debate_id: str | None = None,
    label: str | None = None,
    limit: int | None = None,
    alignment_index_path: str | Path | None = None,
) -> Path:
    dataset = Dataset.load(data_root)
    evaluation = read_config(evaluation_config_path)
    selected = [
        probe for probe in dataset.probes.values()
        if (debate_id is None or probe["debate_id"] == debate_id)
        and (label is None or probe["label"] == label)
    ]
    selected.sort(key=lambda row: row["probe_id"])
    if limit is not None:
        selected = selected[:limit]
    manifests = []
    for probe in selected:
        plan = make_probe_plan(probe, evaluation)
        manifests.append(str(materialize_probe(
            dataset,
            probe,
            plan,
            output_dir,
            alignment_index_path=alignment_index_path,
        ).resolve()))
    batch = {
        "schema_version": "0.1",
        "data_root": str(dataset.root),
        "debates_sha256": sha256_file(dataset.root / "debates.jsonl"),
        "probes_sha256": sha256_file(dataset.root / "probes.jsonl"),
        "filters": {"debate_id": debate_id, "label": label, "limit": limit},
        "alignment_index": (
            str(Path(alignment_index_path).resolve()) if alignment_index_path is not None else None
        ),
        "n": len(manifests),
        "input_manifests": manifests,
    }
    path = Path(output_dir).resolve() / "batch_input.json"
    path.write_text(json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run_batch(
    batch_input_path: str | Path,
    model_config_path: str | Path,
    output_dir: str | Path,
    fixture_mode: str | None = None,
) -> Path:
    batch_input = read_config(batch_input_path)
    model_config = read_config(model_config_path)
    if fixture_mode:
        adapter = FixtureAdapter(fixture_mode)
    elif model_config["adapter"] == "personaplex":
        adapter = PersonaPlexAdapter()
    else:
        raise ValueError(f"unknown adapter: {model_config['adapter']}")

    rows: list[dict[str, Any]] = []
    for manifest in batch_input["input_manifests"]:
        probe_id = read_config(manifest)["plan"]["probe_id"]
        try:
            generation = run_probe(
                manifest,
                model_config_path,
                output_dir,
                fixture_mode=fixture_mode,
                adapter_override=adapter,
            )
            rows.append({"probe_id": probe_id, "status": "GENERATED", "generation": str(generation)})
        except Exception as exc:  # Preserve failures and continue without retrying.
            rows.append({
                "probe_id": probe_id,
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })
    output = {
        "schema_version": "0.1",
        "batch_input": str(Path(batch_input_path).resolve()),
        "model_config": str(Path(model_config_path).resolve()),
        "fixture_mode": fixture_mode,
        "rows": rows,
    }
    path = Path(output_dir).resolve() / (
        f"batch_run_fixture_{fixture_mode}.json" if fixture_mode else
        f"batch_run_{model_config['model_id'].replace('/', '__')}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def score_batch(batch_run_path: str | Path, evaluation_config_path: str | Path) -> Path:
    batch_run = read_config(batch_run_path)
    rows = []
    for row in batch_run["rows"]:
        if row["status"] != "GENERATED":
            rows.append({"probe_id": row["probe_id"], "status": "SKIPPED_GENERATION_ERROR"})
            continue
        try:
            score = score_generation(row["generation"], evaluation_config_path)
            rows.append({"probe_id": row["probe_id"], "status": "SCORED", "score": str(score)})
        except Exception as exc:
            rows.append({
                "probe_id": row["probe_id"],
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            })
    output = {
        "schema_version": "0.1",
        "batch_run": str(Path(batch_run_path).resolve()),
        "rows": rows,
    }
    path = Path(batch_run_path).resolve().with_name(Path(batch_run_path).stem + "_scores.json")
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
