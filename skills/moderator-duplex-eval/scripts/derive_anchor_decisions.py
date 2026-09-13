#!/usr/bin/env python3
"""Derive model-vs-reference crossfire anchors from blinded A3-1 reviews."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deterministic-dir", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    timing = read_json(args.deterministic_dir.resolve() / "timing.json")
    reviews_doc = read_json(args.reviews.resolve())
    reviews = {row["review_id"]: row for row in reviews_doc.get("items") or []}
    if len(reviews) != len(reviews_doc.get("items") or []):
        raise SystemExit("duplicate review_id in semantic review")

    decisions: dict[str, dict[str, Any]] = {}
    for row in timing["rows"]:
        if row["code"] != "A3-1":
            continue
        debate_id = row["debate_id"]
        if debate_id in decisions:
            raise SystemExit(f"{debate_id}: multiple primary A3-1 rows")
        if row["candidate"] is None:
            decisions[debate_id] = {
                "opened_crossfire": False,
                "basis": "no eligible A3-1 candidate; EVAL_SETTING reference fallback",
                "gt_id": row["gt_id"],
                "review_id": None,
            }
            continue
        review_id = f"content:{row['gt_id']}"
        review = reviews.get(review_id)
        if review is None:
            raise SystemExit(f"missing A3-1 semantic review: {review_id}")
        met = review.get("met")
        if not isinstance(met, list) or len(met) != len(row["criteria"]) or not all(isinstance(v, bool) for v in met):
            raise SystemExit(f"invalid A3-1 met array: {review_id}")
        decisions[debate_id] = {
            "opened_crossfire": bool(met[0]),
            "basis": (
                "A3-1 round-change criterion met; use model utterance end"
                if met[0]
                else "A3-1 round-change criterion not met; EVAL_SETTING reference fallback"
            ),
            "gt_id": row["gt_id"],
            "review_id": review_id,
            "candidate_utterance_id": row["candidate"]["utterance_id"],
        }

    expected = {row["debate_id"] for row in timing["rows"]}
    if set(decisions) != expected:
        missing = sorted(expected - set(decisions))
        raise SystemExit(f"missing primary A3-1 row for debates: {missing}")
    output = {
        "schema_version": "moderator-duplex-anchor-decisions-v1",
        "rule": "Use model A3-1 end only when the blinded round-change criterion is met; otherwise use reference xf_open_sec fallback.",
        "reviewer": reviews_doc.get("reviewer"),
        "debates": decisions,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
