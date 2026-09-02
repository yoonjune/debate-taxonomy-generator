from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from .adapters import FixtureAdapter, PersonaPlexAdapter
from .config import read_config
from .data import sha256_file, sha256_text


def run_probe(
    input_manifest_path: str | Path,
    model_config_path: str | Path,
    output_dir: str | Path,
    fixture_mode: str | None = None,
) -> Path:
    input_manifest_path = Path(input_manifest_path).resolve()
    model_config_path = Path(model_config_path).resolve()
    output_dir = Path(output_dir).resolve()
    manifest = read_config(input_manifest_path)
    model_config = read_config(model_config_path)

    if fixture_mode:
        adapter = FixtureAdapter(fixture_mode)
        run_name = f"fixture_{fixture_mode}"
    elif model_config["adapter"] == "personaplex":
        adapter = PersonaPlexAdapter()
        run_name = model_config["model_id"].replace("/", "__")
    else:
        raise ValueError(f"unknown adapter: {model_config['adapter']}")

    run_dir = output_dir / run_name / manifest["plan"]["probe_id"]
    result = adapter.generate(manifest, model_config, run_dir)
    generation = {
        "schema_version": "0.1",
        "probe_id": manifest["plan"]["probe_id"],
        "model": {
            "model_id": model_config["model_id"],
            "revision": model_config["revision"],
            "config_path": str(model_config_path),
            "config_sha256": sha256_file(model_config_path),
        },
        "input_manifest": str(input_manifest_path),
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "generation": result.to_dict(),
        "output_hashes": {
            "audio_sha256": sha256_file(result.output_audio),
            "text_sha256": sha256_file(result.output_text) if result.output_text else None,
        },
        "environment": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "git_commit": _git_commit(input_manifest_path),
        },
        "status": "GENERATED_NOT_SCORED",
    }
    generation_path = run_dir / "generation.json"
    generation_path.write_text(json.dumps(generation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return generation_path


def _git_commit(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path.parent, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
