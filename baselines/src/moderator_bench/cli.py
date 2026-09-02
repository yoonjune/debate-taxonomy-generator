from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .audio import materialize_probe
from .config import read_config
from .data import Dataset
from .protocol import make_probe_plan
from .run import run_probe
from .evaluation.aggregate import aggregate_scores
from .evaluation.temporal import score_generation


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

    run_parser = sub.add_parser("run", help="run one prepared probe")
    run_parser.add_argument("--input-manifest", type=Path, required=True)
    run_parser.add_argument("--model-config", type=Path, required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--fixture", choices=["oracle_tone", "silence"])

    score_parser = sub.add_parser("score", help="score timing and build a content-judge packet")
    score_parser.add_argument("--generation", type=Path, required=True)
    score_parser.add_argument(
        "--evaluation-config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "configs" / "evaluation.json",
    )
    score_parser.add_argument("--content-judgment", type=Path)

    aggregate_parser = sub.add_parser("aggregate", help="aggregate score JSON files")
    aggregate_parser.add_argument("scores", nargs="+", type=Path)

    args = parser.parse_args(argv)
    if args.command == "run":
        print(run_probe(args.input_manifest, args.model_config, args.output_dir, args.fixture))
        return 0
    if args.command == "score":
        print(score_generation(args.generation, args.evaluation_config, args.content_judgment))
        return 0
    if args.command == "aggregate":
        print(json.dumps(aggregate_scores(args.scores), indent=2, ensure_ascii=False))
        return 0

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
