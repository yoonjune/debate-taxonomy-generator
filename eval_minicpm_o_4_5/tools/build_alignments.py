#!/usr/bin/env python3
# khs_claude_code: word level alignment of every moderator turn, cached once and reused.
#
# This is the input to the prefill schedule. To place a moderator turn into the
# assistant channel as if the model had produced it, we need to know when each word is
# spoken, and that is what a forced aligner gives. It runs as its own step for two
# reasons: it is deterministic, so it is wasteful to redo per run, and the aligner lives
# in a different environment from the speech model here.
#
# The audio comes from data_sample/audio/turns, not from the mix. Turn files hold the
# whole utterance with no other speaker over it, which is what alignment needs; the mix
# has the moderator overlapping a debater on purpose.
"""Align every moderator turn and cache the word times.

  python tools/build_alignments.py --out assets/alignments.json
  python tools/build_alignments.py --out assets/alignments.json --debates L000
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from probe_data import ProbeSet, find_data_sample                  # noqa: E402

# khs_claude_code: a repo id by default so this folder is self contained. Point
# --aligner at a local directory to run offline.
DEFAULT_ALIGNER = "Qwen/Qwen3-ForcedAligner-0.6B"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-sample", default=None)
    ap.add_argument("--out", default="assets/alignments.json")
    ap.add_argument("--aligner", default=DEFAULT_ALIGNER)
    ap.add_argument("--debates", nargs="*", default=None)
    ap.add_argument("--speakers", nargs="*", default=["MOD"],
                    help="which speakers to align. MOD is what prefill needs")
    args = ap.parse_args()

    import torch
    from qwen_asr import Qwen3ForcedAligner

    root = pathlib.Path(args.data_sample) if args.data_sample else find_data_sample()
    mixes = sorted((root / "audio/mix").glob("*.json"))
    if args.debates:
        keep = set(args.debates)
        mixes = [m for m in mixes if m.stem in keep]
    print(f"[align] {len(mixes)} debates from {root}")

    aligner = Qwen3ForcedAligner.from_pretrained(args.aligner, dtype=torch.bfloat16,
                                                 device_map="cuda:0")
    out, stats = {}, {"turns": 0, "aligned": 0, "words": 0, "failed": 0}
    for m in mixes:
        did = m.stem
        tl = json.load(open(m))
        for t in tl["turns"]:
            if t["speaker"] not in args.speakers:
                continue
            stats["turns"] += 1
            wav = root / "audio/turns" / f'{did}_{t["i"]:03d}.mp3'
            if not wav.exists():
                stats["failed"] += 1
                continue
            try:
                res = aligner.align(audio=str(wav), text=t["text"], language="English")
            except Exception as e:
                print(f"  {did}/{t['i']}: align failed {type(e).__name__}")
                stats["failed"] += 1
                continue
            aligned = res[0] if res else None
            if not aligned:
                stats["failed"] += 1
                continue
            words = []
            for w in aligned:
                txt = getattr(w, "text", None) or (w.get("text") if isinstance(w, dict) else None)
                s = getattr(w, "start_time", None)
                e = getattr(w, "end_time", None)
                if s is None and isinstance(w, dict):
                    s, e = w.get("start_time"), w.get("end_time")
                if txt is None or s is None:
                    continue
                words.append({"text": str(txt), "start": round(float(s), 3),
                              "end": round(float(e if e is not None else s), 3)})
            if not words:
                stats["failed"] += 1
                continue
            out[f"{did}/{t['i']}"] = {
                "debate_id": did, "turn": t["i"], "speaker": t["speaker"],
                "start_sec": t["start_sec"], "end_sec": t["end_sec"],
                "text": t["text"], "audio": str(wav.relative_to(root)), "words": words}
            stats["aligned"] += 1
            stats["words"] += len(words)

    p = pathlib.Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    # khs_claude_code: merge rather than replace. The shipped asset holds all 97 turns,
    # --out defaults to it, and the usage line shows --debates, so writing only what this
    # invocation produced would replace the asset with one debate and make every other
    # probe raise the missing alignment error, which itself tells the reader to run this
    # command again.
    if p.exists():
        try:
            kept = json.load(open(p)).get("turns", {})
            kept.update(out)
            print(f"[align] merged into {len(kept)} turns already in {p}")
            out = kept
        except (json.JSONDecodeError, OSError):
            pass
    json.dump({"aligner": args.aligner, "speakers": args.speakers,
               "note": "word times are relative to the start of the turn audio, and "
                       "start_sec puts the turn on the debate timeline",
               "turns": out}, open(p, "w"), indent=1)
    print(f"[align] {stats['aligned']}/{stats['turns']} turns, {stats['words']} words, "
          f"{stats['failed']} failed  ->  {p}")


if __name__ == "__main__":
    main()
