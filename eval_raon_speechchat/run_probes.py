#!/usr/bin/env python3
# KHS: drives the official Raon-SpeechChat duplex path over a debate probe set.
#
# The official code is called and not modified. RaonPipeline.duplex already accepts a
# system prompt and a speaker reference wav, so the driver passes those and leaves every
# sampling parameter unset, which makes duplex() fall back to the values in the official
# config/duplex_infer.yaml. Each of those is exposed as a flag defaulting to None, so a
# later sweep is a command line and not an edit, and the effective value of everything
# is written to run_config.json beside the results.
#
# Timing comes from the frame log the official code writes. Each line carries the duplex
# state machine phase for that frame, SIL or SPEECH. The frame rate is read from the
# processor rather than hard coded, so a checkpoint with a different rate cannot
# silently shift every timestamp.
"""Run the Raon-SpeechChat full duplex path over a debate probe set.

  python run_probes.py --ckpt ckpt/Raon-SpeechChat-9B --limit 3
  python run_probes.py --ckpt ckpt/Raon-SpeechChat-9B
  python run_probes.py --ckpt ... --tag sil03 --sil-penalty 0.3
  python run_probes.py --ckpt ... --tag noref --no-reference --kinds negative
"""
import argparse
import ast
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from probe_data import ProbeSet                                   # noqa: E402

# [SIL] f=0 text=- out_rms=0.0000 in_rms=0.0123 ntok=2
FRAME_LINE = re.compile(
    r"^\[(?P<phase>\w+)\] f=(?P<f>\d+) text=(?P<text>.*?) "
    r"out_rms=(?P<out>[\d.eE+-]+) in_rms=(?P<in>[\d.eE+-]+) ntok=(?P<ntok>\d+)\s*$")

# every sampling knob duplex() accepts, with the official default it falls back to
OFFICIAL_DEFAULTS = {"temperature": 0.9, "top_p": 0.95, "top_k": 66,
                     "sil_penalty": 0.0, "bc_penalty": 0.0, "eos_penalty": 0.0,
                     "speak_first": False}


def parse_frame_log(path, frame_rate):
    """First SPEECH frame, and the text the model produced.

    Two independent signals are returned. The phase is the model's own declared
    interaction state and is what spoke_at uses. The first frame with output energy is
    recorded beside it so a disagreement between them is visible in the results rather
    than hidden.
    """
    first_speech, first_audio, said, n = None, None, [], 0
    with open(path) as f:
        for line in f:
            m = FRAME_LINE.match(line.rstrip("\n"))
            if not m:
                continue
            n += 1
            idx = int(m.group("f"))
            if m.group("phase") == "SPEECH" and first_speech is None:
                first_speech = idx
            if float(m.group("out")) > 0.0 and first_audio is None:
                first_audio = idx
            t = m.group("text")
            if t != "-":
                try:
                    said.append(ast.literal_eval(t))   # the log writes repr()
                except (ValueError, SyntaxError):
                    said.append(t)
    to_sec = lambda i: None if i is None else round(i / frame_rate, 3)
    # spoke_at is when the model DECIDED to speak, audible_at is when sound actually
    # leaves it. They can differ, and the scoring window is only a few seconds wide,
    # so both are reported rather than only the one that gets scored.
    return {"spoke_at": to_sec(first_speech), "first_speech_frame": first_speech,
            "audible_at": to_sec(first_audio), "first_audio_frame": first_audio,
            "text": "".join(said).strip() or None, "n_frames": n}


def sampling_kwargs(args):
    """Only the knobs actually set on the command line, so the rest stay official."""
    return {k: getattr(args, k) for k in OFFICIAL_DEFAULTS
            if getattr(args, k) is not None}


def run_one(pipe, item, args, out_dir, sampling):
    probe_dir = out_dir / "probes" / item["probe_id"]
    probe_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    kwargs = dict(sampling)
    kwargs["system_prompt"] = item["system_prompt"]        # KHS: benchmark prompt
    if item["reference_wav"] is not None:
        kwargs["speaker_audio"] = str(item["reference_wav"])
    summary = pipe.duplex(audio_input=pipe.load_audio(str(item["audio"])),
                          output_dir=str(probe_dir), **kwargs)

    frame_rate = float(pipe.processor.frame_rate)
    parsed = parse_frame_log(probe_dir / "frame_log.txt", frame_rate)

    if not args.keep_stereo:
        # the official code also writes a full length stereo mix of user and assistant,
        # about 14 MB per probe and not needed for scoring
        (probe_dir / "user_assistant.wav").unlink(missing_ok=True)

    return {"probe_id": item["probe_id"], "debate_id": item["debate_id"],
            "model": "Raon-SpeechChat-9B",
            "spoke": parsed["spoke_at"] is not None, "spoke_at": parsed["spoke_at"],
            "audible_at": parsed["audible_at"],
            "first_speech_frame": parsed["first_speech_frame"],
            "first_audio_frame": parsed["first_audio_frame"], "text": parsed["text"],
            "frame_rate": frame_rate, "n_frames": parsed["n_frames"],
            "assistant_duration_sec": round(summary.get("assistant_duration_sec", 0.0), 3),
            "audio_seconds": round(summary.get("user_duration_sec", 0.0), 3),
            "wav": str((probe_dir / "assistant.wav").relative_to(out_dir)),
            "label": item["label"], "kind": item["kind"],
            "t_earliest": item["t_earliest"], "t_deadline": item["t_deadline"],
            "t_latest": item["t_latest"],
            "elapsed_s": round(time.time() - t0, 2)}


def parse_args():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=__doc__.splitlines()[0])
    g = ap.add_argument_group("model")
    g.add_argument("--ckpt", required=True, help="official Raon-SpeechChat-9B dir")
    g.add_argument("--dtype", default="bfloat16")
    g.add_argument("--attn", default="sdpa", choices=["sdpa", "eager", "fa"])

    g = ap.add_argument_group(
        "sampling. unset means the official config/duplex_infer.yaml value, shown below")
    g.add_argument("--temperature", type=float, default=None)
    g.add_argument("--top-p", type=float, default=None, dest="top_p")
    g.add_argument("--top-k", type=int, default=None, dest="top_k")
    g.add_argument("--sil-penalty", type=float, default=None, dest="sil_penalty",
                   help="raising it makes the model speak sooner and more often, which "
                        "trades the silence probes for the intervention ones")
    g.add_argument("--bc-penalty", type=float, default=None, dest="bc_penalty")
    g.add_argument("--eos-penalty", type=float, default=None, dest="eos_penalty")
    g.add_argument("--speak-first", action="store_const", const=True, default=None,
                   dest="speak_first")

    g = ap.add_argument_group("probe set, all overridable")
    g.add_argument("--data-sample", default=None, help="directory holding the probe set")
    g.add_argument("--probes", default=None)
    g.add_argument("--debates-file", default=None)
    g.add_argument("--system-prompt", default=None, help="prompt template to use instead")
    g.add_argument("--probe-audio", default=None, help="made by make_probe_audio.py")
    g.add_argument("--voices", default=None)
    g.add_argument("--no-reference", action="store_true",
                   help="do not condition on the moderator voice clip")

    g = ap.add_argument_group("selection")
    g.add_argument("--debates", nargs="*", default=None)
    g.add_argument("--probe-ids", nargs="*", default=None)
    g.add_argument("--labels", nargs="*", default=None, help="e.g. A4 A2-1 none")
    g.add_argument("--kinds", nargs="*", default=None,
                   help="clock, event, content, negative")
    g.add_argument("--limit", type=int, default=0, help="pilot on the first N probes")

    g = ap.add_argument_group("output")
    g.add_argument("--out", default="out", help="root for results")
    g.add_argument("--tag", default="default",
                   help="results go to <out>/<tag>, so settings do not collide")
    g.add_argument("--keep-stereo", action="store_true",
                   help="keep the official stereo mix, about 14 MB per probe")
    return ap.parse_args()


def main():
    args = parse_args()
    out_dir = pathlib.Path(args.out) / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    results = out_dir / "results.jsonl"

    ps = ProbeSet(args.data_sample, args.probes, args.debates_file,
                  args.system_prompt, args.probe_audio, args.voices)
    missing = ps.missing_audio()
    if missing:
        sys.exit(f"[run] {len(missing)} probe wavs missing under {ps.audio_dir}. "
                 f"Run: cd {ps.root} && python make_probe_audio.py")
    items = ps.items(args.debates, args.probe_ids, args.labels, args.kinds,
                     args.limit, not args.no_reference)

    sampling = sampling_kwargs(args)
    effective = {**OFFICIAL_DEFAULTS, **sampling}
    (out_dir / "run_config.json").write_text(json.dumps(
        {"model": "Raon-SpeechChat-9B", "args": vars(args),
         "sampling_effective": effective, "sampling_overridden": sampling,
         "probe_set": ps.describe(), "n_selected": len(items),
         "started": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1, default=str))

    done = set()
    if results.exists():
        for line in open(results):
            try:
                done.add(json.loads(line)["probe_id"])
            except Exception:
                continue
    todo = [i for i in items if i["probe_id"] not in done]
    print(f"[run] tag '{args.tag}': {len(items)} probes selected, {len(done)} done, "
          f"{len(todo)} to run  ->  {out_dir}")
    print(f"[run] sampling {effective}"
          + ("" if sampling else "  (all official)"))
    if not todo:
        return

    print(f"[run] loading {args.ckpt}")
    from transformers.dynamic_module_utils import get_class_from_dynamic_module
    RaonPipeline = get_class_from_dynamic_module("modeling_raon.RaonPipeline", args.ckpt)
    pipe = RaonPipeline(args.ckpt, device="cuda", dtype=args.dtype,
                        attn_implementation=args.attn)
    print(f"[run] pipeline ready, {pipe.processor.frame_rate} frames per second, "
          f"{pipe.processor.sampling_rate} Hz")

    from tqdm import tqdm
    bar = tqdm(todo, unit="probe", ncols=100, ascii=True)
    spoke = 0
    with open(results, "a") as f:
        for item in bar:
            row = run_one(pipe, item, args, out_dir, sampling)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            spoke += bool(row["spoke"])
            bar.set_postfix(spoke=spoke)
    print(f"[run] {spoke}/{len(todo)} spoke. wrote {results}")


if __name__ == "__main__":
    main()
