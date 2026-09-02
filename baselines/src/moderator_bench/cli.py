from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .audio import materialize_probe
from .config import read_config
from .data import Dataset
from .protocol import make_probe_plan


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--evaluation-config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "configs" / "evaluation.json",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="moderator-bench")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_parser = sub.add_parser("inspect", help="validate and summarize the dataset")
    _add_common(inspect_parser)

    show_parser = sub.add_parser("show-probe", help="show the exact probe input/output contract")
    _add_common(show_parser)
    show_parser.add_argument("--probe-id", required=True)

    prepare_parser = sub.add_parser("prepare", help="materialize duplex input streams for a probe")
    _add_common(prepare_parser)
    prepare_parser.add_argument("--probe-id", required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    dataset = Dataset.load(args.data_root)
    evaluation = read_config(args.evaluation_config)

    if args.command == "inspect":
        labels = Counter(probe["label"] for probe in dataset.probes.values())
        kinds = Counter(probe.get("kind", "negative") for probe in dataset.probes.values())
        print(json.dumps({
            "data_root": str(dataset.root),
            "debates": len(dataset.debates),
            "probes": len(dataset.probes),
            "labels": dict(sorted(labels.items())),
            "kinds": dict(sorted(kinds.items())),
        }, indent=2, ensure_ascii=False))
        return 0

    probe = dataset.probes[args.probe_id]
    plan = make_probe_plan(probe, evaluation)
    if args.command == "show-probe":
        print(json.dumps({
            "plan": plan.to_dict(),
            "rendered_system_prompt": dataset.rendered_prompt(plan.debate_id),
            "gold": {"label": probe["label"], "trigger": probe.get("trigger")},
        }, indent=2, ensure_ascii=False))
        return 0

    if args.command == "prepare":
        manifest = materialize_probe(dataset, probe, plan, args.output_dir)
        print(manifest)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
