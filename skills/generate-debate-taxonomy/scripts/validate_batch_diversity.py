#!/usr/bin/env python3
"""Validate event samples individually and check controlled batch diversity."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from validate_sample import DEFAULT_CONTRACT, load_json, validate_sample


VARIATION_FIELDS = (
    "taxonomy",
    "variation_id",
    "seed",
    "domain",
    "motion_family",
    "trigger_subtype",
    "role_pattern",
    "moderator_style",
    "timing_profile",
    "participant_set",
)
TOKEN_RE = re.compile(r"[a-z0-9]+")
FULL_VALIDATOR = Path(__file__).resolve().parent / "validate_full_debate.py"


def normalized(value: str) -> str:
    return " ".join(TOKEN_RE.findall(value.lower()))


def jaccard(left: str, right: str) -> float:
    left_tokens = set(TOKEN_RE.findall(left.lower()))
    right_tokens = set(TOKEN_RE.findall(right.lower()))
    if not left_tokens and not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def moderator_actions(sample: dict[str, Any]) -> list[str]:
    return [
        turn.get("text", "")
        for turn in sample.get("turns", [])
        if turn.get("speaker") == "MOD" and turn.get("taxonomy")
    ]


def trigger_texts(sample: dict[str, Any]) -> list[str]:
    turn_by_id = {turn.get("turn_id"): turn for turn in sample.get("turns", [])}
    texts = []
    for event in sample.get("events", []):
        texts.extend(turn_by_id.get(turn_id, {}).get("text", "") for turn_id in event.get("trigger_turn_ids", []))
    return texts


def variation_alignment_errors(sample: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    variation = sample.get("variation", {})
    targets = sample.get("target_taxonomies", [])
    taxonomy = variation.get("taxonomy")
    is_full_debate = sample.get("duration_profile") in {"short", "long"} and "contract_version" in sample
    if is_full_debate:
        if taxonomy not in targets:
            errors.append(f"variation taxonomy {taxonomy!r} is not present in full-debate targets {targets!r}")
    elif targets != [taxonomy]:
        errors.append(f"variation taxonomy {taxonomy!r} does not match sole target {targets!r}")

    expected_participants = variation.get("participants")
    actual_participants = sample.get("participants", {})
    if not isinstance(expected_participants, dict):
        errors.append("variation participants must be an object")
    else:
        actual_names = {
            role: actual_participants.get(role, {}).get("name")
            for role in ("MOD", "PRO", "CON")
        }
        if actual_names != expected_participants:
            errors.append(
                f"participant names do not match variation card: "
                f"expected={expected_participants}, actual={actual_names}"
            )

    event = next((item for item in sample.get("events", []) if item.get("taxonomy") == taxonomy), {})
    turn_by_id = {turn.get("turn_id"): turn for turn in sample.get("turns", [])}
    triggers = [turn_by_id.get(turn_id, {}) for turn_id in event.get("trigger_turn_ids", [])]
    pattern = variation.get("role_pattern")
    derived_floor = event.get("floor_holder") or (triggers[-1].get("speaker") if triggers else None)
    if pattern in {"PRO_floor", "CON_floor"} and derived_floor != pattern[:3]:
        errors.append(f"{pattern} does not match event floor_holder")
    elif pattern in {"PRO_to_CON", "CON_to_PRO"}:
        floor, next_speaker = pattern.split("_to_")
        if event.get("floor_holder") != floor or event.get("next_speaker") != next_speaker:
            errors.append(f"{pattern} does not match event handoff roles")
    elif pattern in {"PRO_interrupts_CON", "CON_interrupts_PRO"}:
        interrupter, floor = pattern.split("_interrupts_")
        derived_a5_floor = event.get("floor_holder") or (triggers[-2].get("speaker") if len(triggers) >= 2 else None)
        derived_interrupter = event.get("interrupter") or (triggers[-1].get("speaker") if triggers else None)
        if derived_a5_floor != floor or derived_interrupter != interrupter:
            errors.append(f"{pattern} does not match A5 event roles")
    elif pattern in {"PRO_drifts", "CON_drifts"}:
        expected = pattern[:3]
        if not triggers or triggers[-1].get("speaker") != expected:
            errors.append(f"{pattern} does not match B1 trigger speaker")
    elif pattern in {"PRO_claims", "CON_claims"}:
        expected = pattern[:3]
        if len(triggers) < 2 or any(turn.get("speaker") != expected for turn in triggers):
            errors.append(f"{pattern} does not match B2 claim speakers")
    elif pattern in {"PRO_first_direct", "CON_first_direct"}:
        expected = pattern[:3]
        mod_id = event.get("moderator_turn_id")
        mod_turn = turn_by_id.get(mod_id, {})
        candidates = [
            turn
            for turn in sample.get("turns", [])
            if turn.get("speaker") in {"PRO", "CON"}
            and isinstance(turn.get("start_sec"), (int, float))
            and isinstance(mod_turn.get("end_sec"), (int, float))
            and turn["start_sec"] >= mod_turn["end_sec"] - 0.05
        ]
        if not candidates or candidates[0].get("speaker") != expected:
            errors.append(f"{pattern} does not match first direct-debate speaker")

    timing = variation.get("timing_profile", "")
    if taxonomy == "A4" and timing.startswith("remaining-"):
        try:
            expected_remaining = float(timing.removeprefix("remaining-").removesuffix("s"))
        except ValueError:
            errors.append(f"invalid A4 timing profile: {timing}")
        else:
            declared = event.get("remaining_sec")
            if not isinstance(declared, (int, float)) or abs(float(declared) - expected_remaining) > 0.51:
                errors.append(f"A4 event remaining_sec does not match {timing}")
    return errors


def validate_one(path: Path, sample: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    is_full_debate = sample.get("duration_profile") in {"short", "long"} and "contract_version" in sample
    if not is_full_debate:
        return validate_sample(sample, contract)
    result = subprocess.run(
        [sys.executable, str(FULL_VALIDATOR), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "sample_id": sample.get("sample_id"),
            "automatic_valid": False,
            "errors": [f"full-debate validator did not return JSON: {result.stderr.strip()}"],
            "warnings": [],
            "metrics": {},
            "validator_type": "full-debate-voice-wpm",
        }
    return {
        "sample_id": report.get("sample_id"),
        "automatic_valid": bool(report.get("valid")),
        "errors": report.get("errors", []),
        "warnings": report.get("warnings", []),
        "metrics": report.get("metrics", {}),
        "validator_type": "full-debate-voice-wpm",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-csv", default="")
    parser.add_argument("samples", nargs="+", type=Path)
    args = parser.parse_args()
    expected = [item for item in args.expected_csv.split(",") if item]
    contract = load_json(DEFAULT_CONTRACT)
    errors: list[str] = []
    warnings: list[str] = []
    samples: list[dict[str, Any]] = []
    individual = []

    for path in args.samples:
        sample = load_json(path)
        report = validate_one(path, sample, contract)
        samples.append(sample)
        individual.append({"path": str(path), **report})
        if not report["automatic_valid"]:
            errors.append(f"{path}: individual taxonomy validation failed")
        variation = sample.get("variation")
        if not isinstance(variation, dict):
            errors.append(f"{path}: missing variation card")
            continue
        missing = [field for field in VARIATION_FIELDS if not isinstance(variation.get(field), str) or not variation[field].strip()]
        if missing:
            errors.append(f"{path}: variation fields missing or empty: {missing}")
        for alignment_error in variation_alignment_errors(sample):
            errors.append(f"{path}: {alignment_error}")

    primary_taxonomies = [sample.get("variation", {}).get("taxonomy") for sample in samples]
    all_taxonomies = [taxonomy for sample in samples for taxonomy in sample.get("target_taxonomies", [])]
    if expected and Counter(primary_taxonomies) != Counter(expected):
        errors.append(f"taxonomy coverage mismatch: expected={expected}, actual={primary_taxonomies}")

    fields = {
        "sample_id": [str(sample.get("sample_id", "")) for sample in samples],
        "motion": [normalized(str(sample.get("motion", ""))) for sample in samples],
        "variation_id": [str(sample.get("variation", {}).get("variation_id", "")) for sample in samples],
        "domain": [str(sample.get("variation", {}).get("domain", "")) for sample in samples],
        "motion_family": [str(sample.get("variation", {}).get("motion_family", "")) for sample in samples],
        "moderator_style": [str(sample.get("variation", {}).get("moderator_style", "")) for sample in samples],
        "participant_set": [str(sample.get("variation", {}).get("participant_set", "")) for sample in samples],
    }
    for field in ("sample_id", "motion", "variation_id"):
        duplicates = sorted(value for value, count in Counter(fields[field]).items() if value and count > 1)
        if duplicates:
            errors.append(f"duplicate {field}: {duplicates}")

    n_samples = len(samples)
    min_domains = min(n_samples, max(1, math.ceil(n_samples * 2 / 3)))
    unique_domains = len(set(value for value in fields["domain"] if value))
    if unique_domains < min_domains:
        errors.append(f"domain coverage {unique_domains} is below required {min_domains}")
    max_domain_reuse = max(Counter(fields["domain"]).values(), default=0)
    if n_samples >= 6 and max_domain_reuse > 2:
        errors.append(f"one domain is reused {max_domain_reuse} times; maximum is 2")
    unique_styles = len(set(value for value in fields["moderator_style"] if value))
    min_styles = min(n_samples, max(1, math.ceil(n_samples * 2 / 3)))
    if unique_styles < min_styles:
        errors.append(f"moderator style coverage {unique_styles} is below required {min_styles}")

    actions = [(sample.get("sample_id"), text) for sample in samples for text in moderator_actions(sample)]
    duplicate_actions = sorted(
        text for text, count in Counter(normalized(text) for _, text in actions).items() if text and count > 1
    )
    if duplicate_actions:
        errors.append(f"duplicate moderator action text: {duplicate_actions}")
    action_pairs = [
        {"left": left_id, "right": right_id, "similarity": round(jaccard(left, right), 4)}
        for (left_id, left), (right_id, right) in itertools.combinations(actions, 2)
    ]
    high_action_pairs = [pair for pair in action_pairs if pair["similarity"] > 0.8]
    if high_action_pairs:
        errors.append(f"moderator action similarity exceeds 0.8: {high_action_pairs}")

    triggers = [normalized(text) for sample in samples for text in trigger_texts(sample) if text]
    duplicate_triggers = sorted(text for text, count in Counter(triggers).items() if count > 1)
    if duplicate_triggers:
        errors.append(f"duplicate trigger text: {duplicate_triggers}")

    semantic_codes = sorted(set(all_taxonomies) & {"B1", "B2"})
    if semantic_codes:
        warnings.append(f"semantic review remains required for {semantic_codes}")

    metrics = {
        "sample_count": n_samples,
        "taxonomy_count": len(primary_taxonomies),
        "unique_motion_count": len(set(fields["motion"])),
        "unique_domain_count": unique_domains,
        "unique_motion_family_count": len(set(value for value in fields["motion_family"] if value)),
        "unique_moderator_style_count": unique_styles,
        "unique_participant_set_count": len(set(value for value in fields["participant_set"] if value)),
        "max_domain_reuse": max_domain_reuse,
        "max_moderator_action_jaccard": max((pair["similarity"] for pair in action_pairs), default=0.0),
    }
    result = {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "individual": individual,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
