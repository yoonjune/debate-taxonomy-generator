from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .alignment import align_moderator_turns
from .audio import materialize_probe
from .batch import prepare_batch, run_batch, score_batch
from .config import read_config
from .data import Dataset
from .evaluation.aggregate import aggregate_scores
from .evaluation.temporal import score_generation
from .protocol import make_probe_plan
from .run import run_probe


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

    prepare_batch_parser = sub.add_parser("prepare-batch", help="prepare multiple probe inputs")
    _add_common(prepare_batch_parser)
    prepare_batch_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_batch_parser.add_argument("--debate-id")
    prepare_batch_parser.add_argument("--label")
    prepare_batch_parser.add_argument("--limit", type=int)

    align_parser = sub.add_parser(
        "align-moderator", help="align isolated moderator turns with Qwen3 ForcedAligner"
    )
    align_parser.add_argument("--data-root", type=Path, required=True)
    align_parser.add_argument(
        "--aligner-config",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "configs"
        / "aligners"
        / "qwen3_forced_aligner.json",
    )
    align_parser.add_argument("--output-dir", type=Path, required=True)
    align_parser.add_argument("--debate-id")
    align_parser.add_argument("--limit", type=int)

    run_batch_parser = sub.add_parser("run-batch", help="run prepared probes with one loaded model")
    run_batch_parser.add_argument("--batch-input", type=Path, required=True)
    run_batch_parser.add_argument("--model-config", type=Path, required=True)
    run_batch_parser.add_argument("--output-dir", type=Path, required=True)
    run_batch_parser.add_argument("--fixture", choices=["oracle_tone", "silence"])

    score_batch_parser = sub.add_parser("score-batch", help="score every successful batch output")
    score_batch_parser.add_argument("--batch-run", type=Path, required=True)
    score_batch_parser.add_argument(
        "--evaluation-config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "configs" / "evaluation.json",
    )

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
    if args.command == "run-batch":
        print(run_batch(args.batch_input, args.model_config, args.output_dir, args.fixture))
        return 0
    if args.command == "score-batch":
        print(score_batch(args.batch_run, args.evaluation_config))
        return 0
    if args.command == "align-moderator":
        print(align_moderator_turns(
            args.data_root,
            args.aligner_config,
            args.output_dir,
            debate_id=args.debate_id,
            limit=args.limit,
        ))
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
    if args.command == "prepare-batch":
        print(prepare_batch(
            args.data_root,
            args.evaluation_config,
            args.output_dir,
            debate_id=args.debate_id,
            label=args.label,
            limit=args.limit,
        ))
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
