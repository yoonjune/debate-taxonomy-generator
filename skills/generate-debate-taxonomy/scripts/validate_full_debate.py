#!/usr/bin/env python3
"""Validate structure and WPM-derived timing for a full debate JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:\.\d+)?")
ROLES = ("MOD", "PRO", "CON")
REFERENCE_DIR = Path(__file__).resolve().parents[1] / "references"


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def length_band(n_words: int) -> str:
    if n_words <= 2:
        return "1-2"
    if n_words <= 5:
        return "3-5"
    if n_words <= 10:
        return "6-10"
    if n_words <= 17:
        return "11-17"
    if n_words <= 34:
        return "18-34"
    if n_words <= 59:
        return "35-59"
    return "60-100"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument(
        "--contract",
        type=Path,
        default=REFERENCE_DIR / "full-debate-contract.json",
    )
    parser.add_argument(
        "--voices",
        type=Path,
        default=REFERENCE_DIR / "default-voice-profiles.json",
    )
    args = parser.parse_args()

    data = load_json(args.transcript)
    contract = load_json(args.contract)
    voices = load_json(args.voices)["voices"]
    errors: list[str] = []
    warnings: list[str] = []

    profile = data.get("duration_profile")
    if profile not in contract["profiles"]:
        errors.append(f"unknown duration_profile: {profile!r}")
        profile_contract = None
    else:
        profile_contract = contract["profiles"][profile]

    participants = data.get("participants", {})
    if set(participants) != set(ROLES):
        errors.append(f"participants must be exactly {sorted(ROLES)}")

    voice_by_role: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        voice_id = participants.get(role, {}).get("voice_id")
        if voice_id not in voices:
            errors.append(f"{role} voice_id is not in the supplied voice profiles: {voice_id!r}")
        else:
            voice_by_role[role] = voices[voice_id]

    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        errors.append("turns must be a non-empty list")
        turns = []

    turn_ids: set[str] = set()
    turn_by_id: dict[str, dict[str, Any]] = {}
    turn_index_by_id: dict[str, int] = {}
    phases: list[int] = []
    timing_rows: list[dict[str, Any]] = []
    duration_by_role = {role: 0.0 for role in ROLES}
    words_by_role = {role: 0 for role in ROLES}
    phase_duration = {1: 0.0, 2: 0.0, 3: 0.0}
    taxonomy_turns: dict[str, list[str]] = {}

    for index, turn in enumerate(turns):
        turn_id = turn.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            errors.append(f"turn {index}: missing turn_id")
            turn_id = f"__missing_{index}"
        if turn_id in turn_ids:
            errors.append(f"duplicate turn_id: {turn_id}")
        turn_ids.add(turn_id)
        turn_by_id[turn_id] = turn
        turn_index_by_id[turn_id] = index

        phase = turn.get("phase")
        if phase not in (1, 2, 3):
            errors.append(f"{turn_id}: invalid phase {phase!r}")
            continue
        phases.append(phase)

        role = turn.get("speaker")
        if role not in ROLES:
            errors.append(f"{turn_id}: invalid speaker {role!r}")
            continue
        text = turn.get("text", "")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{turn_id}: empty text")
            continue
        if "[" in text or "]" in text:
            errors.append(f"{turn_id}: unresolved square-bracket tag")
        if re.search(r"\baudience\b", text, flags=re.IGNORECASE):
            errors.append(f"{turn_id}: audience language is not allowed")

        n_words = word_count(text)
        if n_words > contract["timing"]["max_words_per_turn"]:
            errors.append(f"{turn_id}: {n_words} words exceeds max turn length")
        band = length_band(n_words)
        if role in voice_by_role:
            sec_per_word = voice_by_role[role]["by_length"][band]["sec_per_word"]
            speech_sec = n_words * sec_per_word
        else:
            speech_sec = 0.0
        gap = turn.get("gap_after_sec", 0.0)
        overlap = turn.get("overlap_sec", 0.0)
        if not isinstance(gap, (int, float)) or gap < 0:
            errors.append(f"{turn_id}: invalid gap_after_sec")
            gap = 0.0
        if not isinstance(overlap, (int, float)) or overlap < 0:
            errors.append(f"{turn_id}: invalid overlap_sec")
            overlap = 0.0
        overlap_with = turn.get("overlap_with")
        if overlap > 0 and not overlap_with:
            errors.append(f"{turn_id}: positive overlap requires overlap_with")

        row_duration = speech_sec + float(gap) - float(overlap)
        duration_by_role[role] += speech_sec
        words_by_role[role] += n_words
        phase_duration[phase] += row_duration
        timing_rows.append(
            {
                "turn_id": turn_id,
                "phase": phase,
                "speaker": role,
                "words": n_words,
                "band": band,
                "speech_sec": round(speech_sec, 3),
                "gap_sec": gap,
                "overlap_sec": overlap,
                "timeline_sec": round(row_duration, 3),
            }
        )

        taxonomies = turn.get("taxonomy", [])
        if not isinstance(taxonomies, list):
            errors.append(f"{turn_id}: taxonomy must be a list")
            taxonomies = []
        if len(taxonomies) > 1:
            errors.append(f"{turn_id}: do not combine taxonomy events")
        for taxonomy in taxonomies:
            if taxonomy not in contract["allowed_taxonomies"]:
                errors.append(f"{turn_id}: unknown taxonomy {taxonomy}")
            taxonomy_turns.setdefault(taxonomy, []).append(turn_id)
            if role != "MOD":
                errors.append(f"{turn_id}: taxonomy event must be on MOD turn")

    if phases != sorted(phases):
        errors.append("phase order is not monotonic 1 -> 2 -> 3")
    if set(phases) != {1, 2, 3}:
        errors.append("all three phases must be present")
    if turns and turns[0].get("speaker") != "MOD":
        errors.append("first turn must be MOD introduction")

    phase2_turns = [turn for turn in turns if turn.get("phase") == 2]
    phase3_turns = [turn for turn in turns if turn.get("phase") == 3]
    if not phase2_turns or phase2_turns[0].get("speaker") != "MOD" or phase2_turns[0].get("taxonomy") != ["A3-1"]:
        errors.append("first Phase 2 turn must be MOD with only A3-1")
    if not phase3_turns or phase3_turns[0].get("speaker") != "MOD" or phase3_turns[0].get("taxonomy") != ["A3-2"]:
        errors.append("first Phase 3 turn must be MOD with only A3-2")
    phase3_debaters = [turn.get("speaker") for turn in phase3_turns if turn.get("speaker") in {"PRO", "CON"}]
    if not phase3_debaters or phase3_debaters[0] != "PRO":
        errors.append("Phase 3 must call PRO before CON")

    targets = data.get("target_taxonomies", [])
    if not isinstance(targets, list) or len(set(targets)) != len(targets):
        errors.append("target_taxonomies must be a unique list")
        targets = []
    count_rule = contract["taxonomy_count_per_sample"]
    if not count_rule["min"] <= len(targets) <= count_rule["max"]:
        errors.append(f"target taxonomy count must be {count_rule['min']}..{count_rule['max']}")
    for required in contract["required_taxonomies"]:
        if required not in targets:
            errors.append(f"missing required target taxonomy: {required}")
    for taxonomy in targets:
        if len(taxonomy_turns.get(taxonomy, [])) != 1:
            errors.append(f"target {taxonomy} must occur on exactly one MOD turn")
    for taxonomy in taxonomy_turns:
        if taxonomy not in targets:
            errors.append(f"turn contains non-target taxonomy: {taxonomy}")

    events = data.get("events", [])
    event_by_taxonomy: dict[str, list[dict[str, Any]]] = {}
    for event in events if isinstance(events, list) else []:
        event_by_taxonomy.setdefault(event.get("taxonomy"), []).append(event)
        moderator_turn_id = event.get("moderator_turn_id")
        trigger_ids = event.get("trigger_turn_ids", [])
        if moderator_turn_id not in turn_ids:
            errors.append(f"event {event.get('taxonomy')}: missing moderator turn link")
        if not trigger_ids or any(trigger not in turn_ids for trigger in trigger_ids):
            errors.append(f"event {event.get('taxonomy')}: invalid or empty trigger_turn_ids")
        if moderator_turn_id in turn_index_by_id and trigger_ids and all(trigger in turn_index_by_id for trigger in trigger_ids):
            if any(turn_index_by_id[trigger] >= turn_index_by_id[moderator_turn_id] for trigger in trigger_ids):
                errors.append(f"event {event.get('taxonomy')}: every trigger must precede MOD action")

        if event.get("taxonomy") == "A5" and len(trigger_ids) >= 2 and all(trigger in turn_by_id for trigger in trigger_ids):
            floor_turn = turn_by_id[trigger_ids[-2]]
            interrupt_turn = turn_by_id[trigger_ids[-1]]
            if {floor_turn.get("speaker"), interrupt_turn.get("speaker")} != {"PRO", "CON"}:
                errors.append("A5 requires different debaters as floor holder and interrupter")
            if interrupt_turn.get("overlap_sec", 0) <= 0:
                errors.append("A5 interrupting turn must have positive overlap_sec")
            if interrupt_turn.get("overlap_with") != floor_turn.get("turn_id"):
                errors.append("A5 interrupting turn must overlap with the listed floor holder")
            if word_count(interrupt_turn.get("text", "")) > contract["timing"]["max_a5_interrupt_words"]:
                errors.append(f"A5 interrupting turn exceeds {contract['timing']['max_a5_interrupt_words']} words")

        if event.get("taxonomy") == "B2" and trigger_ids and all(trigger in turn_by_id for trigger in trigger_ids):
            trigger_speakers = {turn_by_id[trigger].get("speaker") for trigger in trigger_ids}
            if len(trigger_ids) < 2:
                errors.append("B2 requires at least two explicit claim trigger turns")
            if len(trigger_speakers) != 1 or next(iter(trigger_speakers)) not in {"PRO", "CON"}:
                errors.append("B2 trigger turns must be claims by the same non-moderator speaker")
    for taxonomy in targets:
        linked = event_by_taxonomy.get(taxonomy, [])
        if len(linked) != 1:
            errors.append(f"target {taxonomy} must have exactly one event manifest row")
        elif linked[0].get("moderator_turn_id") not in taxonomy_turns.get(taxonomy, []):
            errors.append(f"event {taxonomy}: moderator turn does not match taxonomy turn")

    total_duration = sum(row["timeline_sec"] for row in timing_rows)
    first_turn_id = turns[0].get("turn_id") if turns else None
    first_turn_speech = next((row["speech_sec"] for row in timing_rows if row["turn_id"] == first_turn_id), 0.0)
    intro_rule = contract["timing"]["moderator_intro_sec"]
    if not intro_rule["min"] <= first_turn_speech <= intro_rule["max"]:
        errors.append(f"moderator introduction {first_turn_speech:.2f}s outside {intro_rule['min']}..{intro_rule['max']}")

    for phase, rule_name, label in ((1, "opening_per_debater_sec", "opening"), (3, "closing_per_debater_sec", "closing")):
        rule = contract["timing"][rule_name]
        for role in ("PRO", "CON"):
            seconds = sum(row["speech_sec"] for row in timing_rows if row["phase"] == phase and row["speaker"] == role)
            if not rule["min"] <= seconds <= rule["max"]:
                errors.append(f"{role} {label} {seconds:.2f}s outside {rule['min']}..{rule['max']}")

    if profile_contract:
        total_rule = profile_contract["total_duration_sec"]
        if not total_rule["min"] <= total_duration <= total_rule["max"]:
            errors.append(f"total duration {total_duration:.2f}s outside {total_rule['min']}..{total_rule['max']}")
        phase2_rule = profile_contract["phase2_duration_sec"]
        if not phase2_rule["min"] <= phase_duration[2] <= phase2_rule["max"]:
            errors.append(f"Phase 2 duration {phase_duration[2]:.2f}s outside {phase2_rule['min']}..{phase2_rule['max']}")

    pro_con = [duration_by_role["PRO"], duration_by_role["CON"]]
    ratio = max(pro_con) / min(pro_con) if min(pro_con) > 0 else None
    if ratio is not None and ratio > contract["timing"]["max_pro_con_duration_ratio"]:
        errors.append(f"PRO/CON speech duration ratio {ratio:.3f} exceeds limit")
    total_words = sum(words_by_role.values())
    moderator_share = words_by_role["MOD"] / total_words if total_words else 0.0
    if moderator_share > contract["timing"]["max_moderator_word_share"]:
        errors.append(f"moderator word share {moderator_share:.3f} exceeds limit")

    semantic_targets = sorted(set(targets) & {"A1", "A2-1", "A2-2", "A4", "B1", "B2"})
    if semantic_targets:
        warnings.append(
            "full taxonomy semantics/timing topology require transcript-only review for: "
            + ", ".join(semantic_targets)
        )

    report = {
        "sample_id": data.get("sample_id"),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "total_duration_sec": round(total_duration, 3),
            "phase_duration_sec": {str(key): round(value, 3) for key, value in phase_duration.items()},
            "speech_duration_by_role_sec": {key: round(value, 3) for key, value in duration_by_role.items()},
            "words_by_role": words_by_role,
            "pro_con_duration_ratio": round(ratio, 4) if ratio is not None else None,
            "moderator_word_share": round(moderator_share, 4),
        },
        "turn_timing": timing_rows,
    }
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
