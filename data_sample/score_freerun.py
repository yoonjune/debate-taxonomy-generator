#!/usr/bin/env python3
"""Free-run scorer. Model channel was open for the whole debate; debater audio was static.

  python3 score_freerun.py --probes probes.jsonl --utts utterances.jsonl --out scores/

utterances.jsonl  one line per model utterance:
  {"debate_id": "L000", "start_sec": 38.9, "end_sec": 40.1, "text": "Ten seconds, Nina."}
  (start_sec = speech onset on the model channel, seconds from the debate start; text = the model's
   text stream for that utterance, or ASR of its audio)

Output
  scores/<debate_id>.json   per trigger: timing class + judge packet (binary content rubric)
                            non-trigger utterances: judge packet (duty violation / awkward / backchannel)
  scores/summary.json       counts per code and timing class

No model is called here. Judge packets are written for an LLM judge (see eval_rubric.json).
"""
import argparse, collections, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRE = 5.0        # PREMATURE: onset in [deadline - PRE, t_earliest)
LATE = 3.0       # LATE: onset in (t_latest, t_latest + LATE]
BACK_SEC = 0.4   # under this AND at most one word → backchannel
FILLERS = {"mm", "mmm", "mm-hm", "mhm", "uh-huh", "uh huh", "yeah", "yes", "okay", "ok", "right", "hmm", "hm", "sure", "uh", "um"}
CTX_BEFORE, CTX_AFTER = 20.0, 5.0


def load_jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def code_of(probe, debate):
    c = probe["label"]
    if c == "A4" and debate["turns"][probe["before_turn"]]["phase"] == 2:
        return "A4xf"
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probes", default="probes.jsonl")
    ap.add_argument("--debates", default="debates.jsonl")
    ap.add_argument("--utts", required=True)
    ap.add_argument("--rubric", default=str(HERE / "eval_rubric.json"))
    ap.add_argument("--prompt", default="system_prompt.md")
    ap.add_argument("--out", default="scores")
    a = ap.parse_args()

    rub = json.load(open(a.rubric))
    D = {d["debate_id"]: d for d in load_jsonl(a.debates)}
    P = collections.defaultdict(list)
    for p in load_jsonl(a.probes):
        if p["label"] != "none":
            P[p["debate_id"]].append(p)
    U = collections.defaultdict(list)
    for u in load_jsonl(a.utts):
        U[u["debate_id"]].append(u)
    out = Path(a.out); out.mkdir(exist_ok=True)
    summary = collections.Counter(); nontrig = collections.Counter()

    for did, probes in P.items():
        d = D[did]; nm = {k: v["name"] for k, v in d["speakers"].items()}
        utts = sorted(U.get(did, []), key=lambda u: u["start_sec"])
        for u in utts:
            words = (u.get("text") or "").lower().replace(".", "").replace(",", "").split()
            u["backchannel"] = (words and all(w in FILLERS for w in words)) or \
                               ((u["end_sec"] - u["start_sec"] < BACK_SEC) and len(words) <= 1)
        taken = set()               # 창이 겹치면(A1 → A3-1) 한 발화가 두 trigger 에 붙을 수 있다
        rows = []
        for p in sorted(probes, key=lambda p: p["t_deadline"]):
            code = code_of(p, d)
            e, dl, l = p["t_earliest"], p["t_deadline"], p["t_latest"]
            cand = [u for u in utts if not u["backchannel"]
                    and dl - PRE <= u["start_sec"] <= l + LATE]
            u = cand[0] if cand else None
            if u is None:
                status = "MISSED"
            elif u["start_sec"] < e:
                status = "PREMATURE"
            elif u["start_sec"] <= l:
                status = "ON_TIME"
            else:
                status = "LATE"
            if u is not None:
                taken.add(id(u))
            rows.append({
                "probe_id": p["probe_id"], "code": code, "window": [e, dl, l],
                "timing": status, "onset_sec": u["start_sec"] if u else None,
                "onset_minus_deadline": round(u["start_sec"] - dl, 2) if u else None,
                "text": (u.get("text") if u else None),
                "judge_packet": {
                    "task": "content", "code": code,
                    "criteria": rub["codes"][code]["content"],
                    "instruction": "Answer pass only if every criterion holds. Judge the text only, not the timing.",
                    "trigger": p.get("trigger"), "names": nm,
                    "utterance": (u.get("text") if u else None),
                    "expected_output_schema": {"pass": "boolean", "predicted_label": "A1|A2-1|A2-2|A3-1|A3-2|A4|A5|B1|B2|none|other", "why": "string"}
                } if u else None,
            })
            summary[(code, status)] += 1
        # non-trigger utterances
        turns = d["turns"]
        tl = None
        try:
            tl = {t["i"]: t for t in json.load(open(Path(a.probes).parent / "audio" / "mix" / f"{did}.json"))["turns"]}
        except Exception:
            pass
        extra = []
        for u in utts:
            if id(u) in taken:
                continue
            near = min(probes, key=lambda p: abs(p["t_deadline"] - u["start_sec"]))
            ctx = []
            if tl:
                for t in turns:
                    r = tl.get(t["i"])
                    if r and r["end_sec"] >= u["start_sec"] - CTX_BEFORE and r["start_sec"] <= u["start_sec"] + CTX_AFTER:
                        ctx.append(f'[{r["start_sec"]:.1f}s] {nm[t["speaker"]]} ({t["speaker"]}): {t["text"]}')
            kind = "backchannel" if u["backchannel"] else "non_trigger"
            extra.append({
                "start_sec": u["start_sec"], "end_sec": u["end_sec"], "text": u.get("text"), "kind": kind,
                "nearest_trigger": {"probe_id": near["probe_id"], "code": code_of(near, d), "distance_sec": round(u["start_sec"] - near["t_deadline"], 2)},
                "judge_packet": None if u["backchannel"] else {
                    "task": "non_trigger", "system_prompt_file": a.prompt, "context": ctx, "utterance": u.get("text"),
                    "instruction": rub["non_trigger_judge"]["instruction"] + " Violation means: " + rub["non_trigger_judge"]["violation"],
                    "expected_output_schema": rub["non_trigger_judge"]["output"]},
            })
            nontrig[kind] += 1
        (out / f"{did}.json").write_text(json.dumps({"debate_id": did, "triggers": rows, "non_trigger": extra},
                                                     ensure_ascii=False, indent=1))

    by_code = collections.defaultdict(dict)
    for (code, st), n in summary.items():
        by_code[code][st] = n
    (out / "summary.json").write_text(json.dumps({"triggers": by_code, "non_trigger": dict(nontrig)}, ensure_ascii=False, indent=1))
    print("triggers:", json.dumps(by_code, ensure_ascii=False))
    print("non-trigger:", dict(nontrig), "->", out)


if __name__ == "__main__":
    main()
