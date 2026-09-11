#!/usr/bin/env python3
"""Aggregate scores/ (+ optional judge files) into one table.

  python3 report.py --scores scores/            → scores/report.md and report.json
"""
import argparse, collections, json, statistics as st
from pathlib import Path

CODES = ["A4", "A4xf", "A2-2", "A3-1", "A3-2", "A1", "A2-1", "A5", "B1", "B2"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--scores", default="scores"); a = ap.parse_args()
    S = Path(a.scores)
    tim = collections.defaultdict(collections.Counter); offs = collections.defaultdict(list)
    cont = collections.defaultdict(lambda: [0, 0]); joint = collections.defaultdict(lambda: [0, 0])
    conf = collections.defaultdict(collections.Counter); nt = collections.Counter(); ntv = collections.Counter(); n_deb = 0
    partial = collections.defaultdict(collections.Counter)   # 0.5 를 만든 원인: 빠진 기준
    for f in sorted(S.glob("L*.json")):
        if f.name.endswith(".judge.json"): continue
        n_deb += 1
        sc = json.load(open(f)); jf = S / f"{f.stem}.judge.json"
        J = json.load(open(jf)) if jf.exists() else None
        for r in sc["triggers"]:
            c = r["code"]; tim[c][r["timing"]] += 1
            if r["onset_minus_deadline"] is not None: offs[c].append(r["onset_minus_deadline"])
            jv = (J or {}).get("triggers", {}).get(r["probe_id"]) if J else None
            if jv and "score" in jv:
                s = float(jv["score"])
                cont[c][1] += 1; cont[c][0] += s; conf[c][jv.get("predicted_label", "?")] += 1
                joint[c][1] += 1; joint[c][0] += s if r["timing"] == "ON_TIME" else 0.0
                if 0.0 < s < 1.0:
                    for m in jv.get("missing", []): partial[c][m] += 1
            elif r["timing"] != "MISSED":
                joint[c][1] += 1
        for i, x in enumerate(sc["non_trigger"]):
            nt[x["kind"]] += 1
            if J and J.get("non_trigger") and i < len(J["non_trigger"]) and J["non_trigger"][i]:
                ntv[J["non_trigger"][i].get("verdict", "?")] += 1
    L = [f"# Report ({n_deb} debates)", "", "| code | n | MISSED | PREMATURE | ON_TIME | LATE | onset−deadline median (IQR) | content pass | joint |", "|---|---|---|---|---|---|---|---|---|"]
    for c in CODES:
        t = tim[c]; n = sum(t.values())
        if not n: continue
        o = sorted(offs[c]); med = f"{st.median(o):+.2f} ({o[len(o)//4]:+.1f}…{o[3*len(o)//4]:+.1f})" if o else "—"
        cp = f"{cont[c][0]:.1f}/{cont[c][1]}" if cont[c][1] else "—"; jp = f"{joint[c][0]:.1f}/{joint[c][1]}" if joint[c][1] else "—"
        L.append(f"| {c} | {n} | {t['MISSED']} | {t['PREMATURE']} | {t['ON_TIME']} | {t['LATE']} | {med} | {cp} | {jp} |")
    if partial:
        L += ["", "Half credit — which criterion was missing:", ""]
        for c in CODES:
            for m, k in partial[c].most_common():
                L.append(f"- **{c}** x{k} — missing: {m}")
    L += ["", f"Non-trigger utterances: {dict(nt)}", f"Non-trigger verdicts: {dict(ntv)}" if ntv else "Non-trigger verdicts: (run run_judge.py)"]
    if conf:
        L += ["", "Predicted-label confusion (rows = gold code):", "", "| gold | " + " | ".join(CODES + ["none", "other"]) + " |", "|---|" + "---|" * (len(CODES) + 2)]
        for c in CODES:
            if conf[c]: L.append(f"| {c} | " + " | ".join(str(conf[c].get(k, 0)) for k in CODES + ["none", "other"]) + " |")
    (S / "report.md").write_text("\n".join(L)); (S / "report.json").write_text(json.dumps({"timing": {c: dict(v) for c, v in tim.items()}, "non_trigger": dict(nt), "verdicts": dict(ntv),
                                            "content_score": {c: v for c, v in cont.items()},
                                            "half_credit_missing": {c: dict(v) for c, v in partial.items() if v}}, indent=1))
    print("\n".join(L))


if __name__ == "__main__":
    main()
