from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def aggregate_scores(paths: Iterable[str | Path]) -> dict[str, Any]:
    rows = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    status = Counter(row["temporal"]["status"] for row in rows)
    by_label: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_label[row["gold"]["label"]][row["temporal"]["status"]] += 1
    correct = sum(bool(row["temporal"]["pass"]) for row in rows)
    positives = [row for row in rows if row["gold"]["label"] != "none"]
    negatives = [row for row in rows if row["gold"]["label"] == "none"]
    return {
        "n": len(rows),
        "temporal_accuracy": correct / len(rows) if rows else None,
        "positive_on_time_rate": (
            sum(row["temporal"]["status"] == "ON_TIME" for row in positives) / len(positives)
            if positives else None
        ),
        "negative_false_positive_rate": (
            sum(row["temporal"]["status"] == "FALSE_POSITIVE" for row in negatives) / len(negatives)
            if negatives else None
        ),
        "status": dict(sorted(status.items())),
        "by_label": {label: dict(sorted(counts.items())) for label, counts in sorted(by_label.items())},
        "note": "Development aggregate only; paired debate-level confidence intervals are not yet computed.",
    }
