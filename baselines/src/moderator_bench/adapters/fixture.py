from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .base import GenerationResult


class FixtureAdapter:
    """Model-free adapter for checking replay and scoring plumbing.

    `oracle_tone` emits a tone at the gold deadline for positive probes and
    remains silent for negatives. `silence` never emits a tone. Fixture output
    is never a model baseline result.
    """

    def __init__(self, mode: str):
        if mode not in {"oracle_tone", "silence"}:
            raise ValueError(f"unknown fixture mode: {mode}")
        self.mode = mode

    def generate(
        self,
        manifest: dict[str, Any],
        model_config: dict[str, Any],
        output_dir: Path,
    ) -> GenerationResult:
        started = time.monotonic()
        user, sample_rate = sf.read(manifest["input"]["user_audio"], dtype="float32")
        output = np.zeros_like(user, dtype=np.float32)
        plan = manifest["plan"]
        onset = None
        if self.mode == "oracle_tone" and plan["label"] != "none":
            onset = float(plan["decision_deadline_sec"])
            start = int(round(onset * sample_rate))
            end = min(len(output), start + int(0.5 * sample_rate))
            time_axis = np.arange(end - start, dtype=np.float32) / sample_rate
            output[start:end] = 0.15 * np.sin(2 * np.pi * 440.0 * time_axis)

        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "output.wav"
        text_path = output_dir / "output_text.json"
        sf.write(audio_path, output, sample_rate, subtype="PCM_16")
        text_path.write_text(json.dumps({
            "fixture": True,
            "mode": self.mode,
            "synthetic_onset_sec": onset,
        }, indent=2) + "\n", encoding="utf-8")
        return GenerationResult(
            output_audio=audio_path,
            output_text=text_path,
            sample_rate=sample_rate,
            duration_sec=len(output) / sample_rate,
            wall_time_sec=time.monotonic() - started,
            runtime_metadata={"fixture": True, "mode": self.mode},
        )
