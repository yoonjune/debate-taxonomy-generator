#!/usr/bin/env python3
"""Trivial baselines as utterance logs, for score_freerun.py.

  python3 baselines.py --probes probes.jsonl --debates debates.jsonl --out baselines/
    baselines/silent.jsonl        never speaks
    baselines/every_trigger.jsonl speaks "…" at every trigger deadline (oracle timing, empty content)
    baselines/on_pause.jsonl      speaks 0.3 s after every debater turn ends (a pause-triggered talker)
"""
import argparse, json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probes", default="probes.jsonl"); ap.add_argument("--debates", default="debates.jsonl")
    ap.add_argument("--out", default="baselines")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(exist_ok=True)
    P = [json.loads(l) for l in open(a.probes) if l.strip()]
    D = [json.loads(l) for l in open(a.debates) if l.strip()]
    (out / "silent.jsonl").write_text("")
    every = [{"debate_id": p["debate_id"], "start_sec": p["t_deadline"], "end_sec": p["t_deadline"] + 1.5, "text": "..."} for p in P]
    (out / "every_trigger.jsonl").write_text("\n".join(json.dumps(u) for u in every))
    pause = []
    for d in D:
        tl = {t["i"]: t for t in json.load(open(Path(a.probes).parent / "audio" / "mix" / f"{d['debate_id']}.json"))["turns"]}
        for t in d["turns"]:
            if t["speaker"] == "MOD":
                continue
            r = tl[t["i"]]
            pause.append({"debate_id": d["debate_id"], "start_sec": round(r["end_sec"] + 0.3, 2), "end_sec": round(r["end_sec"] + 1.8, 2), "text": "..."})
    (out / "on_pause.jsonl").write_text("\n".join(json.dumps(u) for u in pause))
    print(f"silent 0 · every_trigger {len(every)} · on_pause {len(pause)} -> {out}/")


if __name__ == "__main__":
    main()
