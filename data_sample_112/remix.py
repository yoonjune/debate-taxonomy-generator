#!/usr/bin/env python3
"""Rebuild a debate's audio from its per-turn files and the timeline. This is the mixing recipe.

  python3 remix.py L000                      # full debate (all three voices) -> L000_remix.wav
  python3 remix.py L000 --debaters-only      # the model's input channel: PRO/CON only, MOD left silent
  python3 remix.py --all --debaters-only --out inputs/   # every debate

Recipe (what audio/mix/<id>.json encodes)
  - place audio/turns/<id>_<i>.mp3 so that it starts at turn["start_sec"]
  - keep it only up to turn["end_sec"]; if the file is longer, that is a cut (overrun stopped by the
    moderator, or a surplus crossfire turn): truncate there with a 0.25 s fade-out
  - turns marked "overlap": true start while the previous speaker is still talking (ten-second cue laid
    over the speaker, moderator cutting in, a debater interrupting); nothing is moved to avoid it
  - sum everything, peak-normalise to 0.99 if needed. Mono, 24 kHz.

The moderator's turns are the reference answers. --debaters-only drops them and leaves their time
as silence, which is exactly what the model under test hears.
"""
import argparse, json
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
FADE = 0.25


def read_audio(path):
    try:
        w, sr = sf.read(str(path), dtype="float32")
    except Exception:
        # mp3 fallback via ffmpeg (soundfile without mp3 support)
        import subprocess, io
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "wav", "-ac", "1", "-"],
                             capture_output=True, check=True).stdout
        w, sr = sf.read(io.BytesIO(raw), dtype="float32")
    if w.ndim > 1:
        w = w.mean(axis=1)
    return w, sr


def remix(debate_id, debaters_only=False, turns_dir=None, mix_dir=None):
    turns_dir = turns_dir or HERE / "audio/turns"
    mix_dir = mix_dir or HERE / "audio/mix"
    tl = json.load(open(mix_dir / f"{debate_id}.json"))["turns"]
    total = max(t["end_sec"] for t in tl)
    sr = None
    buf = None
    for t in tl:
        if debaters_only and t["speaker"] == "MOD":
            continue
        f = None
        for ext in (".mp3", ".wav"):
            cand = turns_dir / f'{debate_id}_{t["i"]:03d}{ext}'
            if cand.exists():
                f = cand
                break
        if f is None:
            continue
        w, s = read_audio(f)
        if sr is None:
            sr = s
            buf = np.zeros(int((total + 1.0) * sr), dtype=np.float32)
        elif s != sr:
            raise SystemExit(f"sample rate mismatch in {f}: {s} vs {sr}")
        keep = int(round((t["end_sec"] - t["start_sec"]) * sr))
        if len(w) > keep + 1:                       # cut turn: truncate with a fade
            w = w[:keep].copy()
            nf = int(FADE * sr)
            if nf and len(w) > nf:
                w[-nf:] *= np.linspace(1.0, 0.0, nf, dtype=np.float32)
        i0 = int(round(t["start_sec"] * sr))
        n = min(len(w), len(buf) - i0)
        if n > 0:
            buf[i0:i0 + n] += w[:n]
    buf = buf[: int(round(total * sr)) + 1]
    pk = float(np.abs(buf).max()) if len(buf) else 0.0
    if pk > 0.99:
        buf *= 0.99 / pk
    return buf, sr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="debate ids, e.g. L000")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--debaters-only", action="store_true", help="model input: PRO/CON only")
    ap.add_argument("--out", default=".", help="output folder")
    a = ap.parse_args()
    ids = a.ids
    if a.all:
        ids = sorted(p.stem for p in (HERE / "audio/mix").glob("L*.json"))
    if not ids:
        ap.error("give debate ids or --all")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for did in ids:
        w, sr = remix(did, a.debaters_only)
        tag = "_input" if a.debaters_only else "_remix"
        sf.write(out / f"{did}{tag}.wav", w, sr)
        print(f"{did}: {len(w)/sr:.1f}s -> {out / (did + tag + '.wav')}")


if __name__ == "__main__":
    main()
