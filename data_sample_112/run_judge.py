#!/usr/bin/env python3
"""Send the judge packets written by score_freerun.py to an OpenAI-compatible chat model.

  python3 run_judge.py --scores scores/ --model gpt-5.6-luna --yes --max-calls 400
  python3 run_judge.py --scores scores/ --dry            # print the packets only

Content judging is per criterion, so a two-criterion code can score 0.5:
  score = met / total ; missing = the criteria that were not met (kept for the report).

The judge never sees our taxonomy letters. It picks the action it saw from a list of
plain-word action names; the mapping back to codes lives in eval_rubric.json["actions"].

Writes scores/<debate_id>.judge.json:
  {"triggers": {probe_id: {score, pass, met, missing, why, action, predicted_label}},
   "non_trigger": [{verdict, violated_duty, why}]}
One call per packet, no retries.
"""
import argparse, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SYS_CONTENT = (
    "You judge one line from a debate moderator. Content only, never timing or style. "
    "Given the situation and the rule, did the line do what it had to do? "
    "If it read the situation wrong and did something else instead, say what. "
    "Credit only what the line actually says. JSON only."
)
SYS_NT = (
    "You judge one moderator utterance made where no moderator action was due. Read the system prompt the "
    "moderator was given and the surrounding transcript. Answer JSON only with verdict in "
    "{backchannel, acceptable, awkward, violation}, violated_duty = the sentence of the system prompt that is "
    "broken (or empty), and a one-sentence why."
)

CONTENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "met": {"type": "array", "items": {"type": "boolean"}},
        "why": {"type": "array", "items": {"type": "string"}},
        "misread": {"type": "string"},
    },
    "required": ["met", "why", "misread"],
}
NT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"verdict": {"type": "string"}, "violated_duty": {"type": "string"}, "why": {"type": "string"}},
    "required": ["verdict", "violated_duty", "why"],
}


def grade(criteria, met, misread):
    """met[] -> score + which rule was missing (the 0.5 reason).

    `misread` is the judge's own words for what the line did instead, when it read the
    situation wrong. No list of actions is shown to the judge, so the expected answer
    cannot anchor the verdict; mapping misread text to a code is done afterwards.
    """
    met = (list(met) + [False] * len(criteria))[:len(criteria)]
    n = len(criteria)
    score = round(sum(1 for m in met if m) / n, 3) if n else 0.0
    return {
        "score": score,
        "pass": score == 1.0,
        "met": [c for c, m in zip(criteria, met) if m],
        "missing": [c for c, m in zip(criteria, met) if not m],
        "misread": (misread or "").strip(),
    }


def user_block(pk, criteria, situation, n_ctx):
    """읽히는 녹취 + 판정 대상 표시 + 상황 + 규칙. JSON 중첩을 쓰지 않는다."""
    nm = pk.get("names") or {}
    L = ["--- transcript ---"]
    for t in (pk.get("context_turns") or [])[-n_ctx:]:
        who = t.get("speaker")
        L.append(f'{who} ({nm.get(who, who)}): {t.get("text")}')
    L.append(f'MOD ({nm.get("MOD", "MOD")}): {pk.get("utterance")}      <<< judge this line')
    L += ["", f'Situation: {situation[pk["code"]]}', "Rule — the moderator had to:"]
    for i, c in enumerate(criteria, 1):
        L.append(f"  {i}. {c}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", default="scores")
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--rubric", default=str(HERE / "eval_rubric.json"))
    ap.add_argument("--prompt", default="system_prompt.md")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--max-calls", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    rub = json.load(open(a.rubric))
    SIT = rub["content"]["situation"]
    NCTX = int(rub["content"].get("context_turns", 5))

    files = [f for f in sorted(Path(a.scores).glob("L*.json")) if not f.name.endswith(".judge.json")]
    jobs = []
    r_code = {}          # probe_id -> 기대 코드. 채점 후처리에만 쓰고 judge 에게는 보내지 않는다.
    for f in files:
        sc = json.load(open(f))
        for r in sc["triggers"]:
            if r.get("judge_packet"):
                r_code[r["probe_id"]] = r["code"]
                jobs.append((f, "trigger", r["probe_id"], r["judge_packet"]))
        for i, x in enumerate(sc["non_trigger"]):
            if x.get("judge_packet"):
                jobs.append((f, "non_trigger", i, x["judge_packet"]))
    print(f"packets: {len(jobs)} from {len(files)} debates")

    if a.dry:
        for f, kind, key, pk in jobs[:3]:
            print("---", f.name, kind, key)
            print(json.dumps(pk, ensure_ascii=False, indent=1)[:900])
        return
    if not a.yes:
        sys.exit("refused: paid calls need --yes")
    if not a.max_calls or len(jobs) > a.max_calls:
        sys.exit(f"refused: {len(jobs)} packets > --max-calls {a.max_calls}")

    from openai import OpenAI
    cl = OpenAI(api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("GPT_API_KEY"))
    sysp = Path(a.prompt).read_text() if Path(a.prompt).exists() else ""
    res = {}

    for f, kind, key, pk in jobs:
        did = f.stem
        res.setdefault(did, {"triggers": {}, "non_trigger": {}})
        if kind == "trigger":
            crit = pk["criteria"]
            msgs = [{"role": "system", "content": SYS_CONTENT},
                    {"role": "user", "content": user_block(pk, crit, SIT, NCTX)}]
            schema, name = CONTENT_SCHEMA, "content"
        else:
            msgs = [{"role": "system", "content": SYS_NT},
                    {"role": "user", "content": "SYSTEM PROMPT GIVEN TO THE MODERATOR:\n" + sysp
                     + "\n\nCONTEXT:\n" + "\n".join(pk.get("context", []))
                     + "\n\nUTTERANCE: " + str(pk.get("utterance"))}]
            schema, name = NT_SCHEMA, "non_trigger"
        slot = "triggers" if kind == "trigger" else "non_trigger"
        try:
            o = cl.chat.completions.create(
                model=a.model, max_completion_tokens=400, messages=msgs,
                response_format={"type": "json_schema",
                                 "json_schema": {"name": name, "strict": True, "schema": schema}})
            out = json.loads(o.choices[0].message.content)
            if kind == "trigger":
                g = grade(crit, out.get("met", []), out.get("misread", ""))
                g["why"] = out.get("why", [])
                res[did][slot][key] = g
            else:
                res[did][slot][key] = out
        except Exception as e:
            res[did][slot][key] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}

    for did, r in res.items():
        n = len(json.load(open(Path(a.scores) / f"{did}.json"))["non_trigger"])
        r["non_trigger"] = [r["non_trigger"].get(i) for i in range(n)]
        (Path(a.scores) / f"{did}.judge.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print("wrote", len(res), "judge files")


if __name__ == "__main__":
    main()
