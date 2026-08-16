#!/usr/bin/env python3
"""Allocate reproducible, stratified variation cards for taxonomy generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from typing import Any


TAXONOMIES = ("A1", "A2-1", "A2-2", "A3-1", "A3-2", "A4", "A5", "B1", "B2")

DOMAIN_FAMILIES = (
    ("education", "curriculum-and-school-policy"),
    ("environment", "waste-and-conservation-policy"),
    ("workplace", "work-schedule-and-employment-policy"),
    ("urban-policy", "transport-and-public-space"),
    ("public-health", "prevention-and-consumer-policy"),
    ("technology", "automation-and-digital-access"),
    ("energy", "power-generation-and-grid-policy"),
    ("culture", "arts-media-and-public-funding"),
    ("housing", "rent-supply-and-neighborhood-policy"),
    ("food", "agriculture-and-consumer-choice"),
    ("science", "research-and-exploration-policy"),
    ("civic-life", "participation-and-local-government"),
)

MODERATOR_STYLES = (
    "minimal-neutral",
    "formal-procedural",
    "firm-concise",
    "calm-conversational",
    "explicit-transition",
    "courteous-direct",
    "broadcast-neutral",
    "plain-language",
    "measured-firm",
)

PARTICIPANT_SETS = (
    {"MOD": "Maya", "PRO": "Daniel", "CON": "Sarah"},
    {"MOD": "Elena", "PRO": "Marcus", "CON": "Priya"},
    {"MOD": "Jonah", "PRO": "Leah", "CON": "Omar"},
    {"MOD": "Nora", "PRO": "Ethan", "CON": "Camila"},
    {"MOD": "Victor", "PRO": "Aisha", "CON": "Lucas"},
    {"MOD": "Grace", "PRO": "Noah", "CON": "Mei"},
    {"MOD": "Adrian", "PRO": "Sofia", "CON": "Malik"},
    {"MOD": "Iris", "PRO": "Theo", "CON": "Hana"},
    {"MOD": "Samuel", "PRO": "Rina", "CON": "Gabriel"},
)

SUBTYPES = {
    "A1": ("unfinished-summary", "final-example-overrun", "rebuttal-clause-overrun"),
    "A2-1": ("overrun-to-opponent", "repeated-point-overrun", "unfinished-list-handoff"),
    "A2-2": ("completed-opening", "completed-answer", "completed-rebuttal"),
    "A3-1": ("PRO-direct-question-first", "CON-direct-challenge-first", "open-floor-response"),
    "A3-2": ("hard-time-boundary", "natural-direct-debate-wrap", "moderator-scheduled-close"),
    "A4": ("remaining-8s", "remaining-10s", "remaining-12s"),
    "A5": ("brief-denial", "clarification-interrupt", "premise-correction"),
    "B1": ("anecdotal-drift", "implementation-detail-drift", "aesthetic-side-topic"),
    "B2": ("necessary-vs-sufficient", "universal-vs-none", "required-policy-vs-rejected-policy"),
}

ROLE_PATTERNS = {
    "A1": ("PRO_floor", "CON_floor"),
    "A2-1": ("PRO_to_CON", "CON_to_PRO"),
    "A2-2": ("PRO_to_CON", "CON_to_PRO"),
    "A3-1": ("PRO_first_direct", "CON_first_direct"),
    "A3-2": ("PRO_closing_first",),
    "A4": ("PRO_floor", "CON_floor"),
    "A5": ("PRO_interrupts_CON", "CON_interrupts_PRO"),
    "B1": ("PRO_drifts", "CON_drifts"),
    "B2": ("PRO_claims", "CON_claims"),
}

TIMING_PROFILES = {
    "A1": ("deadline-plus-0.2s", "deadline-plus-0.8s", "deadline-plus-1.4s"),
    "A2-1": ("early-barge-in", "mid-barge-in", "late-barge-in"),
    "A2-2": ("gap-0.2s", "gap-0.5s", "gap-0.8s"),
    "A3-1": ("transition-gap-0.3s", "transition-gap-0.6s", "transition-gap-0.9s"),
    "A3-2": ("transition-gap-0.3s", "transition-gap-0.6s", "transition-gap-0.9s"),
    "A4": ("remaining-8s", "remaining-10s", "remaining-12s"),
    "A5": ("MOD-during-interrupt", "MOD-at-interrupt-end", "MOD-plus-0.3s"),
    "B1": ("redirect-gap-0.2s", "redirect-gap-0.5s", "redirect-gap-0.8s"),
    "B2": ("contrast-gap-0.2s", "contrast-gap-0.5s", "contrast-gap-0.8s"),
}


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def shuffled(values: tuple[Any, ...], rng: random.Random) -> list[Any]:
    result = list(values)
    rng.shuffle(result)
    return result


def build_plan(taxonomies: list[str], seed: str) -> dict[str, Any]:
    unknown = sorted(set(taxonomies) - set(TAXONOMIES))
    if unknown:
        raise ValueError(f"unknown taxonomies: {unknown}")
    if len(taxonomies) != len(set(taxonomies)):
        raise ValueError("taxonomies must not contain duplicates")
    rng = random.Random(seed)
    domains = shuffled(DOMAIN_FAMILIES, rng)
    styles = shuffled(MODERATOR_STYLES, rng)
    participants = shuffled(PARTICIPANT_SETS, rng)
    seed_tag = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    cards = []
    for index, taxonomy in enumerate(taxonomies):
        domain, motion_family = domains[index % len(domains)]
        role_pattern = rng.choice(ROLE_PATTERNS[taxonomy])
        trigger_subtype = rng.choice(SUBTYPES[taxonomy])
        timing_profile = trigger_subtype if taxonomy == "A4" else rng.choice(TIMING_PROFILES[taxonomy])
        participant_names = participants[index % len(participants)]
        cards.append(
            {
                "taxonomy": taxonomy,
                "variation_id": f"{seed_tag}-{slug(taxonomy)}-{index + 1:02d}",
                "seed": seed,
                "domain": domain,
                "motion_family": motion_family,
                "trigger_subtype": trigger_subtype,
                "role_pattern": role_pattern,
                "moderator_style": styles[index % len(styles)],
                "timing_profile": timing_profile,
                "participant_set": f"set-{PARTICIPANT_SETS.index(participant_names) + 1:02d}",
                "participants": participant_names,
            }
        )
    return {"schema_version": "0.1", "variation_seed": seed, "cards": cards}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True, help="Recorded reproducibility seed")
    parser.add_argument("taxonomies", nargs="+", choices=TAXONOMIES)
    args = parser.parse_args()
    try:
        plan = build_plan(args.taxonomies, args.seed)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
