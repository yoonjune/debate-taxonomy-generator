#!/usr/bin/env python3
"""Render one taxonomy JSON sample into bilingual human-readable Markdown."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_sample import DEFAULT_CONTRACT, load_json, validate_sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    sample = load_json(args.sample)
    report = validate_sample(sample, load_json(args.contract))

    print(f"# {sample.get('sample_id', 'taxonomy sample')}")
    print()
    print(f"- Mode: `{sample.get('mode')}`")
    print(f"- Motion: **{sample.get('motion')}**")
    print(f"- Target: {', '.join(sample.get('target_taxonomies', []))}")
    print(f"- Automatic validation: **{'PASS' if report['automatic_valid'] else 'FAIL'}**")
    print(f"- Timeline span: {report['metrics']['duration_sec']:.3f}s")
    print(
        f"- Maximum turn rate: {report['metrics']['max_turn_wpm']:.3f} WPM "
        f"(`{report['metrics']['max_turn_wpm_turn_id']}`; ceiling 260 WPM)"
    )
    if report["warnings"]:
        print(f"- Semantic warnings: {'; '.join(report['warnings'])}")
    print()

    print("## Events")
    print()
    print("| Taxonomy | MOD turn | Trigger turns |")
    print("|---|---|---|")
    for event in sample.get("events", []):
        triggers = ", ".join(f"`{turn_id}`" for turn_id in event.get("trigger_turn_ids", []))
        print(f"| {event.get('taxonomy')} | `{event.get('moderator_turn_id')}` | {triggers} |")
    print()

    print("## Transcript")
    print()
    names = sample.get("participants", {})
    translations = sample.get("translations_ko", {})
    for turn in sample.get("turns", []):
        badges = " ".join(f"**[{code}]**" for code in turn.get("taxonomy", []))
        name = names.get(turn.get("speaker"), {}).get("name", "")
        print(
            f"**{turn.get('speaker')} / {name}** `{turn.get('turn_id')}` "
            f"`{turn.get('start_sec'):.2f}–{turn.get('end_sec'):.2f}s` {badges}".rstrip()
        )
        print()
        print(turn.get("text", ""))
        print()
        print(f"> **한국어 해석:** {translations.get(turn.get('turn_id'), '')}")
        print()

    if report["errors"]:
        print("## Automatic validation errors")
        print()
        for error in report["errors"]:
            print(f"- {error}")
        print()
    return 0 if report["automatic_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
