from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProbePlan:
    probe_id: str
    debate_id: str
    label: str
    kind: str
    release_sec: float
    decision_earliest_sec: float | None
    decision_deadline_sec: float | None
    decision_latest_sec: float
    observe_end_sec: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_probe_plan(probe: dict[str, Any], evaluation: dict[str, Any]) -> ProbePlan:
    positive = probe["label"] != "none"
    kind = probe.get("kind") or "negative"
    if positive:
        deadline = float(probe["t_deadline"])
        earliest = float(probe["t_earliest"])
        latest = float(probe["t_latest"])
        lead_by_kind = evaluation["positive_release_lead_sec"]
        if kind not in lead_by_kind:
            raise ValueError(f"{probe['probe_id']}: no release lead for kind={kind}")
        release = max(0.0, deadline - float(lead_by_kind[kind]))
        decision_deadline = deadline
    else:
        earliest = None
        decision_deadline = None
        context_end = float(probe["context_end_sec"])
        release = max(0.0, context_end - float(evaluation["negative_release_lead_sec"]))
        latest = context_end + float(evaluation["negative_observation_sec"])

    observe_end = latest + float(evaluation["post_window_tail_sec"])
    return ProbePlan(
        probe_id=probe["probe_id"],
        debate_id=probe["debate_id"],
        label=probe["label"],
        kind=kind,
        release_sec=round(release, 6),
        decision_earliest_sec=round(earliest, 6) if earliest is not None else None,
        decision_deadline_sec=round(decision_deadline, 6) if decision_deadline is not None else None,
        decision_latest_sec=round(latest, 6),
        observe_end_sec=round(observe_end, 6),
    )
