#!/usr/bin/env python3
"""Validate and run GPT-Live-first moderator duplex inference campaigns.

The control plane is provider-neutral; provider session code remains pinned and native.
No paid API or GPU inference occurs unless the matching confirmation flag is supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any


SCHEMA = "moderator-duplex-inference/v1"
SKILL_ROOT = Path(__file__).resolve().parents[1]
GPT_PROFILE_PATH = SKILL_ROOT / "references/gpt-live-canonical.json"
PROVIDERS = {"gpt-live", "gemini", "moshi"}


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def relative_or_absolute(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def resolve_campaign(value: str, workspace_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    return cwd_candidate if cwd_candidate.exists() else workspace_root / path


def output_state(path: Path) -> str:
    if not path.exists():
        return "PENDING"
    metadata = path / "generation.json"
    if not metadata.is_file():
        return "EXISTING_NONCOMPLETE"
    try:
        status = read_json(metadata).get("status")
    except (OSError, ValueError, TypeError):
        return "EXISTING_NONCOMPLETE"
    return "COMPLETE_EXISTING" if status == "COMPLETE" else "EXISTING_NONCOMPLETE"


def provider_name(campaign: dict[str, Any]) -> str:
    return campaign.get("provider", "gpt-live")


def check_hash(path: Path, expected: str, label: str) -> str:
    require(path.is_file(), f"Missing {label}: {path}")
    actual = sha256(path)
    require(actual == expected, f"Frozen {label} hash mismatch: {path}")
    return actual


def validate_zero_pcm_regions(source_path: Path, gap_path: Path) -> None:
    payload = read_json(gap_path)
    require(payload.get("sample_rate") == 24000, f"Gap sample rate mismatch: {gap_path}")
    gaps = payload.get("gaps")
    require(isinstance(gaps, list), f"Missing gaps list: {gap_path}")
    with wave.open(str(source_path), "rb") as source:
        require(source.getnchannels() == 1, f"GPT-Live source must be mono: {source_path}")
        require(source.getsampwidth() == 2, f"GPT-Live source must be PCM16: {source_path}")
        require(source.getframerate() == 24000, f"GPT-Live source must be 24 kHz: {source_path}")
        frames = source.getnframes()
        previous_end = 0
        seen: set[str] = set()
        for gap in gaps:
            start, end = gap.get("start_sample"), gap.get("end_sample")
            gap_id = gap.get("gap_id")
            require(isinstance(start, int) and isinstance(end, int), f"Invalid gap coordinates: {gap_path}")
            require(0 <= start < end <= frames and start >= previous_end, f"Invalid/overlapping gap: {gap_path}")
            require(isinstance(gap_id, str) and gap_id not in seen, f"Invalid/duplicate gap ID: {gap_path}")
            source.setpos(start)
            require(not any(source.readframes(end - start)), f"Registered gap is not exact zero: {gap_id}")
            previous_end = end
            seen.add(gap_id)


def gpt_output_dir(root: Path, run: dict[str, Any]) -> Path:
    return resolve(root, run["output_dir"])


def gemini_output_dir(root: Path, plan: dict[str, Any], run: dict[str, Any]) -> Path:
    if run.get("output_dir"):
        return resolve(root, run["output_dir"])
    base = resolve(root, plan.get("output_root", "reports/gemini-runs"))
    return base / run["condition"] / f"r{run['repeat']}" / run["debate_id"]


def remap_moshi_path(root: Path, plan: dict[str, Any], value: str) -> Path:
    original = Path(value)
    direct = original if original.is_absolute() else root / original
    if direct.exists():
        return direct
    for mapping in plan.get("path_remap", []):
        source_prefix = Path(mapping["from"])
        try:
            suffix = original.relative_to(source_prefix)
        except ValueError:
            continue
        candidate = resolve(root, mapping["to"]) / suffix
        if candidate.exists():
            return candidate
    return direct


def validate_gpt_plan(plan: dict[str, Any], root: Path, profile: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("model", "endpoint", "audio_format", "frame_ms", "concurrency", "tail_sec"):
        require(plan.get(key) == profile[key], f"GPT-Live canonical {key} mismatch")
    require(plan.get("start_cue", {}).get("text") == profile["start_cue_text"], "GPT-Live start cue must occur once with frozen text")
    require(plan.get("input_controller") == profile["input_controller"], "GPT-Live input controller drift")
    require(plan.get("conditional_skip") == profile["conditional_skip"], "GPT-Live conditional skip drift")
    cue = resolve(root, plan["start_cue"]["audio"])
    check_hash(cue, plan["start_cue"]["sha256"], "start cue")
    runs = plan.get("runs")
    require(isinstance(runs, list) and runs, "GPT-Live plan has no runs")
    selected = plan.get("selected_debates")
    require(selected == [run.get("debate_id") for run in runs], "selected_debates must equal run order")
    seen_runs: set[str] = set()
    seen_outputs: set[str] = set()
    rows = []
    for run in runs:
        run_id = run.get("run_id")
        case_id = run.get("debate_id")
        require(isinstance(run_id, str) and run_id not in seen_runs, "Duplicate/invalid GPT-Live run_id")
        require(isinstance(case_id, str) and case_id, f"Invalid debate_id: {run_id}")
        require(run.get("condition") == "B0_GAP_ONLY_GATE_ZERO_FILL_1000MS", f"Condition drift: {run_id}")
        source_dir = resolve(root, run["input_dir"])
        source = source_dir / "user.wav"
        prompt = source_dir / "system_prompt.txt"
        gap = resolve(root, run["conditional_gap_file"])
        check_hash(source, run["source_audio_sha256"], "source audio")
        check_hash(prompt, run["prompt_sha256"], "system prompt")
        check_hash(gap, run["conditional_gap_sha256"], "gap manifest")
        require(prompt.read_text().strip() != "", f"Empty prompt: {run_id}")
        trim = run.get("leading_trim_sample")
        require(trim == round(float(run.get("trim_leading_silence_sec", -1)) * 24000), f"Leading trim mismatch: {run_id}")
        validate_zero_pcm_regions(source, gap)
        destination = gpt_output_dir(root, run)
        require(str(destination.resolve()) not in seen_outputs, f"Duplicate output directory: {destination}")
        seen_runs.add(run_id)
        seen_outputs.add(str(destination.resolve()))
        rows.append({"run_id": run_id, "case_id": case_id, "run": run, "output_dir": destination})
    return rows


def validate_gemini_plan(plan: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    concurrency = int(plan.get("concurrency", 3))
    require(1 <= concurrency <= 3, "Gemini plan concurrency must be 1..3")
    require(float(plan.get("tail_sec", 15)) >= 0, "Gemini tail_sec must be nonnegative")
    runs = plan.get("runs")
    require(isinstance(runs, list) and runs, "Gemini plan has no runs")
    seen_runs: set[str] = set()
    seen_outputs: set[str] = set()
    rows = []
    for run in runs:
        run_id, case_id = run.get("run_id"), run.get("debate_id")
        require(isinstance(run_id, str) and run_id not in seen_runs, "Duplicate/invalid Gemini run_id")
        require(isinstance(case_id, str) and case_id, f"Invalid debate_id: {run_id}")
        source_dir = resolve(root, run["input_dir"])
        source, prompt = source_dir / "user.wav", source_dir / "system_prompt.txt"
        require(source.is_file() and prompt.is_file() and prompt.read_text().strip(), f"Missing Gemini input: {run_id}")
        if run.get("source_audio_sha256"):
            check_hash(source, run["source_audio_sha256"], "source audio")
        if run.get("prompt_sha256"):
            check_hash(prompt, run["prompt_sha256"], "system prompt")
        if run.get("conditional_gap_file"):
            gap = resolve(root, run["conditional_gap_file"])
            check_hash(gap, run["conditional_gap_sha256"], "gap manifest")
        destination = gemini_output_dir(root, plan, run)
        require(str(destination.resolve()) not in seen_outputs, f"Duplicate output directory: {destination}")
        seen_runs.add(run_id)
        seen_outputs.add(str(destination.resolve()))
        rows.append({"run_id": run_id, "case_id": case_id, "run": run, "output_dir": destination})
    return rows


def validate_moshi_plan(plan: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    require(plan.get("schema_version") == "moderator-duplex-moshi/v1", "Invalid Moshi plan schema")
    require(plan.get("model") in {"base", "rl"}, "Moshi model must be base or rl")
    require(plan.get("concurrency") == 1, "Moshi concurrency must be one")
    prepared = resolve(root, plan["prepared_dir"])
    output = resolve(root, plan["output_dir"])
    index_path = prepared / "index.json"
    require(index_path.is_file(), f"Missing Moshi prepared index: {index_path}")
    mappings = plan.get("path_remap", [])
    require(isinstance(mappings, list), "Moshi path_remap must be a list")
    for mapping in mappings:
        require(isinstance(mapping, dict) and isinstance(mapping.get("from"), str) and isinstance(mapping.get("to"), str), "Invalid Moshi path_remap")
    manifests = [remap_moshi_path(root, plan, value) for value in read_json(index_path)]
    by_case = {path.parent.name: path for path in manifests}
    selected = plan.get("selected_debates")
    require(isinstance(selected, list) and selected, "Moshi selected_debates is empty")
    require(len(selected) == len(set(selected)), "Duplicate Moshi debate ID")
    rows = []
    for case_id in selected:
        require(case_id in by_case and by_case[case_id].is_file(), f"Missing Moshi input manifest: {case_id}")
        manifest = read_json(by_case[case_id])
        resolved_manifest = dict(manifest)
        for field in ("user_audio", "system_prompt", "voice"):
            resolved = remap_moshi_path(root, plan, manifest[field])
            require(resolved.is_file(), f"Missing remapped Moshi {field}: {case_id}: {resolved}")
            resolved_manifest[field] = str(resolved.resolve())
        hashes = manifest.get("hashes", {})
        for field, hash_key in (("user_audio", "user"), ("system_prompt", "prompt"), ("voice", "voice")):
            if hashes.get(hash_key):
                check_hash(Path(resolved_manifest[field]), hashes[hash_key], f"Moshi {field}")
        rows.append({
            "run_id": f"{plan['model']}:{case_id}",
            "case_id": case_id,
            "input_manifest": by_case[case_id],
            "resolved_manifest": resolved_manifest,
            "output_dir": output / case_id,
        })
    return rows


def preflight(campaign_path: Path, workspace_root: Path, only_cases: list[str] | None = None) -> dict[str, Any]:
    campaign = read_json(campaign_path)
    require(campaign.get("schema_version") == SCHEMA, f"schema_version must be {SCHEMA}")
    require(isinstance(campaign.get("campaign_id"), str) and campaign["campaign_id"], "Missing campaign_id")
    provider = provider_name(campaign)
    require(provider in PROVIDERS, f"Unknown provider: {provider}")
    adapter = campaign.get("adapter")
    require(isinstance(adapter, dict), "Missing adapter")
    module_path = resolve(workspace_root, adapter.get("module_path", ""))
    expected_module_hash = adapter.get("module_sha256")
    require(isinstance(expected_module_hash, str) and len(expected_module_hash) == 64, "adapter.module_sha256 is required")
    actual_module_hash = check_hash(module_path, expected_module_hash, "adapter module")
    execution = campaign.get("execution")
    require(isinstance(execution, dict), "Missing execution contract")
    require(execution.get("no_retry") is True, "execution.no_retry must be true")
    require(execution.get("skip_complete") is True, "execution.skip_complete must be true")
    concurrency = execution.get("concurrency")
    require(isinstance(concurrency, int), "execution.concurrency must be an integer")
    if provider in {"gpt-live", "moshi"}:
        require(concurrency == 1, f"{provider} concurrency must be one")
    else:
        require(1 <= concurrency <= 3, "Gemini concurrency must be 1..3")
    profile = read_json(GPT_PROFILE_PATH) if provider == "gpt-live" else None
    if profile:
        require(adapter.get("profile") == profile["profile"], "GPT-Live canonical profile mismatch")
        require(adapter.get("module_path") == profile["canonical_adapter_path"], "GPT-Live adapter path mismatch")
        require(actual_module_hash == profile["canonical_adapter_sha256"], "GPT-Live canonical adapter SHA mismatch")
    jobs = campaign.get("jobs")
    require(isinstance(jobs, list) and jobs, "Campaign has no jobs")
    work_items = []
    seen_jobs: set[str] = set()
    seen_work: set[str] = set()
    plan_rows = []
    for job_index, job in enumerate(jobs):
        job_id = job.get("job_id")
        require(isinstance(job_id, str) and job_id and job_id not in seen_jobs, "Duplicate/invalid job_id")
        seen_jobs.add(job_id)
        plan_path = resolve(workspace_root, job.get("plan_path", ""))
        expected_plan_hash = job.get("plan_sha256")
        require(isinstance(expected_plan_hash, str) and len(expected_plan_hash) == 64, f"Missing plan_sha256: {job_id}")
        actual_plan_hash = check_hash(plan_path, expected_plan_hash, "plan")
        plan = read_json(plan_path)
        if provider == "gpt-live":
            rows = validate_gpt_plan(plan, workspace_root, profile)
        elif provider == "gemini":
            rows = validate_gemini_plan(plan, workspace_root)
        else:
            rows = validate_moshi_plan(plan, workspace_root)
        plan_rows.append({"job_id": job_id, "plan_path": plan_path, "plan_sha256": actual_plan_hash, "plan": plan})
        for row in rows:
            work_id = f"{job_id}:{row['run_id']}"
            require(work_id not in seen_work, f"Duplicate work ID: {work_id}")
            seen_work.add(work_id)
            row.update(job_id=job_id, job_index=job_index, work_id=work_id, state=output_state(row["output_dir"]))
            work_items.append(row)
    if only_cases:
        requested = set(only_cases)
        selected = [row for row in work_items if row["case_id"] in requested or row["run_id"] in requested or row["work_id"] in requested]
        matched = {value for value in requested if any(value in {row["case_id"], row["run_id"], row["work_id"]} for row in work_items)}
        require(matched == requested, f"Unknown --only-case values: {sorted(requested - matched)}")
        work_items = selected
    require(work_items, "No cases selected")
    return {
        "campaign": campaign,
        "campaign_path": campaign_path,
        "workspace_root": workspace_root,
        "provider": provider,
        "profile": adapter.get("profile"),
        "adapter_path": module_path,
        "adapter_sha256": actual_module_hash,
        "plans": plan_rows,
        "items": work_items,
        "concurrency": concurrency,
    }


def public_preflight(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "campaign_id": state["campaign"]["campaign_id"],
        "provider": state["provider"],
        "profile": state["profile"],
        "adapter": relative_or_absolute(state["workspace_root"], state["adapter_path"]),
        "adapter_sha256": state["adapter_sha256"],
        "concurrency": state["concurrency"],
        "network_or_gpu_used": False,
        "cases": [
            {
                "work_id": row["work_id"],
                "case_id": row["case_id"],
                "run_id": row["run_id"],
                "state": row["state"],
                "output_dir": relative_or_absolute(state["workspace_root"], row["output_dir"]),
            }
            for row in state["items"]
        ],
    }


def load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("moderator_duplex_provider", path)
    require(spec is not None and spec.loader is not None, f"Cannot load adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_item(state: dict[str, Any], work_id: str) -> dict[str, Any]:
    matches = [row for row in state["items"] if row["work_id"] == work_id]
    require(len(matches) == 1, f"Unknown worker ID: {work_id}")
    return matches[0]


def run_worker(state: dict[str, Any], work_id: str, billing: str | None, gpu_confirmed: bool) -> int:
    item = find_item(state, work_id)
    require(item["state"] == "PENDING", f"Worker output is not unused: {item['output_dir']}")
    plan_row = state["plans"][item["job_index"]]
    plan = plan_row["plan"]
    module = load_adapter(state["adapter_path"])
    if state["provider"] == "gpt-live":
        require(billing == "paid-authorized", "GPT-Live requires --billing-confirmed paid-authorized")
        ok = asyncio.run(module.run_session(plan, item["run"], plan_row["plan_sha256"]))
        return 0 if ok else 1
    if state["provider"] == "gemini":
        require(billing in {"free", "paid-authorized"}, "Gemini requires --billing-confirmed")
        ok = asyncio.run(module.run_session(plan, item["run"], billing, plan_row["plan_sha256"]))
        return 0 if ok else 1
    require(gpu_confirmed, "Moshi requires --gpu-confirmed")
    with tempfile.TemporaryDirectory(prefix="moderator-moshi-resolved-") as temporary:
        prepared = Path(temporary)
        manifest_path = prepared / item["case_id"] / "input.json"
        write_json(manifest_path, item["resolved_manifest"])
        write_json(prepared / "index.json", [str(manifest_path.resolve())])
        module.run(
            prepared,
            resolve(state["workspace_root"], plan["output_dir"]),
            plan["model"],
            [item["case_id"]],
        )
    return 0 if output_state(item["output_dir"]) == "COMPLETE_EXISTING" else 1


def normalized_row(state: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    root, output = state["workspace_root"], row["output_dir"]
    artifacts: dict[str, str | None] = {
        "generation": relative_or_absolute(root, output / "generation.json") if (output / "generation.json").is_file() else None,
        "input_audio": None,
        "model_audio": None,
        "stereo_audio": None,
        "transcript": None,
    }
    if state["provider"] in {"gpt-live", "gemini"}:
        candidates = {
            "input_audio": output / "input.wav",
            "model_audio": output / "model_timeline.wav",
            "stereo_audio": output / "stereo.wav",
            "transcript": output / "transcripts.jsonl",
        }
    else:
        input_audio = Path(row["resolved_manifest"]["user_audio"])
        candidates = {
            "input_audio": input_audio,
            "model_audio": output / "output.wav",
            "stereo_audio": output / "stereo.wav",
            "transcript": output / "utterances.jsonl",
        }
    for key, path in candidates.items():
        if path.is_file():
            artifacts[key] = relative_or_absolute(root, path)
    return {
        "work_id": row["work_id"],
        "case_id": row["case_id"],
        "run_id": row["run_id"],
        "provider": state["provider"],
        "profile": state["profile"],
        "state": output_state(output),
        "output_dir": relative_or_absolute(root, output),
        "artifacts": artifacts,
    }


def collect_index(state: dict[str, Any]) -> Path:
    campaign = state["campaign"]
    destination = resolve(
        state["workspace_root"],
        campaign.get("index_path", f"reports/{campaign['campaign_id']}/campaign-index.json"),
    )
    payload = {
        "schema_version": SCHEMA,
        "campaign_id": campaign["campaign_id"],
        "provider": state["provider"],
        "profile": state["profile"],
        "adapter_sha256": state["adapter_sha256"],
        "human_gold": False,
        "rows": [normalized_row(state, row) for row in state["items"]],
    }
    write_json(destination, payload)
    return destination


async def run_queue(state: dict[str, Any], billing: str | None, gpu_confirmed: bool) -> int:
    blocked = [row for row in state["items"] if row["state"] == "EXISTING_NONCOMPLETE"]
    require(not blocked, "Existing noncomplete outputs block execution: " + ", ".join(row["work_id"] for row in blocked))
    pending = [row for row in state["items"] if row["state"] == "PENDING"]
    for row in state["items"]:
        if row["state"] == "COMPLETE_EXISTING":
            print(f"SKIP COMPLETE {row['work_id']}", flush=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    summary_dir = resolve(state["workspace_root"], state["campaign"].get("summary_dir", f"reports/{state['campaign']['campaign_id']}/executions"))
    summary_path = summary_dir / f"execution-{stamp}.json"
    summary = {"campaign_id": state["campaign"]["campaign_id"], "provider": state["provider"], "status": "RUNNING", "completed": [], "errors": [], "not_started": []}
    write_json(summary_path, summary)
    active: dict[asyncio.Task[int], tuple[dict[str, Any], asyncio.subprocess.Process]] = {}
    stopped = False
    while pending or active:
        while pending and not stopped and len(active) < state["concurrency"]:
            row = pending.pop(0)
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--workspace-root",
                str(state["workspace_root"]),
                "--campaign",
                str(state["campaign_path"]),
                "--worker",
                row["work_id"],
            ]
            if billing:
                command.extend(["--billing-confirmed", billing])
            if gpu_confirmed:
                command.append("--gpu-confirmed")
            process = await asyncio.create_subprocess_exec(*command)
            active[asyncio.create_task(process.wait())] = (row, process)
        if not active:
            break
        done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            row, _process = active.pop(task)
            code = task.result()
            summary["completed" if code == 0 else "errors"].append({"work_id": row["work_id"], "exit_code": code})
            if code:
                stopped = True
        write_json(summary_path, summary)
    summary.update(status="STOPPED_ERROR" if stopped else "COMPLETE", not_started=[row["work_id"] for row in pending])
    write_json(summary_path, summary)
    print(f"SUMMARY {summary_path}", flush=True)
    return 1 if stopped else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--only-case", action="append")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--collect-only", action="store_true")
    parser.add_argument("--billing-confirmed", choices=["free", "paid-authorized"])
    parser.add_argument("--gpu-confirmed", action="store_true")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.workspace_root.resolve()
    campaign_path = resolve_campaign(args.campaign, root).resolve()
    state = preflight(campaign_path, root, args.only_case)
    if args.worker:
        return run_worker(state, args.worker, args.billing_confirmed, args.gpu_confirmed)
    print(json.dumps(public_preflight(state), ensure_ascii=False, indent=2), flush=True)
    if args.collect_only:
        print(f"INDEX {collect_index(state)}", flush=True)
        return 0
    if not args.execute:
        return 0
    if state["provider"] == "gpt-live":
        require(args.billing_confirmed == "paid-authorized", "GPT-Live requires --billing-confirmed paid-authorized")
    elif state["provider"] == "gemini":
        require(args.billing_confirmed in {"free", "paid-authorized"}, "Gemini requires --billing-confirmed")
    else:
        require(args.gpu_confirmed, "Moshi requires --gpu-confirmed")
    code = asyncio.run(run_queue(state, args.billing_confirmed, args.gpu_confirmed))
    print(f"INDEX {collect_index(state)}", flush=True)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as error:
        print(f"CONTRACT_ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
