#!/usr/bin/env python3
# khs_claude_code: measures how far ahead of its own speech the model emits text.
#
# Why this exists. The technical report says Raon-SpeechChat is trained with "one-frame
# text lookahead ... so that speech semantic tokens are predicted conditioned on text
# generated one frame in advance", and that assistant text and speech are "aligned at
# the word level" with PAD filling the frames where no new text token starts. To build
# a teacher forced assistant history we have to place each word's text token on the
# right frame, and that is exactly the lookahead offset. The report states it for a
# training stage and does not say it holds at inference, so this measures it on the
# model's own output instead of assuming.
#
# How. The official frame log already carries everything needed, without touching
# official code. Each line gives the state machine phase and the number of tokens the
# frame appended, and the state machine emits two tokens for SIL and PAD and three for a
# text token, EPAD or BC, so the full per frame schedule can be reconstructed:
#
#     phase SIL    ntok 2                -> SIL
#     phase SPEECH ntok 2                -> PAD
#     phase SPEECH ntok 3, text printed  -> a real text token
#     phase SPEECH ntok 3, no text       -> EPAD
#
# assistant.wav is frame aligned, one frame of audio per input frame including the
# silent ones, so frame index times 80 ms is a position in that file. Force aligning a
# speech segment against its own text gives where each word is actually pronounced, and
# the difference between that and the frame its token was emitted on is the answer.
"""Measure the text to audio offset from a finished run.

  python tools/measure_text_audio_offset.py --run out/pilot
  python tools/measure_text_audio_offset.py --run out/pilot --probe L000_p02
"""
import argparse
import ast
import collections
import json
import pathlib
import re
import sys

FRAME_LINE = re.compile(
    r"^\[(?P<phase>\w+)\] f=(?P<f>\d+) text=(?P<text>.*?) "
    r"out_rms=(?P<out>[\d.eE+-]+) in_rms=(?P<in>[\d.eE+-]+) ntok=(?P<ntok>\d+)\s*$")
BACKCHANNEL_TOKEN = "<|audio_output_backchannel|>"
SIL_TOKEN = "<|audio_output_sil|>"


def read_schedule(path):
    """One entry per frame: (frame, kind, text). kind is SIL, PAD, EPAD, BC or TEXT."""
    out = []
    for line in open(path):
        m = FRAME_LINE.match(line.rstrip("\n"))
        if not m:
            continue
        f, phase, ntok = int(m.group("f")), m.group("phase"), int(m.group("ntok"))
        raw = m.group("text")
        text = ""
        if raw != "-":
            try:
                text = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                text = raw
        if phase == "SIL" and ntok == 2:
            kind = "SIL"
        elif phase == "SPEECH" and ntok == 2:
            kind = "PAD"
        elif BACKCHANNEL_TOKEN in text:
            kind = "BC"
        elif SIL_TOKEN in text:
            kind = "SIL"
        elif text:
            kind = "TEXT"
        else:
            kind = "EPAD"          # three tokens appended but nothing printable
        out.append((f, kind, text))
    return out


def speech_runs(schedule):
    """Contiguous stretches of the SPEECH phase, with the frames that carry text."""
    runs, cur = [], None
    for f, kind, text in schedule:
        if kind == "SIL":
            if cur:
                runs.append(cur)
                cur = None
            continue
        if cur is None:
            cur = {"start": f, "end": f, "tokens": []}
        cur["end"] = f
        if kind in ("TEXT", "BC"):
            cur["tokens"].append((f, text))
    if cur:
        runs.append(cur)
    return runs


def to_words(tokens):
    """Group token pieces into words, keeping the frame the word's first piece landed on.

    Sub word pieces continue the current word; a piece that starts with a space, or the
    first piece of the run, begins a new one. That is the same convention the aligner
    reports words in, so the two can be compared.
    """
    words = []
    for f, piece in tokens:
        if BACKCHANNEL_TOKEN in piece:
            piece = piece.replace(BACKCHANNEL_TOKEN, "")
        if not piece:
            continue
        if not words or piece[:1].isspace():
            words.append({"frame": f, "text": piece.strip()})
        else:
            words[-1]["text"] += piece
    return [w for w in words if w["text"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="a finished run directory, e.g. out/pilot")
    ap.add_argument("--probe", default=None, help="restrict to one probe id")
    ap.add_argument("--aligner", default="/gpfs/home1/gmltmd7/workspace/Cowork/"
                                         "samsung_mx/debate5min/models/Qwen3-ForcedAligner-0.6B")
    ap.add_argument("--frame-rate", type=float, default=12.5)
    ap.add_argument("--min-words", type=int, default=2,
                    help="skip a run shorter than this, alignment is unreliable there")
    ap.add_argument("--out", default=None, help="write the per word table as json")
    args = ap.parse_args()

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ForcedAligner

    run = pathlib.Path(args.run)
    probes = sorted((run / "probes").glob("*"))
    if args.probe:
        probes = [p for p in probes if p.name == args.probe]
    probes = [p for p in probes if (p / "frame_log.txt").exists()
              and (p / "assistant.wav").exists()]
    if not probes:
        sys.exit(f"[offset] no finished probes under {run}/probes")
    print(f"[offset] {len(probes)} probes")

    aligner = Qwen3ForcedAligner.from_pretrained(args.aligner, dtype=torch.bfloat16,
                                                 device_map="cuda:0")
    spf = None
    rows, skipped = [], collections.Counter()
    tmp = run / ".offset_tmp"
    tmp.mkdir(exist_ok=True)

    for pd in probes:
        sched = read_schedule(pd / "frame_log.txt")
        wav, sr = sf.read(str(pd / "assistant.wav"), dtype="float32")
        if spf is None:
            spf = int(round(sr / args.frame_rate))
            got, want = len(wav) / sr, len(sched) / args.frame_rate
            print(f"[offset] {sr} Hz, {spf} samples per frame; "
                  f"wav {got:.2f} s vs frames {want:.2f} s "
                  f"{'aligned' if abs(got - want) < 0.05 else 'NOT ALIGNED, stop'}")
            if abs(got - want) >= 0.05:
                sys.exit(1)

        for run_i, sp in enumerate(speech_runs(sched)):
            words = to_words(sp["tokens"])
            if len(words) < args.min_words:
                skipped["too short"] += 1
                continue
            a = wav[sp["start"] * spf: (sp["end"] + 1) * spf]
            if len(a) < spf * 2:
                skipped["no audio"] += 1
                continue
            clip = tmp / f"{pd.name}_{run_i}.wav"
            sf.write(str(clip), a, sr)
            text = " ".join(w["text"] for w in words)
            try:
                res = aligner.align(audio=str(clip), text=text, language="English")
            except Exception as e:
                skipped[f"align failed: {type(e).__name__}"] += 1
                clip.unlink(missing_ok=True)
                continue
            clip.unlink(missing_ok=True)
            aligned = res[0] if res else None
            if not aligned:
                skipped["aligner returned nothing"] += 1
                continue
            items = []
            for w in aligned:
                t = getattr(w, "text", None) or (w.get("text") if isinstance(w, dict) else None)
                s = getattr(w, "start_time", None)
                if s is None and isinstance(w, dict):
                    s = w.get("start_time")
                if t is None or s is None:
                    continue
                items.append((str(t).strip(), float(s)))
            if len(items) != len(words):
                skipped[f"word count {len(items)} vs {len(words)}"] += 1
                continue
            for (atext, astart), w in zip(items, words):
                audio_frame = sp["start"] + astart * args.frame_rate
                rows.append({"probe": pd.name, "run": run_i, "word": w["text"],
                             "aligned": atext,
                             "text_frame": w["frame"],
                             "audio_frame": round(audio_frame, 2),
                             "offset_frames": round(w["frame"] - audio_frame, 2)})

    for f in tmp.glob("*"):
        f.unlink(missing_ok=True)
    tmp.rmdir()

    if not rows:
        print("[offset] nothing measurable")
        for k, v in skipped.items():
            print(f"    skipped {v}: {k}")
        return

    offs = sorted(r["offset_frames"] for r in rows)
    q = lambda p: offs[min(len(offs) - 1, int(len(offs) * p))]
    ms = 1000.0 / args.frame_rate
    print(f"\n[offset] {len(rows)} words measured over "
          f"{len({(r['probe'], r['run']) for r in rows})} speech runs")
    for k, v in skipped.items():
        print(f"    skipped {v}: {k}")
    print(f"\n  text frame minus audio frame")
    print(f"    p10 {q(.10):+6.2f}   p25 {q(.25):+6.2f}   median {q(.50):+6.2f}   "
          f"p75 {q(.75):+6.2f}   p90 {q(.90):+6.2f}   frames")
    print(f"    median in time {q(.50) * ms:+.0f} ms   "
          f"(one frame is {ms:.0f} ms)")
    hist = collections.Counter(int(round(o)) for o in offs)
    print(f"\n  rounded to whole frames")
    for k in sorted(hist):
        bar = "#" * max(1, int(40 * hist[k] / max(hist.values())))
        print(f"    {k:+3d} frames {hist[k]:5}  {bar}")

    if args.out:
        json.dump({"frame_rate": args.frame_rate, "n_words": len(rows),
                   "median_offset_frames": q(.50),
                   "histogram": {str(k): v for k, v in sorted(hist.items())},
                   "words": rows}, open(args.out, "w"), indent=1)
        print(f"\n[offset] wrote {args.out}")


if __name__ == "__main__":
    main()
