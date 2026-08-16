#!/usr/bin/env python3
"""Regression checks for deterministic and diverse variation planning."""

from __future__ import annotations

import json
import sys

from plan_variations import TAXONOMIES, build_plan


def main() -> int:
    first = build_plan(list(TAXONOMIES), "variation-regression-001")
    repeated = build_plan(list(TAXONOMIES), "variation-regression-001")
    second = build_plan(list(TAXONOMIES), "variation-regression-002")
    cards = first["cards"]
    repeated_a4 = [build_plan(["A4"], f"repeat-a4-{index:02d}")["cards"][0] for index in range(8)]
    checks = {
        "same_seed_reproducible": first == repeated,
        "different_seed_changes_plan": first != second,
        "all_taxonomies_covered_once": [card["taxonomy"] for card in cards] == list(TAXONOMIES),
        "unique_variation_ids": len({card["variation_id"] for card in cards}) == len(cards),
        "unique_domains_in_nine_card_plan": len({card["domain"] for card in cards}) == len(cards),
        "unique_styles_in_nine_card_plan": len({card["moderator_style"] for card in cards}) == len(cards),
        "unique_participant_sets_in_nine_card_plan": len({card["participant_set"] for card in cards}) == len(cards),
        "repeated_a4_changes_domain": len({card["domain"] for card in repeated_a4}) >= 4,
        "repeated_a4_changes_role_pattern": len({card["role_pattern"] for card in repeated_a4}) >= 2,
        "repeated_a4_changes_trigger_subtype": len({card["trigger_subtype"] for card in repeated_a4}) >= 2,
        "a4_trigger_and_timing_stay_aligned": all(
            card["trigger_subtype"] == card["timing_profile"] for card in repeated_a4
        ),
    }
    result = {"valid": all(checks.values()), "checks": checks, "first_plan": first}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
