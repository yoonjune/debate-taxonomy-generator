#!/usr/bin/env python3
# KHS: measures which chunk a word's text is emitted in against the chunk its audio
# actually starts in.
#
# Why this exists. MiniCPM-o 4.5 places text with TAIL, Time Aligned Interleaving. The
# technical report describes the training supervision as "collecting the start and end
# times of each text token. Tokens whose start times fall into [(k-1)t, kt), together
# with their corresponding speech tokens, are assigned to the k-th Omni-Flow chunk",
# with a bounded look ahead that defers "the speech tokens of the last few text tokens
# in chunk k to chunk k+1". To build a teacher forced assistant history we have to put
# each word in the right chunk, so the relation has to be known rather than assumed. The
# report gives the rule for training and quantifies neither the look ahead nor what the
# released model does at inference, so this measures it on the model's own output.
#
# How. The run records, per speech segment, which chunk emitted which text and which
# chunk produced how many audio samples. Force aligning the segment's audio against its
# own text gives where each word is really pronounced, and converting that back to a
# chunk index gives the difference.
"""Measure the text to audio offset from a finished run.

  python tools/measure_text_audio_offset.py --run out/pilot
"""
import argparse
import collections
import json
import pathlib
import sys


def words_from_chunks(text_chunks):
    """Group the per chunk text pieces into words, keeping the chunk of the first piece."""
    words = []
    for idx, piece in text_chunks:
        for part in _split_keep(piece):
            if not part.strip():
                continue
            if not words or part[:1].isspace():
                words.append({"chunk": idx, "text": part.strip()})
            else:
                words[-1]["text"] += part
    return [w for w in words if w["text"]]


def _split_keep(piece):
    """Split on spaces but keep the leading space with each part, so a word boundary is
    still visible after the split."""
    out, cur = [], ""
    for ch in piece:
        if ch.isspace() and cur:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--probe", default=None)
    ap.add_argument("--aligner", default="/gpfs/home1/gmltmd7/workspace/Cowork/"
                                         "samsung_mx/debate5min/models/Qwen3-ForcedAligner-0.6B")
    ap.add_argument("--min-words", type=int, default=2)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ForcedAligner

    run = pathlib.Path(args.run)
    rows_in = [json.loads(l) for l in open(run / "results.jsonl")]
    if args.probe:
        rows_in = [r for r in rows_in if r["probe_id"] == args.probe]
    rows_in = [r for r in rows_in if r.get("wav") and r.get("segments")]
    if not rows_in:
        sys.exit(f"[offset] nothing with audio under {run}")
    print(f"[offset] {len(rows_in)} probes")

    aligner = Qwen3ForcedAligner.from_pretrained(args.aligner, dtype=torch.bfloat16,
                                                 device_map="cuda:0")
    rows, skipped = [], collections.Counter()
    tmp = run / ".offset_tmp"
    tmp.mkdir(exist_ok=True)

    for r in rows_in:
        wav, sr = sf.read(str(run / r["wav"]), dtype="float32")
        chunk_s = r["chunk_seconds"]
        cursor = 0
        for si, seg in enumerate(r["segments"]):
            n = sum(k for _, k in seg.get("audio_chunks", []))
            a = wav[cursor: cursor + n]
            cursor += n
            words = words_from_chunks(seg.get("text_chunks", []))
            if len(words) < args.min_words:
                skipped["too short"] += 1
                continue
            if len(a) < sr // 2:
                skipped["no audio"] += 1
                continue
            # the first audio sample of this segment belongs to the first chunk that
            # produced audio for it
            first_chunk = seg["audio_chunks"][0][0]
            clip = tmp / f'{r["probe_id"]}_{si}.wav'
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
                if t is not None and s is not None:
                    items.append((str(t).strip(), float(s)))
            if len(items) != len(words):
                skipped[f"word count {len(items)} vs {len(words)}"] += 1
                continue
            for (atext, astart), w in zip(items, words):
                audio_chunk = first_chunk + astart / chunk_s
                rows.append({"probe": r["probe_id"], "segment": si, "word": w["text"],
                             "text_chunk": w["chunk"],
                             "audio_chunk": round(audio_chunk, 3),
                             "offset_chunks": round(w["chunk"] - audio_chunk, 3),
                             "offset_ms": round((w["chunk"] - audio_chunk) * chunk_s * 1000)})

    for f in tmp.glob("*"):
        f.unlink(missing_ok=True)
    tmp.rmdir()

    if not rows:
        print("[offset] nothing measurable")
        for k, v in skipped.items():
            print(f"    skipped {v}: {k}")
        return

    offs = sorted(r["offset_ms"] for r in rows)
    q = lambda p: offs[min(len(offs) - 1, int(len(offs) * p))]
    print(f"\n[offset] {len(rows)} words over "
          f"{len({(r['probe'], r['segment']) for r in rows})} segments")
    for k, v in skipped.items():
        print(f"    skipped {v}: {k}")
    print(f"\n  text chunk minus audio position, in milliseconds")
    print(f"    p10 {q(.10):+6}   p25 {q(.25):+6}   median {q(.50):+6}   "
          f"p75 {q(.75):+6}   p90 {q(.90):+6}")
    hist = collections.Counter(int(round(r["offset_chunks"])) for r in rows)
    print(f"\n  rounded to whole chunks")
    for k in sorted(hist):
        print(f"    {k:+3d}  {hist[k]:5}  {'#' * max(1, int(40*hist[k]/max(hist.values())))}")
    if args.out:
        json.dump({"n_words": len(rows), "median_offset_ms": q(.50), "words": rows},
                  open(args.out, "w"), indent=1)
        print(f"\n[offset] wrote {args.out}")


if __name__ == "__main__":
    main()
