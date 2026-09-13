#!/usr/bin/env python3
"""Validate blinded semantic judgments and finalize an EVAL_SETTING report."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BARGE_PRECEDENCE = (
    "on_time_required_and_correct",
    "late_required_and_correct",
    "premature_but_content_correct",
    "other_matched_barge_in",
    "stale_required_action",
    "other_contextually_acceptable_barge_in",
    "other_awkward_or_violating_barge_in",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def distribution(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median": percentile(values, 0.5),
        "q1": percentile(values, 0.25),
        "q3": percentile(values, 0.75),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deterministic-dir", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument(
        "--adjudications", action="append", default=[], type=Path,
        help="optional blinded subset review; later files override matching primary review IDs",
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    base = args.deterministic_dir.resolve()
    timing = read_json(base / "timing.json")
    barge = read_json(base / "barge_in_candidates.json")
    packet = read_json(base / "review_packet.json")
    keys = {row["review_id"]: row for row in read_json(base / "review_key.json")["items"]}
    reviews_doc = read_json(args.reviews.resolve())
    review_sources = [("primary", reviews_doc)] + [
        (str(path.resolve()), read_json(path.resolve())) for path in args.adjudications
    ]
    judgments: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    packet_items = {row["review_id"]: row for row in packet["items"]}

    for source_name, source_doc in review_sources:
        seen_in_source: set[str] = set()
        for item in source_doc.get("items") or []:
            review_id = item.get("review_id")
            if review_id not in packet_items:
                errors.append(f"{source_name}: unknown review_id: {review_id}")
                continue
            if review_id in seen_in_source:
                errors.append(f"{source_name}: duplicate review_id: {review_id}")
                continue
            seen_in_source.add(review_id)
            task = packet_items[review_id]["task"]
            if task in ("content", "stale_content"):
                criteria = packet_items[review_id]["criteria"]
                met = item.get("met")
                why = item.get("why")
                if not isinstance(met, list) or len(met) != len(criteria) or not all(isinstance(v, bool) for v in met):
                    errors.append(f"{source_name}/{review_id}: met must contain one boolean per criterion")
                    continue
                if not isinstance(why, list) or len(why) != len(criteria) or not all(isinstance(v, str) and v.strip() for v in why):
                    errors.append(f"{source_name}/{review_id}: why must contain one non-empty string per criterion")
                    continue
                if item.get("action") not in packet_items[review_id]["actions"]:
                    errors.append(f"{source_name}/{review_id}: action must be copied from the supplied list")
                    continue
            elif task == "non_trigger":
                if item.get("verdict") not in packet_items[review_id]["allowed_verdicts"]:
                    errors.append(f"{source_name}/{review_id}: invalid non-trigger verdict")
                    continue
                if not isinstance(item.get("why"), str) or not item["why"].strip():
                    errors.append(f"{source_name}/{review_id}: why is required")
                    continue
                if item.get("verdict") == "violation" and not (
                    isinstance(item.get("violated_duty"), str) and item["violated_duty"].strip()
                ):
                    errors.append(f"{source_name}/{review_id}: violation requires violated_duty")
                    continue
            judgments[review_id] = item

    if errors:
        raise SystemExit("invalid review file:\n- " + "\n- ".join(errors))

    timing_rows: list[dict[str, Any]] = []
    content_by_gt: dict[str, float | str] = {}
    missing_reviews: list[str] = []
    for row in timing["rows"]:
        updated = dict(row)
        if row["candidate"] is None:
            updated["content_score"] = 0.0
            updated["joint_score"] = 0.0
            updated["content_provenance"] = "no attributed utterance"
        else:
            review_id = f"content:{row['gt_id']}"
            review = judgments.get(review_id)
            if review is None:
                updated["content_score"] = "UNKNOWN"
                updated["joint_score"] = "UNKNOWN"
                updated["content_provenance"] = "missing semantic review"
                missing_reviews.append(review_id)
            else:
                score = sum(review["met"]) / len(review["met"])
                updated["content_score"] = score
                updated["content_met"] = review["met"]
                updated["content_why"] = review["why"]
                updated["predicted_action"] = review["action"]
                updated["joint_score"] = score if row["timing"] == "ON_TIME" else 0.0
                updated["content_provenance"] = "fresh blinded semantic review"
                content_by_gt[row["gt_id"]] = score
        timing_rows.append(updated)

    nontrigger_reviews: dict[str, dict[str, Any]] = {}
    for review_id, key in keys.items():
        if key["task"] == "non_trigger":
            review = judgments.get(review_id)
            if review is None:
                missing_reviews.append(review_id)
            else:
                nontrigger_reviews[key["utterance_id"]] = review

    stale_correct: set[tuple[str, str]] = set()
    for review_id, key in keys.items():
        if key["task"] != "stale_content":
            continue
        review = judgments.get(review_id)
        if review is None:
            missing_reviews.append(review_id)
            continue
        if all(review["met"]):
            stale_correct.add((key["utterance_id"], key["gt_id"]))

    rows_by_gt = {row["gt_id"]: row for row in timing_rows}
    group_counts: Counter[str] = Counter()
    run_outputs: list[dict[str, Any]] = []
    for run in barge["runs"]:
        output_utts: list[dict[str, Any]] = []
        for utt in run["utterances"]:
            updated = dict(utt)
            group = None
            if utt["barge_in"]:
                links = [rows_by_gt[gt_id] for gt_id in utt["matched_gt_ids"]]
                if any(row["timing"] == "ON_TIME" and row["content_score"] == 1.0 for row in links):
                    group = "on_time_required_and_correct"
                elif any(row["timing"] == "LATE" and row["content_score"] == 1.0 for row in links):
                    group = "late_required_and_correct"
                elif any(row["timing"] == "PREMATURE" and row["content_score"] == 1.0 for row in links):
                    group = "premature_but_content_correct"
                elif links:
                    group = "other_matched_barge_in"
                elif any((utt["utterance_id"], stale["gt_id"]) in stale_correct
                         for stale in utt["stale_review_candidates"]):
                    group = "stale_required_action"
                else:
                    verdict = (nontrigger_reviews.get(utt["utterance_id"]) or {}).get("verdict")
                    if verdict == "acceptable":
                        group = "other_contextually_acceptable_barge_in"
                    elif verdict in ("awkward", "violation"):
                        group = "other_awkward_or_violating_barge_in"
                    else:
                        group = "UNKNOWN"
                group_counts[group] += 1
            updated["diagnostic_group"] = group
            nontrigger_review = nontrigger_reviews.get(utt["utterance_id"]) or {}
            updated["non_trigger_verdict"] = nontrigger_review.get("verdict", "UNKNOWN")
            updated["non_trigger_why"] = nontrigger_review.get("why")
            updated["non_trigger_violated_duty"] = nontrigger_review.get("violated_duty")
            output_utts.append(updated)
        run_outputs.append({**run, "utterances": output_utts})

    known_content = [row["content_score"] for row in timing_rows if isinstance(row["content_score"], (int, float))]
    known_joint = [row["joint_score"] for row in timing_rows if isinstance(row["joint_score"], (int, float))]
    by_code: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in timing_rows:
        grouped[row["code"]].append(row)
    for code, rows in sorted(grouped.items()):
        counts = Counter(row["timing"] for row in rows)
        content = [row["content_score"] for row in rows if isinstance(row["content_score"], (int, float))]
        joint = [row["joint_score"] for row in rows if isinstance(row["joint_score"], (int, float))]
        onset_offsets = [
            float(row["onset_minus_deadline_sec"])
            for row in rows if row["onset_minus_deadline_sec"] is not None
        ]
        actions = Counter(
            row["predicted_action"] for row in rows if row.get("predicted_action")
        )
        half_credit: list[dict[str, Any]] = []
        for row in rows:
            if row.get("content_score") != 0.5:
                continue
            met_flags = row.get("content_met") or []
            half_credit.append({
                "gt_id": row["gt_id"],
                "utterance_id": row["candidate"]["utterance_id"] if row.get("candidate") else None,
                "met": [criterion for criterion, flag in zip(row["criteria"], met_flags) if flag],
                "missing": [criterion for criterion, flag in zip(row["criteria"], met_flags) if not flag],
                "why": row.get("content_why") or [],
            })
        by_code[code] = {
            "n": len(rows),
            "timing": dict(counts),
            "onset_minus_deadline_sec": distribution(onset_offsets),
            "content_mean_known": sum(content) / len(content) if content else None,
            "joint_mean_known": sum(joint) / len(joint) if joint else None,
            "predicted_action_counts": dict(actions),
            "half_credit": half_credit,
        }

    per_debate: dict[str, dict[str, Any]] = {}
    for debate_id in sorted({row["debate_id"] for row in timing_rows}):
        debate_rows = [row for row in timing_rows if row["debate_id"] == debate_id]
        content = [row["content_score"] for row in debate_rows if isinstance(row["content_score"], (int, float))]
        joint = [row["joint_score"] for row in debate_rows if isinstance(row["joint_score"], (int, float))]
        nontriggers: list[dict[str, Any]] = []
        for run in run_outputs:
            if run["debate_id"] != debate_id:
                continue
            for utt in run["utterances"]:
                if utt["kind"] == "non_trigger":
                    nontriggers.append({
                        "utterance_id": utt["utterance_id"],
                        "text": utt.get("text"),
                        "barge_in": utt["barge_in"],
                        "verdict": utt["non_trigger_verdict"],
                        "why": utt.get("non_trigger_why"),
                        "violated_duty": utt.get("non_trigger_violated_duty"),
                    })
        per_debate[debate_id] = {
            "primary_n": len(debate_rows),
            "timing": dict(Counter(row["timing"] for row in debate_rows)),
            "content_mean_known": sum(content) / len(content) if content else None,
            "joint_mean_known": sum(joint) / len(joint) if joint else None,
            "non_trigger_n": len(nontriggers),
            "non_trigger_verdicts": dict(Counter(row["verdict"] for row in nontriggers)),
            "non_trigger_rows": nontriggers,
        }

    reviewer = dict(reviews_doc.get("reviewer") or {})
    reviewer["adjudications"] = [
        {
            "path": str(path.resolve()),
            "reviewer": source_doc.get("reviewer"),
            "overridden_review_ids": [row.get("review_id") for row in source_doc.get("items") or []],
        }
        for path, (_, source_doc) in zip(args.adjudications, review_sources[1:])
    ]
    final = {
        "status": "PROVISIONAL_COMPLETE" if not missing_reviews else "PROVISIONAL_WITH_UNKNOWN",
        "human_gold": False,
        "reviewer": reviewer,
        "primary_unit": "removed_moderator_utterance",
        "primary_n": len(timing_rows),
        "timing": dict(Counter(row["timing"] for row in timing_rows)),
        "content_mean_known": sum(known_content) / len(known_content) if known_content else None,
        "joint_mean_known": sum(known_joint) / len(known_joint) if known_joint else None,
        "by_code": by_code,
        "per_debate": per_debate,
        "barge_in_groups": {key: group_counts.get(key, 0) for key in BARGE_PRECEDENCE},
        "missing_review_ids": sorted(set(missing_reviews)),
        "review_validation": {
            "packet_items": len(packet_items),
            "primary_review_items": len(reviews_doc.get("items") or []),
            "adjudication_files": len(args.adjudications),
            "adjudicated_review_ids": [
                row.get("review_id")
                for _, source_doc in review_sources[1:]
                for row in source_doc.get("items") or []
            ],
            "resolved_items": len(judgments),
            "missing_items": len(set(missing_reviews)),
        },
        "rows": timing_rows,
        "barge_in": {**barge, "runs": run_outputs},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.out.resolve(), final)
    print(json.dumps({
        "status": final["status"],
        "primary_n": final["primary_n"],
        "timing": final["timing"],
        "content_mean_known": final["content_mean_known"],
        "joint_mean_known": final["joint_mean_known"],
        "barge_in_groups": final["barge_in_groups"],
        "missing_reviews": len(final["missing_review_ids"]),
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
