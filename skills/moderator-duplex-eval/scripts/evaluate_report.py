#!/usr/bin/env python3
"""Deterministic EVAL_SETTING scorer for gap-gated moderator reports.

This stage counts primary GT from removed moderator utterance IDs, scores timing,
extracts barge-in/stale candidates, and writes blinded semantic-review packets.
It never assigns semantic correctness by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import wave
from array import array
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE.parent / "references" / "eval-contract.json"
EPS = 1e-6


class ContractError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ContractError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(workspace: Path, raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else workspace / path


def norm_words(text: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", (text or "").lower())


def is_backchannel(turn: dict[str, Any], contract: dict[str, Any]) -> bool:
    words = norm_words(turn.get("text"))
    duration = float(turn["end_sec"]) - float(turn["start_sec"])
    spec = contract["backchannel"]
    if words == ["time"]:
        return False
    normalized = " ".join(words)
    fillers = set(spec["fillers"])
    filler_only = bool(words) and (
        normalized in fillers or all(word in fillers for word in words)
    )
    short_one_word = (
        duration < float(spec["max_duration_exclusive_sec"])
        and len(words) <= int(spec["max_words"])
    )
    return filler_only or short_one_word


def source_to_session(source_sec: float, spans: list[dict[str, Any]]) -> float:
    mapped: list[float] = []
    for span in spans:
        lo = float(span["source_start_sec"])
        hi = float(span["source_end_sec"])
        if lo - EPS <= source_sec <= hi + EPS:
            value = float(span["session_start_sec"]) + (source_sec - lo)
            mapped.append(value)
    if not mapped:
        raise ContractError(f"source time {source_sec:.6f}s has no clock-span mapping")
    if max(mapped) - min(mapped) > 1e-4:
        raise ContractError(f"source time {source_sec:.6f}s maps ambiguously: {mapped}")
    return sum(mapped) / len(mapped)


def classify_timing(onset: float | None, earliest: float, latest: float) -> str:
    if onset is None:
        return "MISSED"
    if onset < earliest - EPS:
        return "PREMATURE"
    if onset <= latest + EPS:
        return "ON_TIME"
    return "LATE"


def pcm16(path: Path) -> tuple[int, int, array]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    if width != 2:
        raise ContractError(f"{path}: expected PCM16, got sample width {width}")
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder == "big":
        values.byteswap()
    if channels != 1:
        raise ContractError(f"{path}: expected mono input, got {channels} channels")
    return sample_rate, frames, values


def wav_pcm_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with wave.open(str(path), "rb") as wav:
        while True:
            block = wav.readframes(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def interval_peak(values: array, start: int, end: int) -> int:
    start = max(0, start)
    end = min(len(values), end)
    if end <= start:
        return 0
    return max(abs(int(value)) for value in values[start:end])


def merge_intervals(spans: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((float(a), float(b)) for a, b in spans if b > a)
    merged: list[list[float]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1] + EPS:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(a, b) for a, b in merged]


def participant_vad(
    path: Path,
    declared_spans: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    sample_rate, frame_count, values = pcm16(path)
    frame_samples = round(sample_rate * float(spec["frame_ms"]) / 1000.0)
    min_speech_frames = math.ceil(float(spec["min_speech_ms"]) / float(spec["frame_ms"]))
    min_silence_frames = math.ceil(float(spec["min_silence_ms"]) / float(spec["frame_ms"]))
    threshold = int(spec["peak_abs_threshold"])
    active: list[int] = []
    for frame_i, start in enumerate(range(0, frame_count, frame_samples)):
        if interval_peak(values, start, min(start + frame_samples, frame_count)) >= threshold:
            active.append(frame_i)

    raw: list[tuple[float, float]] = []
    if active:
        group_start = active[0]
        last = active[0]
        for frame_i in active[1:]:
            if frame_i - last - 1 >= min_silence_frames:
                if last - group_start + 1 >= min_speech_frames:
                    raw.append((group_start * frame_samples / sample_rate,
                                min((last + 1) * frame_samples, frame_count) / sample_rate))
                group_start = frame_i
            last = frame_i
        if last - group_start + 1 >= min_speech_frames:
            raw.append((group_start * frame_samples / sample_rate,
                        min((last + 1) * frame_samples, frame_count) / sample_rate))

    supports = merge_intervals(
        (float(turn["session_start_sec"]), float(turn["session_end_sec"]))
        for turn in declared_spans
    )
    clipped: list[tuple[float, float]] = []
    for start, end in raw:
        for support_start, support_end in supports:
            lo, hi = max(start, support_start), min(end, support_end)
            if hi > lo:
                clipped.append((lo, hi))
    intervals = [
        {"session_start_sec": round(a, 6), "session_end_sec": round(b, 6)}
        for a, b in merge_intervals(clipped)
    ]
    meta = {
        "input_wav": str(path),
        "sample_rate": sample_rate,
        "frame_ms": spec["frame_ms"],
        "peak_abs_threshold": threshold,
        "min_speech_ms": spec["min_speech_ms"],
        "min_silence_ms": spec["min_silence_ms"],
        "declared_turn_intersection": True,
        "status": spec["status"],
    }
    return intervals, meta


def point_in_intervals(value: float, intervals: list[dict[str, float]]) -> bool:
    return any(
        float(span["session_start_sec"]) - EPS <= value < float(span["session_end_sec"]) - EPS
        for span in intervals
    )


def load_benchmark(root: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    debates = {row["debate_id"]: row for row in read_jsonl(root / "debates.jsonl")}
    probes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in read_jsonl(root / "probes.jsonl"):
        if row.get("label") != "none":
            probes[row["debate_id"]].append(row)
    return debates, probes


def phase_for_turn(debate: dict[str, Any], turn_id: int) -> int | None:
    rows = [row for row in debate["turns"] if int(row["i"]) == turn_id]
    if len(rows) != 1:
        raise ContractError(f"turn {turn_id}: expected one debate row, found {len(rows)}")
    if rows[0].get("speaker") != "MOD":
        raise ContractError(f"turn {turn_id}: expected MOD, got {rows[0].get('speaker')}")
    return rows[0].get("phase")


def actual_code(probe: dict[str, Any], phase: int | None) -> str:
    code = probe["label"]
    return "A4xf" if code == "A4" and phase == 2 else code


def build_gt(
    workspace: Path,
    benchmark_root: Path,
    run_plan: dict[str, Any],
    debate: dict[str, Any],
    probes: list[dict[str, Any]],
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    debate_id = run_plan["debate_id"]
    gap_path = resolve(workspace, run_plan["conditional_gap_file"])
    input_dir = resolve(workspace, run_plan["input_dir"])
    source_wav = input_dir / "user.wav"
    mix_path = benchmark_root / "audio" / "mix" / f"{debate_id}.json"
    gap_doc = read_json(gap_path)
    mix_doc = read_json(mix_path)
    expected_gap_hash = run_plan.get("conditional_gap_sha256")
    expected_source_hash = run_plan.get("source_audio_sha256")
    if expected_gap_hash and file_sha256(gap_path) != expected_gap_hash:
        raise ContractError(f"{debate_id}: conditional gap hash mismatch")
    if expected_source_hash and file_sha256(source_wav) != expected_source_hash:
        raise ContractError(f"{debate_id}: source audio hash mismatch")
    if gap_doc.get("timeline_sha256") and file_sha256(mix_path) != gap_doc["timeline_sha256"]:
        raise ContractError(f"{debate_id}: timeline hash mismatch")
    source_pcm_hash = wav_pcm_sha256(source_wav)
    if gap_doc.get("source_audio_sha256") and source_pcm_hash != gap_doc["source_audio_sha256"]:
        raise ContractError(f"{debate_id}: gap registry source PCM hash mismatch")

    sample_rate, source_frames, source_pcm = pcm16(source_wav)
    if sample_rate != int(gap_doc["sample_rate"]):
        raise ContractError(f"{debate_id}: sample-rate mismatch")
    turns = {int(row["i"]): row for row in mix_doc["turns"]}
    probe_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for probe in probes:
        probe_map[int(probe["before_turn"])].append(probe)

    seen: set[int] = set()
    gt_rows: list[dict[str, Any]] = []
    gap_checks: list[dict[str, Any]] = []
    for gap in gap_doc["gaps"]:
        start_sample = int(gap["start_sample"])
        end_sample = int(gap["end_sample"])
        if not (0 <= start_sample < end_sample <= source_frames):
            raise ContractError(f"{debate_id}/{gap['gap_id']}: invalid sample bounds")
        peak = interval_peak(source_pcm, start_sample, end_sample)
        if peak != 0:
            raise ContractError(f"{debate_id}/{gap['gap_id']}: registered gap is not exact-zero (peak={peak})")
        gap_checks.append({
            "gap_id": gap["gap_id"],
            "start_sample": start_sample,
            "end_sample": end_sample,
            "exact_zero_peak": peak,
            "mod_turn_ids": gap["mod_turn_ids"],
        })
        for raw_turn_id in gap["mod_turn_ids"]:
            turn_id = int(raw_turn_id)
            if turn_id in seen:
                raise ContractError(f"{debate_id}: duplicate mod_turn_id {turn_id}")
            seen.add(turn_id)
            if turn_id not in turns or turns[turn_id].get("speaker") != "MOD":
                raise ContractError(f"{debate_id}: mod_turn_id {turn_id} is missing or not MOD")
            turn = turns[turn_id]
            turn_start = round(float(turn["start_sec"]) * sample_rate)
            turn_end = round(float(turn["end_sec"]) * sample_rate)
            if turn_end <= start_sample or turn_start >= end_sample:
                raise ContractError(f"{debate_id}: MOD turn {turn_id} does not overlap {gap['gap_id']}")
            matches = probe_map.get(turn_id, [])
            if len(matches) != 1:
                raise ContractError(f"{debate_id}: MOD turn {turn_id} has {len(matches)} matching probes")
            probe = matches[0]
            phase = phase_for_turn(debate, turn_id)
            code = actual_code(probe, phase)
            if code not in contract["content"]["criteria"]:
                raise ContractError(f"{debate_id}: unsupported EVAL_SETTING code {code}")
            gt_rows.append({
                "gt_id": f"{debate_id}:mod:{turn_id}",
                "debate_id": debate_id,
                "mod_turn_id": turn_id,
                "gap_id": gap["gap_id"],
                "probe_id": probe["probe_id"],
                "code": code,
                "phase": phase,
                "source_mod_interval_sec": [float(turn["start_sec"]), float(turn["end_sec"])],
                "source_window_sec": [
                    float(probe["t_earliest"]),
                    float(probe["t_deadline"]),
                    float(probe["t_latest"]),
                ],
                "trigger_text": (probe.get("trigger") or {}).get("text") or [],
                "criteria": contract["content"]["criteria"][code],
            })
    gt_rows.sort(key=lambda row: (row["source_window_sec"][1], row["mod_turn_id"]))
    provenance = {
        "gap_file": str(gap_path),
        "gap_sha256": file_sha256(gap_path),
        "source_wav": str(source_wav),
        "source_wav_sha256": file_sha256(source_wav),
        "source_pcm_sha256": source_pcm_hash,
        "timeline": str(mix_path),
        "timeline_sha256": file_sha256(mix_path),
    }
    validation = {
        "status": "PASS",
        "registered_gap_count": len(gap_doc["gaps"]),
        "unique_removed_moderator_utterance_count": len(gt_rows),
        "gap_checks": gap_checks,
    }
    return gt_rows, provenance, validation


def first_candidate(
    turns: list[dict[str, Any]],
    start: float,
    end: float,
    contract: dict[str, Any],
) -> dict[str, Any] | None:
    for turn in turns:
        onset = float(turn["start_sec"])
        if start - EPS <= onset <= end + EPS and not is_backchannel(turn, contract):
            return turn
    return None


def score_timing(
    gt_rows: list[dict[str, Any]],
    run: dict[str, Any],
    debate: dict[str, Any],
    contract: dict[str, Any],
    anchor_decision: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    turns = sorted(run["model_turns"], key=lambda row: float(row["start_sec"]))
    spans = run["clock_spans"]
    timing_spec = contract["timing"]
    model_xf_end: float | None = None
    rows: list[dict[str, Any]] = []
    for gt in gt_rows:
        code = gt["code"]
        offsets = timing_spec["codes"][code]
        if code in ("A4xf", "A3-2"):
            if anchor_decision is None:
                row = dict(gt)
                row.update({
                    "session_window_sec": None,
                    "candidate_search_sec": None,
                    "window_anchor": "ANCHOR_PENDING_SEMANTIC_A3-1_REVIEW",
                    "timing": "ANCHOR_PENDING",
                    "onset_minus_deadline_sec": None,
                    "candidate": None,
                    "content_score": "UNKNOWN",
                    "joint_score": "UNKNOWN",
                })
                rows.append(row)
                continue
            if anchor_decision.get("opened_crossfire") is True:
                if model_xf_end is None:
                    raise ContractError(
                        f"{gt['debate_id']}: anchor decision says model opened crossfire "
                        "but no eligible A3-1 utterance exists"
                    )
                anchor = "model_A3-1_end"
                delay = float(timing_spec["crossfire_anchor"][f"{code}_deadline_after_anchor_sec"])
                deadline = model_xf_end + delay
            else:
                anchor = "reference_xf_open_fallback"
                delay = float(timing_spec["crossfire_anchor"][f"{code}_deadline_after_anchor_sec"])
                deadline = source_to_session(float(debate["xf_open_sec"]) + delay, spans)
        else:
            anchor = "source_probe_deadline"
            deadline = source_to_session(float(gt["source_window_sec"][1]), spans)
        earliest = deadline + float(offsets["earliest_offset_sec"])
        latest = deadline + float(offsets["latest_offset_sec"])
        search_start = deadline - float(timing_spec["premature_lookback_sec"])
        search_end = latest + float(timing_spec["late_extension_sec"])
        candidate = first_candidate(turns, search_start, search_end, contract)
        onset = float(candidate["start_sec"]) if candidate else None
        timing = classify_timing(onset, earliest, latest)
        row = dict(gt)
        row.update({
            "session_window_sec": [round(earliest, 6), round(deadline, 6), round(latest, 6)],
            "candidate_search_sec": [round(search_start, 6), round(search_end, 6)],
            "window_anchor": anchor,
            "timing": timing,
            "onset_minus_deadline_sec": round(onset - deadline, 6) if onset is not None else None,
            "candidate": ({
                "utterance_id": f"{gt['debate_id']}:utt:{candidate['turn']}",
                "turn": candidate["turn"],
                "start_sec": candidate["start_sec"],
                "end_sec": candidate["end_sec"],
                "text": candidate.get("text"),
            } if candidate else None),
            "content_score": "UNKNOWN",
            "joint_score": "UNKNOWN",
        })
        rows.append(row)
        if code == "A3-1" and candidate is not None:
            expected_candidate = (anchor_decision or {}).get("candidate_utterance_id")
            actual_candidate = f"{gt['debate_id']}:utt:{candidate['turn']}"
            if expected_candidate and expected_candidate != actual_candidate:
                raise ContractError(
                    f"{gt['debate_id']}: anchor review candidate changed: "
                    f"{expected_candidate} != {actual_candidate}"
                )
            model_xf_end = float(candidate["end_sec"])
    return rows


def phase_boundary_after(run: dict[str, Any], phase: int | None) -> float:
    if phase is None:
        return math.inf
    starts = [
        float(turn["session_start_sec"])
        for turn in run["input_turns"]
        if turn.get("phase") is not None and int(turn["phase"]) > int(phase)
    ]
    return min(starts) if starts else math.inf


def transcript_context(run: dict[str, Any], onset: float) -> list[str]:
    context: list[str] = []
    for turn in run["input_turns"]:
        if float(turn["session_end_sec"]) >= onset - 20.0 and float(turn["session_start_sec"]) <= onset + 5.0:
            context.append(
                f"[{float(turn['session_start_sec']):.2f}s] {turn.get('name') or turn['speaker']} "
                f"({turn['speaker']}): {turn.get('text') or ''}"
            )
    return context


def run_mechanical(
    workspace: Path,
    report_dir: Path,
    plan: dict[str, Any],
    run_plan: dict[str, Any],
    gap_doc: dict[str, Any],
) -> dict[str, Any]:
    output_dir = resolve(workspace, run_plan["output_dir"])
    generation = read_json(output_dir / "generation.json")
    sends = read_jsonl(output_dir / "input_sends.jsonl")
    frame_ms = float(generation["frame_ms"])
    audio_format = generation["audio_format"]
    sample_rate = audio_format.get("sample_rate", audio_format.get("rate"))
    if sample_rate is None:
        raise ContractError(f"{run_plan['debate_id']}: audio_format has no sample rate")
    frame_samples = round(int(sample_rate) * frame_ms / 1000.0)
    max_send_samples = max((int(row.get("samples", 0)) for row in sends), default=0)
    gate_audits = generation.get("gate_release_audits") or []
    server_bad = {
        key: value for key, value in (generation.get("server_event_counts") or {}).items()
        if ("error" in key.lower() or "interrupt" in key.lower()) and value
    }
    gap_bounds = {
        row["gap_id"]: (int(row["start_sample"]), int(row["end_sample"]))
        for row in gap_doc["gaps"]
    }
    invalid_skips: list[dict[str, Any]] = []
    for skip in generation.get("runtime_silence_skips") or []:
        bounds = gap_bounds.get(skip["gap_id"])
        if not bounds or not (
            bounds[0] <= int(skip["source_start_sample"])
            <= int(skip["source_end_sample"]) <= bounds[1]
        ):
            invalid_skips.append(skip)
    tail_sec_observed = int(generation.get("tail_silence_frames", 0)) * frame_ms / 1000.0
    checks = {
        "status_complete": generation.get("status") == "COMPLETE",
        "transmission_integrity": generation.get("transmission_integrity_pass") is True,
        "frame_at_most_80ms": frame_ms <= 80.0 + EPS,
        "send_samples_within_frame": max_send_samples <= frame_samples,
        "gate_audits_pass": bool(gate_audits) and all(
            row.get("status") == "PASS"
            and float(row["observed_quiet_sec"]) + EPS >= float(row["required_quiet_sec"])
            for row in gate_audits
        ),
        "zero_fill_count_matches": sum(1 for row in sends if row.get("kind") == "gate_zero_fill")
        == int(generation.get("gate_zero_fill_frames", -1)),
        "tail_at_least_plan": tail_sec_observed + frame_ms / 1000.0 + EPS >= float(plan["tail_sec"]),
        "start_cue_completed": generation.get("start_cue_status") == "AUDIO_RECEIVED_AND_QUEUE_DRAINED",
        "no_server_error_or_interruption": not server_bad,
        "runtime_skips_within_registered_gaps": not invalid_skips,
    }
    return {
        "debate_id": run_plan["debate_id"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "observed": {
            "frame_ms": frame_ms,
            "max_send_samples": max_send_samples,
            "frame_samples": frame_samples,
            "gate_release_count": len(gate_audits),
            "minimum_observed_quiet_sec": min(
                (float(row["observed_quiet_sec"]) for row in gate_audits), default=None
            ),
            "tail_sec_from_logged_frames": tail_sec_observed,
            "server_bad_events": server_bad,
            "invalid_runtime_skips": invalid_skips,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--scaffold", type=Path)
    parser.add_argument("--benchmark-root", required=True, type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--anchor-decisions",
        type=Path,
        help="semantic A3-1 decisions from derive_anchor_decisions.py; without this, A4xf/A3-2 remain ANCHOR_PENDING",
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    workspace = args.workspace_root.resolve()
    report_dir = args.report_dir.resolve()
    benchmark_root = args.benchmark_root.resolve()
    plan_path = (args.plan or (report_dir / "plan_renewal5.json")).resolve()
    scaffold_path = (args.scaffold or (report_dir / "review_scaffold.json")).resolve()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output directory: {out}")
    out.mkdir(parents=True, exist_ok=True)

    contract = read_json(args.contract.resolve())
    plan = read_json(plan_path)
    scaffold_doc = read_json(scaffold_path)
    anchor_doc = read_json(args.anchor_decisions.resolve()) if args.anchor_decisions else {"debates": {}}
    anchor_decisions = anchor_doc.get("debates") or {}
    anchor_review_stage = args.anchor_decisions is None
    run_scaffolds = {row["debate_id"]: row for row in scaffold_doc["runs"]}
    debates, probes_by_debate = load_benchmark(benchmark_root)

    all_gt: list[dict[str, Any]] = []
    all_timing: list[dict[str, Any]] = []
    all_barge: list[dict[str, Any]] = []
    all_review_items: list[dict[str, Any]] = []
    review_key: list[dict[str, Any]] = []
    mechanical: list[dict[str, Any]] = []
    case_contracts: list[dict[str, Any]] = []
    input_hashes: list[dict[str, str]] = []

    for run_plan in plan["runs"]:
        debate_id = run_plan["debate_id"]
        if debate_id not in run_scaffolds or debate_id not in debates:
            raise ContractError(f"{debate_id}: missing scaffold or benchmark debate")
        run = run_scaffolds[debate_id]
        gt_rows, provenance, validation = build_gt(
            workspace, benchmark_root, run_plan, debates[debate_id],
            probes_by_debate[debate_id], contract,
        )
        timing_rows = score_timing(
            gt_rows, run, debates[debate_id], contract, anchor_decisions.get(debate_id)
        )
        all_gt.extend(gt_rows)
        all_timing.extend(timing_rows)
        case_contracts.append({
            "debate_id": debate_id,
            "primary_n": len(gt_rows),
            "registered_gap_n": validation["registered_gap_count"],
            "validation": validation,
            "provenance": provenance,
        })
        input_hashes.append({"debate_id": debate_id, **provenance})

        gap_doc = read_json(resolve(workspace, run_plan["conditional_gap_file"]))
        mechanical.append(run_mechanical(workspace, report_dir, plan, run_plan, gap_doc))

        input_wav = report_dir / run["files"]["input"]
        speech_intervals, vad_meta = participant_vad(
            input_wav, run["input_turns"], contract["participant_vad"]
        )
        matched: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in timing_rows:
            if row["candidate"]:
                matched[int(row["candidate"]["turn"])].append(row)

        first_input = min(float(row["session_start_sec"]) for row in run["input_turns"])
        last_input = max(float(row["session_end_sec"]) for row in run["input_turns"])
        prompt_path = report_dir / run["files"]["prompt"]
        system_prompt = prompt_path.read_text(encoding="utf-8")
        run_barge_rows: list[dict[str, Any]] = []
        for turn in sorted(run["model_turns"], key=lambda row: float(row["start_sec"])):
            turn_id = int(turn["turn"])
            utterance_id = f"{debate_id}:utt:{turn_id}"
            onset = float(turn["start_sec"])
            backchannel = is_backchannel(turn, contract)
            over_speech = point_in_intervals(onset, speech_intervals)
            links = matched.get(turn_id, [])
            kind = (
                "opening_announcement" if onset < first_input
                else "closing" if onset > last_input
                else "backchannel" if backchannel
                else "matched" if links
                else "non_trigger"
            )
            stale_candidates: list[dict[str, Any]] = []
            if over_speech and not backchannel and not links:
                eligible: list[dict[str, Any]] = []
                for missed in timing_rows:
                    if missed["timing"] != "MISSED":
                        continue
                    if missed["candidate_search_sec"] is None:
                        continue
                    late_end = float(missed["candidate_search_sec"][1])
                    next_same = min(
                        (float(other["session_window_sec"][1]) for other in timing_rows
                         if other["code"] == missed["code"]
                         and float(other["session_window_sec"][1]) > float(missed["session_window_sec"][1]) + EPS),
                        default=math.inf,
                    )
                    boundary = phase_boundary_after(run, missed.get("phase"))
                    if late_end < onset <= min(next_same, boundary) + EPS:
                        eligible.append(missed)
                if eligible:
                    recent = max(eligible, key=lambda row: float(row["session_window_sec"][1]))
                    stale_candidates.append({
                        "gt_id": recent["gt_id"],
                        "probe_id": recent["probe_id"],
                        "seconds_after_latest_plus_3": round(onset - float(recent["candidate_search_sec"][1]), 6),
                    })

            barge_row = {
                "utterance_id": utterance_id,
                "debate_id": debate_id,
                "turn": turn_id,
                "start_sec": onset,
                "end_sec": float(turn["end_sec"]),
                "text": turn.get("text"),
                "backchannel": backchannel,
                "audible_participant_at_onset": over_speech,
                "barge_in": over_speech and not backchannel,
                "matched_gt_ids": [row["gt_id"] for row in links],
                "matched_timing": [row["timing"] for row in links],
                "stale_review_candidates": stale_candidates,
                "kind": kind,
            }
            run_barge_rows.append(barge_row)

            for link in links:
                if anchor_review_stage and link["code"] != "A3-1":
                    continue
                review_id = f"content:{link['gt_id']}"
                all_review_items.append({
                    "review_id": review_id,
                    "task": "content",
                    "system": contract["content"]["judge_system"],
                    "criteria": link["criteria"],
                    "trigger": {"text": link["trigger_text"]},
                    "names": {key: value["name"] for key, value in debates[debate_id]["speakers"].items()},
                    "utterance": turn.get("text"),
                    "actions": contract["content"]["actions"],
                })
                review_key.append({
                    "review_id": review_id, "task": "content", "gt_id": link["gt_id"],
                    "utterance_id": utterance_id, "code": link["code"],
                })

            if kind == "non_trigger" and not anchor_review_stage:
                review_id = f"nontrigger:{utterance_id}"
                all_review_items.append({
                    "review_id": review_id,
                    "task": "non_trigger",
                    "system_prompt": system_prompt,
                    "context": transcript_context(run, onset),
                    "utterance": turn.get("text"),
                    "nearest_primary_gt_distance_sec": min(
                        (abs(onset - float(row["session_window_sec"][1])) for row in timing_rows),
                        default=None,
                    ),
                    "allowed_verdicts": contract["outside_window_verdicts"],
                })
                review_key.append({
                    "review_id": review_id, "task": "non_trigger", "utterance_id": utterance_id,
                })

            for stale in (stale_candidates if not anchor_review_stage else []):
                missed = next(row for row in timing_rows if row["gt_id"] == stale["gt_id"])
                review_id = f"stale:{utterance_id}:{missed['gt_id']}"
                all_review_items.append({
                    "review_id": review_id,
                    "task": "stale_content",
                    "system": contract["content"]["judge_system"],
                    "criteria": missed["criteria"],
                    "trigger": {"text": missed["trigger_text"]},
                    "names": {key: value["name"] for key, value in debates[debate_id]["speakers"].items()},
                    "utterance": turn.get("text"),
                    "actions": contract["content"]["actions"],
                })
                review_key.append({
                    "review_id": review_id, "task": "stale_content",
                    "gt_id": missed["gt_id"], "utterance_id": utterance_id,
                    "code": missed["code"],
                })

        all_barge.append({
            "debate_id": debate_id,
            "vad": vad_meta,
            "participant_speech_intervals": speech_intervals,
            "utterances": run_barge_rows,
        })

    selected = [row["debate_id"] for row in plan["runs"]]
    if plan.get("selected_debates") and selected != plan["selected_debates"]:
        raise ContractError("plan selected_debates does not match runs order")
    timing_counts = Counter(row["timing"] for row in all_timing)
    denominator = {
        "schema_version": contract["schema_version"],
        "authority": contract["authority"],
        "primary_unit": contract["primary_unit"],
        "status": "PASS",
        "selected_debates": selected,
        "primary_n_by_case": {row["debate_id"]: row["primary_n"] for row in case_contracts},
        "primary_n": len(all_gt),
        "registered_gap_n": sum(row["registered_gap_n"] for row in case_contracts),
        "cases": case_contracts,
        "gt_rows": all_gt,
    }
    timing_output = {
        "status": (
            "ANCHOR_REVIEW_PENDING"
            if timing_counts.get("ANCHOR_PENDING", 0)
            else "DETERMINISTIC_COMPLETE_SEMANTIC_PENDING"
        ),
        "primary_n": len(all_timing),
        "aggregate": {
            key: timing_counts.get(key, 0)
            for key in ("ON_TIME", "LATE", "PREMATURE", "MISSED", "ANCHOR_PENDING")
        },
        "rows": all_timing,
    }
    nonback = [row for run in all_barge for row in run["utterances"] if not row["backchannel"]]
    barge = [row for row in nonback if row["barge_in"]]
    back_over = [row for run in all_barge for row in run["utterances"] if row["backchannel"] and row["audible_participant_at_onset"]]
    barge_output = {
        "status": "DETERMINISTIC_CANDIDATES_SEMANTIC_PENDING",
        "definition": "non-backchannel model utterance onset inside operational participant PCM VAD",
        "aggregate": {
            "nonbackchannel_utterances": len(nonback),
            "barge_ins": len(barge),
            "barge_in_rate": len(barge) / len(nonback) if nonback else None,
            "backchannels_over_speech": len(back_over),
            "stale_review_candidates": sum(len(row["stale_review_candidates"]) for row in barge),
        },
        "runs": all_barge,
    }
    mechanical_output = {
        "status": "PASS" if all(row["status"] == "PASS" for row in mechanical) else "FAIL",
        "runs": mechanical,
    }
    review_packet = {
        "schema_version": contract["schema_version"],
        "stage": "anchor" if anchor_review_stage else "full",
        "blinding": "Do not provide review_key.json, taxonomy codes, reference answers, or timing classes to the reviewer.",
        "human_gold": False,
        "output_contract": {
            "top_level": {
                "reviewer": {
                    "model": "string",
                    "fresh_session": True,
                    "blinded": True,
                },
                "items": "exactly one result object per input review_id",
            },
            "content_or_stale_item": {
                "review_id": "copy exactly",
                "met": "boolean array, one value per criterion in order",
                "why": "string array, one reason per criterion in order",
                "action": "copy exactly one value from the supplied actions list",
            },
            "non_trigger_item": {
                "review_id": "copy exactly",
                "verdict": "copy exactly one supplied allowed verdict",
                "violated_duty": "string when verdict is violation, otherwise null",
                "why": "one-sentence reason",
            },
            "forbidden": "Do not rename items to reviews or expand met into criterion objects.",
        },
        "items": all_review_items,
    }
    manifest = {
        "schema_version": contract["schema_version"],
        "contract": str(args.contract.resolve()),
        "contract_sha256": file_sha256(args.contract.resolve()),
        "plan": str(plan_path),
        "plan_sha256": file_sha256(plan_path),
        "scaffold": str(scaffold_path),
        "scaffold_sha256": file_sha256(scaffold_path),
        "anchor_decisions": str(args.anchor_decisions.resolve()) if args.anchor_decisions else None,
        "anchor_decisions_sha256": file_sha256(args.anchor_decisions.resolve()) if args.anchor_decisions else None,
        "benchmark_root": str(benchmark_root),
        "inputs": input_hashes,
    }

    write_json(out / "denominator_contract.json", denominator)
    write_json(out / "timing.json", timing_output)
    write_json(out / "barge_in_candidates.json", barge_output)
    write_json(out / "mechanical.json", mechanical_output)
    write_json(out / "review_packet.json", review_packet)
    write_json(out / "review_key.json", {"items": review_key})
    write_json(out / "manifest.json", manifest)
    print(json.dumps({
        "status": "PASS",
        "primary_n": len(all_gt),
        "primary_n_by_case": denominator["primary_n_by_case"],
        "timing": timing_output["aggregate"],
        "barge_in": barge_output["aggregate"],
        "mechanical": mechanical_output["status"],
        "out": str(out),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
