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
    "You judge one moderator utterance from a debate. "
    "For each criterion you are given, decide whether the utterance meets it, and give a one-line reason. "
    "Judge only what the utterance actually says; do not credit anything it does not state. "
    "Also name the single action the utterance performs, copied verbatim from the actions list. "
    "Judge the text only, never the timing. JSON only."
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
        "action": {"type": "string"},
    },
    "required": ["met", "why", "action"],
}
NT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"verdict": {"type": "string"}, "violated_duty": {"type": "string"}, "why": {"type": "string"}},
    "required": ["verdict", "violated_duty", "why"],
}


def grade(criteria, met, actions_map, action, expected):
    """met[] -> score + which criterion was missing (the 0.5 reason).

    `expected` is used only to resolve an action name that maps to more than one code.
    A1/A2-1 and A4/A4xf are separated by structure (is anyone next; which clock), never by
    wording, so the judge cannot tell them apart from text and we do not ask it to.
    """
    met = (list(met) + [False] * len(criteria))[:len(criteria)]
    n = len(criteria)
    score = round(sum(1 for m in met if m) / n, 3) if n else 0.0
    codes = actions_map.get(action, [])
    if not codes:
        label = "none" if action == "none" else "other"
    elif len(codes) == 1:
        label = codes[0]
    else:
        label = expected if expected in codes else codes[0]
    return {
        "score": score,
        "pass": score == 1.0,
        "met": [c for c, m in zip(criteria, met) if m],
        "missing": [c for c, m in zip(criteria, met) if not m],
        "action": action,
        "predicted_label": label,
        "ambiguous_action": len(codes) > 1,
    }


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
    actions_map = rub.get("actions", {})
    action_list = list(actions_map)

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
            user = {"criteria": crit, "trigger": pk.get("trigger"), "names": pk.get("names"),
                    "utterance": pk.get("utterance"), "actions": action_list}
            msgs = [{"role": "system", "content": SYS_CONTENT},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]
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
                g = grade(crit, out.get("met", []), actions_map, out.get("action", "other"), r_code[key])
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
