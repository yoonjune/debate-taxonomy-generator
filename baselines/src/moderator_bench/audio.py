from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .data import Dataset, sha256_file, sha256_text
from .protocol import ProbePlan


@dataclass(frozen=True)
class DuplexStreams:
    sample_rate: int
    user: np.ndarray
    agent: np.ndarray
    timeline: dict[str, Any]


def build_duplex_streams(dataset: Dataset, debate_id: str, sample_rate: int = 24000) -> DuplexStreams:
    timeline = json.loads(dataset.timeline_path(debate_id).read_text(encoding="utf-8"))
    total_sec = max(float(timeline["total_sec"]), max(float(t["end_sec"]) for t in timeline["turns"]))
    n_samples = int(np.ceil(total_sec * sample_rate)) + 1
    user = np.zeros(n_samples, dtype=np.float32)
    agent = np.zeros(n_samples, dtype=np.float32)

    for turn in timeline["turns"]:
        path = dataset.turn_audio_path(debate_id, int(turn["i"]))
        waveform, source_rate = sf.read(path, dtype="float32", always_2d=True)
        waveform = waveform.mean(axis=1)
        if source_rate != sample_rate:
            raise ValueError(
                f"{path}: sample rate {source_rate}; expected {sample_rate}. "
                "Resampling must be explicit so timing does not change silently."
            )
        start = int(round(float(turn["start_sec"]) * sample_rate))
        expected = int(round(float(turn["dur_sec"]) * sample_rate))
        if abs(len(waveform) - expected) > int(0.08 * sample_rate):
            raise ValueError(
                f"{path}: audio length {len(waveform) / sample_rate:.3f}s differs from "
                f"timeline {float(turn['dur_sec']):.3f}s"
            )
        end = min(start + len(waveform), n_samples)
        target = agent if turn["speaker"] == "MOD" else user
        target[start:end] += waveform[: end - start]

    return DuplexStreams(
        sample_rate=sample_rate,
        user=np.clip(user, -1.0, 1.0),
        agent=np.clip(agent, -1.0, 1.0),
        timeline=timeline,
    )


def materialize_probe(
    dataset: Dataset,
    probe: dict[str, Any],
    plan: ProbePlan,
    output_dir: str | Path,
    sample_rate: int = 24000,
) -> Path:
    output_dir = Path(output_dir)
    probe_dir = output_dir / plan.probe_id
    probe_dir.mkdir(parents=True, exist_ok=True)
    streams = build_duplex_streams(dataset, plan.debate_id, sample_rate=sample_rate)
    end_sample = min(len(streams.user), int(round(plan.observe_end_sec * sample_rate)))
    release_sample = min(end_sample, int(round(plan.release_sec * sample_rate)))
    user = streams.user[:end_sample].copy()
    agent_teacher = streams.agent[:end_sample].copy()
    agent_teacher[release_sample:] = 0.0

    _apply_counterfactual_user_silence(user, streams.timeline, probe, plan, sample_rate)

    user_path = probe_dir / "user.wav"
    teacher_path = probe_dir / "agent_teacher.wav"
    sf.write(user_path, user, sample_rate, subtype="PCM_16")
    sf.write(teacher_path, agent_teacher, sample_rate, subtype="PCM_16")

    prompt = dataset.rendered_prompt(plan.debate_id)
    prompt_path = probe_dir / "system_prompt.txt"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    voice_id = dataset.debates[plan.debate_id]["speakers"]["MOD"]["voice_id"]
    voice_path = dataset.voice_path(voice_id)

    manifest = {
        "schema_version": "0.1",
        "plan": plan.to_dict(),
        "input": {
            "user_audio": str(user_path.resolve()),
            "agent_teacher_audio": str(teacher_path.resolve()),
            "teacher_forcing_until_sec": plan.release_sec,
            "system_prompt": str(prompt_path.resolve()),
            "moderator_reference_voice": str(voice_path.resolve()),
            "sample_rate": sample_rate,
        },
        "gold": {
            "label": probe["label"],
            "neg_kind": probe.get("neg_kind"),
            "trigger": probe.get("trigger"),
        },
        "hashes": {
            "user_audio_sha256": sha256_file(user_path),
            "agent_teacher_audio_sha256": sha256_file(teacher_path),
            "system_prompt_sha256": sha256_text(prompt),
            "moderator_reference_voice_sha256": sha256_file(voice_path),
        },
    }
    manifest_path = probe_dir / "input_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def _apply_counterfactual_user_silence(
    user: np.ndarray,
    timeline: dict[str, Any],
    probe: dict[str, Any],
    plan: ProbePlan,
    sample_rate: int,
) -> None:
    if probe.get("kind") not in {"event", "content"} or probe.get("label") == "none":
        return
    turns = {int(turn["i"]): turn for turn in timeline["turns"]}
    next_turn = turns.get(int(probe["before_turn"]) + 1)
    if not next_turn or next_turn["speaker"] == "MOD":
        return
    start = int(round(float(next_turn["start_sec"]) * sample_rate))
    end = min(len(user), int(round(plan.decision_latest_sec * sample_rate)))
    if end > start:
        user[start:end] = 0.0
