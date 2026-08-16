#!/usr/bin/env python3
"""Render one project-schema full debate as bilingual Markdown."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("validation", type=Path)
    parser.add_argument("translations", type=Path)
    args = parser.parse_args()

    sample = load_json(args.transcript)
    validation = load_json(args.validation)
    translations = load_json(args.translations)
    turn_ids = {turn.get("turn_id") for turn in sample.get("turns", [])}
    translation_ids = set(translations) if isinstance(translations, dict) else set()
    errors: list[str] = []

    if validation.get("sample_id") != sample.get("sample_id"):
        errors.append("validation sample_id does not match transcript")
    if not validation.get("valid"):
        errors.append("automatic full-debate validation is not PASS")
    if turn_ids != translation_ids:
        errors.append(
            "translation keys must exactly match turn IDs; "
            f"missing={sorted(turn_ids - translation_ids)}, extra={sorted(translation_ids - turn_ids)}"
        )
    if isinstance(translations, dict):
        empty = sorted(
            turn_id
            for turn_id, value in translations.items()
            if not isinstance(value, str) or not value.strip()
        )
        if empty:
            errors.append(f"empty Korean translations: {empty}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    metrics = validation["metrics"]
    semantic_codes = sorted(set(sample.get("target_taxonomies", [])) & {"B1", "B2"})
    print(f"# {sample.get('sample_id', 'full debate')}")
    print()
    print(f"- Profile: `{sample.get('duration_profile')}`")
    print(f"- Motion: **{sample.get('motion')}**")
    print(f"- Target: {', '.join(sample.get('target_taxonomies', []))}")
    print(f"- Voice-WPM 예상 길이: {metrics['total_duration_sec']:.3f}s")
    print("- Automatic validation: **PASS**")
    if semantic_codes:
        print(f"- Semantic review required: {', '.join(semantic_codes)}")
    print()
    print("## Events")
    print()
    print("| Taxonomy | MOD turn | Trigger turns | Realization |")
    print("|---|---|---|---|")
    for event in sample.get("events", []):
        trigger_ids = ", ".join(f"`{item}`" for item in event.get("trigger_turn_ids", []))
        note = str(event.get("realization_note", "")).replace("|", "\\|")
        print(
            f"| {event.get('taxonomy')} | `{event.get('moderator_turn_id')}` | "
            f"{trigger_ids} | {note} |"
        )
    print()
    print("## Transcript")
    print()

    phase = None
    participants = sample.get("participants", {})
    for turn in sample.get("turns", []):
        if turn.get("phase") != phase:
            phase = turn.get("phase")
            print(f"### Phase {phase}")
            print()
        badges = " ".join(f"**[{code}]**" for code in turn.get("taxonomy", []))
        overlap = ""
        if turn.get("overlap_sec", 0) > 0:
            overlap = (
                f" _(overlap {turn['overlap_sec']:.1f}s with "
                f"`{turn.get('overlap_with')}`)_"
            )
        role = turn.get("speaker")
        name = participants.get(role, {}).get("name", "")
        print(f"**{role} / {name}** `{turn.get('turn_id')}` {badges}{overlap}".rstrip())
        print()
        print(turn.get("text", ""))
        print()
        print(f"> **한국어 해석:** {translations[turn['turn_id']]}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
