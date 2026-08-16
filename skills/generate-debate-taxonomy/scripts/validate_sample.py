#!/usr/bin/env python3
"""Deterministically validate debate-taxonomy event windows and full debates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = SKILL_ROOT / "references" / "contract.json"
WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:\.\d+)?")


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return float(left["start_sec"]) < float(right["end_sec"]) and float(right["start_sec"]) < float(left["end_sec"])


def find_next_debater(turns: list[dict[str, Any]], after_sec: float) -> dict[str, Any] | None:
    for turn in turns:
        if turn.get("speaker") in {"PRO", "CON"} and float(turn.get("start_sec", -1)) >= after_sec - 0.05:
            return turn
    return None


def require_substring(
    errors: list[str], value: Any, text: str, label: str, *, case_sensitive: bool = False
) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")
        return
    haystack = text if case_sensitive else text.lower()
    needle = value if case_sensitive else value.lower()
    if needle not in haystack:
        errors.append(f"{label} is not grounded in its linked turn text")


def validate_sample(data: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    roles = tuple(contract["roles"])
    allowed_taxonomies = set(contract["taxonomies"])

    if data.get("schema_version") != contract["schema_version"]:
        errors.append("schema_version does not match contract")
    mode = data.get("mode")
    if mode not in {"event-window", "full-debate"}:
        errors.append("mode must be event-window or full-debate")

    participants = data.get("participants")
    if not isinstance(participants, dict) or set(participants) != set(roles):
        errors.append(f"participants must contain exactly {list(roles)}")
        participants = {}
    else:
        names = []
        for role in roles:
            name = participants[role].get("name") if isinstance(participants[role], dict) else None
            if not isinstance(name, str) or not name.strip():
                errors.append(f"participant {role} requires a name")
            else:
                names.append(name.lower())
        if len(names) != len(set(names)):
            errors.append("participant names must be unique")

    targets = data.get("target_taxonomies")
    if not isinstance(targets, list) or not targets:
        errors.append("target_taxonomies must be a non-empty list")
        targets = []
    elif len(targets) != len(set(targets)):
        errors.append("target_taxonomies must not contain duplicates")
    for taxonomy in targets:
        if taxonomy not in allowed_taxonomies:
            errors.append(f"unknown target taxonomy: {taxonomy}")

    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        errors.append("turns must be a non-empty list")
        turns = []

    turn_by_id: dict[str, dict[str, Any]] = {}
    taxonomy_turns: dict[str, list[str]] = {}
    previous_start = -1.0
    phases: list[int] = []
    turn_wpm: dict[str, float] = {}
    for index, turn in enumerate(turns):
        turn_id = turn.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            errors.append(f"turn {index} requires turn_id")
            continue
        if turn_id in turn_by_id:
            errors.append(f"duplicate turn_id: {turn_id}")
        turn_by_id[turn_id] = turn

        speaker = turn.get("speaker")
        if speaker not in roles:
            errors.append(f"{turn_id}: unknown speaker {speaker!r}")
        text = turn.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{turn_id}: text must be non-empty")
            text = ""
        if "[" in text or "]" in text:
            errors.append(f"{turn_id}: unresolved square-bracket tag")

        start = turn.get("start_sec")
        end = turn.get("end_sec")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            errors.append(f"{turn_id}: start_sec/end_sec must be numeric")
            continue
        if start < 0 or end <= start:
            errors.append(f"{turn_id}: invalid time interval {start}..{end}")
        elif text:
            wpm = word_count(text) / (float(end) - float(start)) * 60.0
            turn_wpm[turn_id] = wpm
            max_turn_wpm = float(contract.get("timing", {}).get("max_turn_wpm", 260))
            if wpm > max_turn_wpm + 1e-9:
                errors.append(
                    f"{turn_id}: speech rate {wpm:.1f} WPM exceeds "
                    f"{max_turn_wpm:.0f} WPM ceiling"
                )
        if start < previous_start:
            errors.append("turns must be sorted by start_sec")
        previous_start = float(start)

        phase = turn.get("phase")
        if phase not in {1, 2, 3}:
            errors.append(f"{turn_id}: phase must be 1, 2, or 3")
        else:
            phases.append(phase)

        turn_taxonomies = turn.get("taxonomy", [])
        if not isinstance(turn_taxonomies, list):
            errors.append(f"{turn_id}: taxonomy must be a list")
            turn_taxonomies = []
        if len(turn_taxonomies) > 1:
            errors.append(f"{turn_id}: one MOD turn cannot realize multiple taxonomies")
        for taxonomy in turn_taxonomies:
            if taxonomy not in allowed_taxonomies:
                errors.append(f"{turn_id}: unknown taxonomy {taxonomy}")
            if speaker != "MOD":
                errors.append(f"{turn_id}: taxonomy must be attached to a MOD turn")
            taxonomy_turns.setdefault(taxonomy, []).append(turn_id)

    if phases != sorted(phases):
        errors.append("phase sequence must be monotonic")

    for left_index, left in enumerate(turns):
        if not isinstance(left.get("start_sec"), (int, float)) or not isinstance(left.get("end_sec"), (int, float)):
            continue
        for right in turns[left_index + 1 :]:
            if not isinstance(right.get("start_sec"), (int, float)) or not isinstance(right.get("end_sec"), (int, float)):
                continue
            if left.get("speaker") == right.get("speaker") and overlaps(left, right):
                errors.append(
                    "same speaker turns must not overlap: "
                    f"{left.get('turn_id')} and {right.get('turn_id')}"
                )

    translations = data.get("translations_ko")
    if not isinstance(translations, dict):
        errors.append("translations_ko must be an object")
        translations = {}
    turn_id_set = set(turn_by_id)
    missing_translations = sorted(turn_id_set - set(translations))
    extra_translations = sorted(set(translations) - turn_id_set)
    if missing_translations:
        errors.append(f"missing Korean translations: {missing_translations}")
    if extra_translations:
        errors.append(f"translations reference unknown turns: {extra_translations}")
    for turn_id, translation in translations.items():
        if not isinstance(translation, str) or not translation.strip():
            errors.append(f"{turn_id}: Korean translation must be non-empty")

    events = data.get("events")
    if not isinstance(events, list):
        errors.append("events must be a list")
        events = []
    event_by_taxonomy: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        taxonomy = event.get("taxonomy")
        event_by_taxonomy.setdefault(taxonomy, []).append(event)
        if taxonomy not in allowed_taxonomies:
            errors.append(f"event has unknown taxonomy: {taxonomy}")
            continue
        mod_id = event.get("moderator_turn_id")
        trigger_ids = event.get("trigger_turn_ids")
        if mod_id not in turn_by_id:
            errors.append(f"{taxonomy}: moderator_turn_id is missing")
            continue
        mod_turn = turn_by_id[mod_id]
        if mod_turn.get("speaker") != "MOD":
            errors.append(f"{taxonomy}: moderator_turn_id must link to MOD")
        if mod_turn.get("taxonomy") != [taxonomy]:
            errors.append(f"{taxonomy}: MOD turn taxonomy linkage mismatch")
        if not isinstance(trigger_ids, list) or not trigger_ids:
            errors.append(f"{taxonomy}: trigger_turn_ids must be non-empty")
            trigger_ids = []
        if any(trigger_id not in turn_by_id for trigger_id in trigger_ids):
            errors.append(f"{taxonomy}: trigger_turn_ids contain unknown turn")
            continue
        trigger_turns = [turn_by_id[trigger_id] for trigger_id in trigger_ids]
        if any(float(trigger["start_sec"]) > float(mod_turn["start_sec"]) for trigger in trigger_turns):
            errors.append(f"{taxonomy}: triggers must start before MOD action")

        rule = contract["event_rules"][taxonomy]
        if taxonomy in {"A1", "A2-1"}:
            floor = trigger_turns[-1]
            floor_holder = event.get("floor_holder")
            deadline = event.get("deadline_sec")
            if floor.get("speaker") != floor_holder or floor_holder not in {"PRO", "CON"}:
                errors.append(f"{taxonomy}: floor_holder must match trigger speaker")
            if not isinstance(deadline, (int, float)):
                errors.append(f"{taxonomy}: deadline_sec is required")
            else:
                if not float(floor["start_sec"]) < deadline < float(floor["end_sec"]):
                    errors.append(f"{taxonomy}: deadline must fall inside over-time floor turn")
                if float(mod_turn["start_sec"]) < deadline:
                    errors.append(f"{taxonomy}: MOD cannot act before deadline")
            if not overlaps(floor, mod_turn):
                errors.append(f"{taxonomy}: MOD must barge into over-time floor turn")
            if taxonomy == "A1":
                if event.get("next_speaker") not in {None, ""}:
                    errors.append("A1 must not call a next speaker")
            else:
                next_speaker = event.get("next_speaker")
                if next_speaker not in {"PRO", "CON"} or next_speaker == floor_holder:
                    errors.append("A2-1 requires the opposite next_speaker")
                next_turn = find_next_debater(turns, float(mod_turn["end_sec"]))
                if next_turn is None or next_turn.get("speaker") != next_speaker:
                    errors.append("A2-1 next substantive turn must belong to next_speaker")

        elif taxonomy == "A2-2":
            floor = trigger_turns[-1]
            floor_holder = event.get("floor_holder")
            next_speaker = event.get("next_speaker")
            if floor.get("speaker") != floor_holder or floor_holder not in {"PRO", "CON"}:
                errors.append("A2-2 floor_holder must match trigger speaker")
            if overlaps(floor, mod_turn) or float(mod_turn["start_sec"]) < float(floor["end_sec"]):
                errors.append("A2-2 must occur after a non-overlapping completed turn")
            if next_speaker not in {"PRO", "CON"} or next_speaker == floor_holder:
                errors.append("A2-2 requires the opposite next_speaker")
            next_turn = find_next_debater(turns, float(mod_turn["end_sec"]))
            if next_turn is None or next_turn.get("speaker") != next_speaker:
                errors.append("A2-2 next substantive turn must belong to next_speaker")

        elif taxonomy == "A3-1":
            if mod_turn.get("phase") != 2:
                errors.append("A3-1 MOD turn must be in Phase 2")
            phase2_turns = [turn for turn in turns if turn.get("phase") == 2]
            if not phase2_turns or phase2_turns[0].get("turn_id") != mod_id:
                errors.append("A3-1 must be the first Phase 2 turn")
            opening_roles = {
                turn.get("speaker")
                for turn in turns
                if turn.get("phase") == 1 and turn.get("speaker") in {"PRO", "CON"}
            }
            if opening_roles != {"PRO", "CON"}:
                errors.append("A3-1 requires both PRO and CON openings")
            next_turn = find_next_debater(turns, float(mod_turn["end_sec"]))
            if next_turn is None or next_turn.get("phase") != 2:
                errors.append("A3-1 requires direct debate after MOD transition")

        elif taxonomy == "A3-2":
            if mod_turn.get("phase") != 3:
                errors.append("A3-2 MOD turn must be in Phase 3")
            phase3_turns = [turn for turn in turns if turn.get("phase") == 3]
            if not phase3_turns or phase3_turns[0].get("turn_id") != mod_id:
                errors.append("A3-2 must be the first Phase 3 turn")
            closing_roles = [
                turn.get("speaker")
                for turn in phase3_turns
                if turn.get("speaker") in {"PRO", "CON"}
            ]
            if not closing_roles or closing_roles[0] != "PRO" or "CON" not in closing_roles[1:]:
                errors.append("A3-2 requires PRO closing before CON closing")

        elif taxonomy == "A4":
            floor = trigger_turns[-1]
            floor_holder = event.get("floor_holder")
            if floor.get("speaker") != floor_holder or floor_holder not in {"PRO", "CON"}:
                errors.append("A4 floor_holder must match trigger speaker")
            if not overlaps(floor, mod_turn):
                errors.append("A4 MOD notice must overlap the current floor holder")
            remaining = float(floor["end_sec"]) - float(mod_turn["start_sec"])
            if not rule["remaining_sec_min"] <= remaining <= rule["remaining_sec_max"]:
                errors.append(f"A4 remaining time {remaining:.2f}s is outside 8..12s")
            declared_remaining = event.get("remaining_sec")
            if not isinstance(declared_remaining, (int, float)) or abs(declared_remaining - remaining) > 0.51:
                errors.append("A4 remaining_sec must match the timeline")
            if word_count(mod_turn.get("text", "")) > rule["max_mod_words"]:
                errors.append("A4 MOD notice exceeds 10 words")
            if float(floor["end_sec"]) <= float(mod_turn["end_sec"]):
                errors.append("A4 floor holder must continue after the time notice")

        elif taxonomy == "A5":
            if len(trigger_turns) < 2:
                errors.append("A5 requires floor and interrupt trigger turns")
            else:
                floor, interrupt = trigger_turns[-2], trigger_turns[-1]
                floor_holder = event.get("floor_holder")
                interrupter = event.get("interrupter")
                if floor.get("speaker") != floor_holder or interrupt.get("speaker") != interrupter:
                    errors.append("A5 event roles must match trigger speakers")
                if {floor_holder, interrupter} != {"PRO", "CON"}:
                    errors.append("A5 floor holder and interrupter must be opposite debaters")
                if not overlaps(floor, interrupt):
                    errors.append("A5 interrupter must overlap the floor holder")
                if word_count(interrupt.get("text", "")) > rule["max_interrupt_words"]:
                    errors.append("A5 interrupt exceeds 12 words")
                delay = float(mod_turn["start_sec"]) - float(interrupt["end_sec"])
                if delay > rule["max_mod_delay_sec"]:
                    errors.append("A5 MOD intervention is too late")
                if float(mod_turn["start_sec"]) < float(interrupt["start_sec"]):
                    errors.append("A5 MOD cannot act before the interruption starts")
                resume_id = event.get("resume_turn_id")
                resume = turn_by_id.get(resume_id)
                if resume is None or resume.get("speaker") != floor_holder:
                    errors.append("A5 requires a resume turn by the original floor holder")
                elif float(resume["start_sec"]) < float(mod_turn["end_sec"]):
                    errors.append("A5 resume turn must follow MOD intervention")

        elif taxonomy == "B1":
            trigger = trigger_turns[-1]
            if trigger.get("speaker") not in {"PRO", "CON"}:
                errors.append("B1 trigger must be a debater turn")
            if overlaps(trigger, mod_turn) or float(mod_turn["start_sec"]) < float(trigger["end_sec"]):
                errors.append("B1 redirect must follow the drift turn")
            require_substring(errors, event.get("off_topic_quote"), trigger.get("text", ""), "B1 off_topic_quote")
            require_substring(errors, event.get("redirect_quote"), mod_turn.get("text", ""), "B1 redirect_quote")
            warnings.append("B1 requires transcript-only semantic review for genuine topic drift")

        elif taxonomy == "B2":
            if len(trigger_turns) < rule["min_claims"]:
                errors.append("B2 requires at least two claim turns")
            else:
                claim_a, claim_b = trigger_turns[-2], trigger_turns[-1]
                speakers = {claim_a.get("speaker"), claim_b.get("speaker")}
                if len(speakers) != 1 or next(iter(speakers)) not in {"PRO", "CON"}:
                    errors.append("B2 claims must be spoken by the same debater")
                if float(claim_a["start_sec"]) >= float(claim_b["start_sec"]):
                    errors.append("B2 CLAIM_A must precede CLAIM_B")
                if float(mod_turn["start_sec"]) < float(claim_b["end_sec"]):
                    errors.append("B2 MOD action must follow both claims")
                require_substring(errors, event.get("claim_a_quote"), claim_a.get("text", ""), "B2 claim_a_quote")
                require_substring(errors, event.get("claim_b_quote"), claim_b.get("text", ""), "B2 claim_b_quote")
                require_substring(errors, event.get("contrast_quote"), mod_turn.get("text", ""), "B2 contrast_quote")
            warnings.append("B2 requires transcript-only semantic review for logical incompatibility")

    for taxonomy in targets:
        if len(event_by_taxonomy.get(taxonomy, [])) != 1:
            errors.append(f"target {taxonomy} must have exactly one event")
        if len(taxonomy_turns.get(taxonomy, [])) != 1:
            errors.append(f"target {taxonomy} must occur on exactly one MOD turn")
    for taxonomy in event_by_taxonomy:
        if taxonomy not in targets:
            errors.append(f"event contains non-target taxonomy: {taxonomy}")
    for taxonomy in taxonomy_turns:
        if taxonomy not in targets:
            errors.append(f"turn contains non-target taxonomy: {taxonomy}")

    if mode == "event-window" and len(targets) != 1:
        errors.append("event-window mode must target exactly one taxonomy")
    if mode == "full-debate":
        errors.append(
            "full-debate must use scripts/validate_full_debate.py with voice-WPM timing"
        )

    duration_sec = 0.0
    if turns and all(isinstance(turn.get("start_sec"), (int, float)) and isinstance(turn.get("end_sec"), (int, float)) for turn in turns):
        duration_sec = max(float(turn["end_sec"]) for turn in turns) - min(float(turn["start_sec"]) for turn in turns)

    return {
        "sample_id": data.get("sample_id"),
        "automatic_valid": not errors,
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "metrics": {
            "mode": mode,
            "duration_sec": round(duration_sec, 3),
            "turn_count": len(turns),
            "target_taxonomies": targets,
            "max_turn_wpm": round(max(turn_wpm.values()), 3) if turn_wpm else 0.0,
            "max_turn_wpm_turn_id": max(turn_wpm, key=turn_wpm.get) if turn_wpm else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    report = validate_sample(load_json(args.sample), load_json(args.contract))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if report["automatic_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
