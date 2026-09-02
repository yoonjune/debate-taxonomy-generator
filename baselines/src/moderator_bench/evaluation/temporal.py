from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import soundfile as sf

from ..config import read_config
from ..data import sha256_file
from .vad import detect_speech_segments


def score_generation(
    generation_path: str | Path,
    evaluation_config_path: str | Path,
    content_judgment_path: str | Path | None = None,
) -> Path:
    generation_path = Path(generation_path).resolve()
    generation = read_config(generation_path)
    input_manifest = read_config(generation["input_manifest"])
    evaluation = read_config(evaluation_config_path)
    plan = input_manifest["plan"]

    waveform, sample_rate = sf.read(
        generation["generation"]["output_audio"], dtype="float32", always_2d=True
    )
    waveform = waveform.mean(axis=1)
    if sample_rate != generation["generation"]["sample_rate"]:
        raise ValueError("generation sample-rate metadata does not match output audio")
    segments = detect_speech_segments(
        waveform,
        sample_rate,
        start_sec=float(plan["release_sec"]),
        end_sec=float(plan["observe_end_sec"]),
        config=evaluation["vad"],
    )
    first_onset = segments[0].start_sec if segments else None
    temporal = _classify(plan, first_onset)
    generated_text = _generated_text_after_release(generation, float(plan["release_sec"]))
    content = _load_content_judgment(content_judgment_path)

    if plan["label"] == "none":
        joint_pass = temporal["pass"]
    elif content["status"] == "JUDGED":
        joint_pass = temporal["pass"] and bool(content["pass"])
    else:
        joint_pass = None

    score = {
        "schema_version": "0.1",
        "probe_id": generation["probe_id"],
        "model": generation["model"],
        "gold": input_manifest["gold"],
        "plan": plan,
        "speech_detection": {
            "first_onset_sec": first_onset,
            "segments": [segment.to_dict() for segment in segments],
            "vad_config": evaluation["vad"],
        },
        "temporal": temporal,
        "generated_text_after_release": generated_text,
        "content": content,
        "joint_pass": joint_pass,
        "provenance": {
            "generation": str(generation_path),
            "generation_sha256": sha256_file(generation_path),
            "evaluation_config": str(Path(evaluation_config_path).resolve()),
            "evaluation_config_sha256": sha256_file(Path(evaluation_config_path)),
        },
    }
    score_path = generation_path.parent / "score.json"
    score_path.write_text(json.dumps(score, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_judge_packet(generation_path.parent / "judge_packet.json", score, input_manifest)
    return score_path


def _classify(plan: dict[str, Any], onset: float | None) -> dict[str, Any]:
    positive = plan["label"] != "none"
    if onset is None:
        status = "MISSED" if positive else "CORRECT_SILENCE"
        passed = not positive
    elif not positive:
        status = "FALSE_POSITIVE"
        passed = False
    elif onset < float(plan["decision_earliest_sec"]):
        status = "PREMATURE"
        passed = False
    elif onset <= float(plan["decision_latest_sec"]):
        status = "ON_TIME"
        passed = True
    else:
        status = "LATE"
        passed = False
    deadline = plan.get("decision_deadline_sec")
    return {
        "status": status,
        "pass": passed,
        "should_speak": positive,
        "spoke": onset is not None,
        "onset_sec": onset,
        "onset_minus_deadline_sec": (
            round(onset - float(deadline), 6) if onset is not None and deadline is not None else None
        ),
    }


def _generated_text_after_release(generation: dict[str, Any], release_sec: float) -> str | None:
    text_path = generation["generation"].get("output_text")
    if not text_path:
        return None
    value = json.loads(Path(text_path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        return None
    pieces = [
        row.get("piece") or ""
        for row in value
        if float(row.get("time_sec", -1)) >= release_sec and row.get("piece")
    ]
    return "".join(pieces).strip() or None


def _load_content_judgment(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"status": "NOT_JUDGED", "pass": None, "predicted_label": None, "reason": None}
    value = read_config(path)
    required = {"pass", "predicted_label", "reason"}
    if not required.issubset(value):
        raise ValueError(f"content judgment missing keys: {sorted(required - set(value))}")
    return {"status": "JUDGED", **value}


def _write_judge_packet(path: Path, score: dict[str, Any], manifest: dict[str, Any]) -> None:
    packet = {
        "probe_id": score["probe_id"],
        "instruction": (
            "Judge only the generated moderator content. Decide whether it performs the gold action "
            "for the visible trigger without taking a side or inventing facts. Do not judge timing."
        ),
        "gold_label": manifest["gold"]["label"],
        "gold_trigger": manifest["gold"].get("trigger"),
        "generated_text": score["generated_text_after_release"],
        "expected_output_schema": {
            "pass": "boolean",
            "predicted_label": "A1|A2-1|A2-2|A3-1|A3-2|A4|A5|B1|B2|none|other",
            "reason": "short evidence-based string",
        },
    }
    path.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
