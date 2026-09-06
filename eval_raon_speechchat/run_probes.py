#!/usr/bin/env python3
# KHS: drives the official Raon-SpeechChat duplex path over the debate probes.
#
# The official code is called and not modified. RaonPipeline.duplex already accepts a
# system prompt string and a speaker reference wav, and every sampling parameter is left
# at the value in the official config/duplex_infer.yaml, so this file passes only the
# two things the benchmark defines and nothing else:
#
#   system_prompt   data_sample/system_prompt.md with its four placeholders substituted
#   speaker_audio   the clip the moderator voice in this debate was cloned from
#
# Timing comes from the frame log the official code writes. Each line carries the
# duplex state machine phase for that frame, SIL or SPEECH, and the model runs at
# 12.5 frames per second, so the first SPEECH frame gives spoke_at to within 80 ms.
# The frame rate is read from the processor rather than hard coded, so a checkpoint
# with a different rate cannot silently shift every timestamp.
"""Run the Raon-SpeechChat full duplex path over data_sample probes.

  python run_probes.py --ckpt ckpt/Raon-SpeechChat-9B --out out/raon_speechchat
  python run_probes.py --ckpt ... --limit 3            # short pilot first
  python run_probes.py --ckpt ... --debates L000 L001  # one or two debates
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


def parse_frame_log(path, frame_rate):
    """First SPEECH frame, and the text the model produced.

    Two independent signals are returned. The phase is the model's own declared
    interaction state and is what spoke_at uses. The output audio energy is recorded
    beside it so that a disagreement between the two is visible in the results rather
    than hidden: they should agree, and if they ever do not, the timing needs another
    look before the numbers are used.
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
    return {
        "spoke_at": to_sec(first_speech),
        "first_speech_frame": first_speech,
        "first_audio_at": to_sec(first_audio),
        "first_audio_frame": first_audio,
        "text": "".join(said).strip() or None,
        "n_frames": n,
    }


def run_one(pipe, item, args, out_dir):
    probe_dir = out_dir / "probes" / item["probe_id"]
    probe_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    audio = pipe.load_audio(str(item["audio"]))
    kwargs = {"system_prompt": item["system_prompt"]}      # KHS: benchmark prompt
    if item["reference_wav"] is not None:
        kwargs["speaker_audio"] = str(item["reference_wav"])
    summary = pipe.duplex(audio_input=audio, output_dir=str(probe_dir), **kwargs)

    frame_rate = float(pipe.processor.frame_rate)
    parsed = parse_frame_log(probe_dir / "frame_log.txt", frame_rate)

    if not args.keep_stereo:
        # the official code also writes a full length stereo mix of user and assistant,
        # which is about 14 MB per probe and is not needed for scoring
        (probe_dir / "user_assistant.wav").unlink(missing_ok=True)

    row = {
        "probe_id": item["probe_id"],
        "debate_id": item["debate_id"],
        "model": "Raon-SpeechChat-9B",
        "spoke": parsed["spoke_at"] is not None,
        "spoke_at": parsed["spoke_at"],
        "first_speech_frame": parsed["first_speech_frame"],
        "first_audio_at": parsed["first_audio_at"],
        "text": parsed["text"],
        "frame_rate": frame_rate,
        "n_frames": parsed["n_frames"],
        "assistant_duration_sec": round(summary.get("assistant_duration_sec", 0.0), 3),
        "audio_seconds": round(summary.get("user_duration_sec", 0.0), 3),
        "wav": str((probe_dir / "assistant.wav").relative_to(out_dir)),
        "label": item["label"],
        "kind": item["kind"],
        "t_earliest": item["t_earliest"],
        "t_deadline": item["t_deadline"],
        "t_latest": item["t_latest"],
        "elapsed_s": round(time.time() - t0, 2),
    }
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True, help="official Raon-SpeechChat-9B dir")
    ap.add_argument("--out", default="out/raon_speechchat")
    ap.add_argument("--data-sample", default=None)
    ap.add_argument("--probe-audio", default=None,
                    help="default data_sample/probe_audio, made by make_probe_audio.py")
    ap.add_argument("--debates", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=0, help="pilot on the first N probes")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--attn", default="sdpa", choices=["sdpa", "eager", "fa"])
    ap.add_argument("--keep-stereo", action="store_true",
                    help="keep the official stereo mix, about 14 MB per probe")
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = out_dir / "results.jsonl"

    ps = ProbeSet(args.data_sample, args.probe_audio)
    missing = ps.missing_audio()
    if missing:
        sys.exit(f"[run] {len(missing)} probe wavs missing under {ps.audio_dir}. "
                 f"Run: cd {ps.root} && python make_probe_audio.py")
    items = ps.items(args.debates, args.limit)

    done = set()
    if results.exists():
        for line in open(results):
            try:
                done.add(json.loads(line)["probe_id"])
            except Exception:
                continue
    todo = [i for i in items if i["probe_id"] not in done]
    print(f"[run] {len(items)} probes selected, {len(done)} already done, "
          f"{len(todo)} to run")
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
            row = run_one(pipe, item, args, out_dir)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            spoke += bool(row["spoke"])
            bar.set_postfix(spoke=spoke)
    print(f"[run] wrote {results}")


if __name__ == "__main__":
    main()
