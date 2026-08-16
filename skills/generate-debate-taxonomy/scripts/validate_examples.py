#!/usr/bin/env python3
"""Validate all positive fixtures and targeted negative regression mutations."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from validate_sample import DEFAULT_CONTRACT, load_json, validate_sample


SKILL_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = SKILL_ROOT / "examples"


def main() -> int:
    contract = load_json(DEFAULT_CONTRACT)
    results: list[dict[str, object]] = []
    failed = False
    fixtures: dict[str, dict] = {}
    for path in sorted(EXAMPLES.glob("*.json")):
        sample = load_json(path)
        fixtures[path.stem] = sample
        report = validate_sample(sample, contract)
        results.append(
            {
                "case": path.name,
                "expected": "PASS",
                "actual": "PASS" if report["automatic_valid"] else "FAIL",
                "errors": report["errors"],
                "warnings": report["warnings"],
            }
        )
        if not report["automatic_valid"]:
            failed = True

    negative_cases: list[tuple[str, dict, str]] = []

    invalid_a1 = copy.deepcopy(fixtures["a1"])
    a1_mod_id = invalid_a1["events"][0]["moderator_turn_id"]
    for turn in invalid_a1["turns"]:
        if turn["turn_id"] == a1_mod_id:
            turn["start_sec"] = 7.0
            turn["end_sec"] = 7.8
    negative_cases.append(("negative_a1_before_deadline", invalid_a1, "A1: MOD cannot act before deadline"))

    invalid_a21 = copy.deepcopy(fixtures["a2-1"])
    invalid_a21["events"][0]["next_speaker"] = "PRO"
    negative_cases.append(("negative_a2_1_same_speaker", invalid_a21, "A2-1 requires the opposite next_speaker"))

    invalid_a22 = copy.deepcopy(fixtures["a2-2"])
    a22_mod_id = invalid_a22["events"][0]["moderator_turn_id"]
    for turn in invalid_a22["turns"]:
        if turn["turn_id"] == a22_mod_id:
            turn["start_sec"] = 6.5
            turn["end_sec"] = 8.0
    negative_cases.append(("negative_a2_2_overlap", invalid_a22, "A2-2 must occur after a non-overlapping"))

    invalid_a31 = copy.deepcopy(fixtures["a3-1"])
    for turn in invalid_a31["turns"]:
        if turn["turn_id"] == "t002":
            turn["speaker"] = "MOD"
    negative_cases.append(("negative_a3_1_missing_con_opening", invalid_a31, "A3-1 requires both PRO and CON openings"))

    invalid_a32 = copy.deepcopy(fixtures["a3-2"])
    for turn in invalid_a32["turns"]:
        if turn["turn_id"] == "t004":
            turn["speaker"] = "CON"
        elif turn["turn_id"] == "t005":
            turn["speaker"] = "PRO"
    negative_cases.append(("negative_a3_2_con_first", invalid_a32, "A3-2 requires PRO closing before CON"))

    invalid_a4 = copy.deepcopy(fixtures["a4"])
    mod_id = invalid_a4["events"][0]["moderator_turn_id"]
    for turn in invalid_a4["turns"]:
        if turn["turn_id"] == mod_id:
            turn["start_sec"] = 20.0
            turn["end_sec"] = 20.8
    negative_cases.append(("negative_a4_no_overlap", invalid_a4, "A4 MOD notice must overlap"))

    invalid_same_speaker_overlap = copy.deepcopy(fixtures["a4"])
    invalid_same_speaker_overlap["turns"].append(
        {
            "turn_id": "t004",
            "phase": 1,
            "speaker": "PRO",
            "text": "I will continue the same sentence here.",
            "start_sec": 5.9,
            "end_sec": 8.0,
            "taxonomy": [],
        }
    )
    invalid_same_speaker_overlap["turns"].sort(key=lambda turn: turn["start_sec"])
    invalid_same_speaker_overlap["translations_ko"]["t004"] = "같은 문장을 여기서 계속 말하겠습니다."
    negative_cases.append(
        (
            "negative_global_same_speaker_overlap",
            invalid_same_speaker_overlap,
            "same speaker turns must not overlap",
        )
    )

    invalid_fast_speech = copy.deepcopy(fixtures["a4"])
    fast_id = invalid_fast_speech["events"][0]["moderator_turn_id"]
    for turn in invalid_fast_speech["turns"]:
        if turn["turn_id"] == fast_id:
            turn["end_sec"] = turn["start_sec"] + 0.2
    negative_cases.append(
        (
            "negative_global_implausible_speech_rate",
            invalid_fast_speech,
            "WPM exceeds 260 WPM ceiling",
        )
    )

    invalid_a5 = copy.deepcopy(fixtures["a5"])
    interrupt_id = invalid_a5["events"][0]["trigger_turn_ids"][-1]
    for turn in invalid_a5["turns"]:
        if turn["turn_id"] == interrupt_id:
            turn["text"] = "But that misses the entire point because deliberate practice changes how people reason in every later situation they encounter."
    negative_cases.append(("negative_a5_long_interrupt", invalid_a5, "A5 interrupt exceeds"))

    invalid_b1 = copy.deepcopy(fixtures["b1"])
    invalid_b1["events"][0]["off_topic_quote"] = "a claim that never appears"
    negative_cases.append(("negative_b1_ungrounded_quote", invalid_b1, "B1 off_topic_quote is not grounded"))

    invalid_b2 = copy.deepcopy(fixtures["b2"])
    claim_b_id = invalid_b2["events"][0]["trigger_turn_ids"][-1]
    for turn in invalid_b2["turns"]:
        if turn["turn_id"] == claim_b_id:
            turn["speaker"] = "PRO"
    negative_cases.append(("negative_b2_mixed_speaker", invalid_b2, "B2 claims must be spoken by the same"))

    for name, sample, expected_fragment in negative_cases:
        report = validate_sample(sample, contract)
        caught = not report["automatic_valid"] and any(expected_fragment in error for error in report["errors"])
        results.append(
            {
                "case": name,
                "expected": "FAIL",
                "actual": "FAIL" if not report["automatic_valid"] else "PASS",
                "regression_caught": caught,
                "errors": report["errors"],
            }
        )
        if not caught:
            failed = True

    summary = {
        "valid": not failed,
        "positive_fixture_count": len(fixtures),
        "negative_regression_count": len(negative_cases),
        "results": results,
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
