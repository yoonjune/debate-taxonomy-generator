#!/usr/bin/env python3
"""Send the judge packets written by score_freerun.py to an OpenAI-compatible chat model.

  python3 run_judge.py --scores scores/ --model gpt-5.6-luna --yes --max-calls 400
  python3 run_judge.py --scores scores/ --dry            # print the packets only

Writes scores/<debate_id>.judge.json: {"triggers": {probe_id: {pass, predicted_label, why}},
"non_trigger": [{start_sec, verdict, violated_duty, why}]}. One call per packet, no retries.
"""
import argparse, json, os, sys
from pathlib import Path

CONTENT_SCHEMA = {"type": "object", "additionalProperties": False,
                  "properties": {"pass": {"type": "boolean"}, "predicted_label": {"type": "string"}, "why": {"type": "string"}},
                  "required": ["pass", "predicted_label", "why"]}
NT_SCHEMA = {"type": "object", "additionalProperties": False,
             "properties": {"verdict": {"type": "string"}, "violated_duty": {"type": "string"}, "why": {"type": "string"}},
             "required": ["verdict", "violated_duty", "why"]}
SYS_CONTENT = ("You judge one moderator utterance from a debate. Decide whether it performs the required action. "
               "Answer pass=true only if every listed criterion holds. Also name the action it actually performed "
               "(A1, A2-1, A2-2, A3-1, A3-2, A4, A5, B1, B2, none, other). Judge the text only, not the timing. JSON only.")
SYS_NT = ("You judge one moderator utterance made where no moderator action was due. Read the system prompt the moderator was given "
          "and the surrounding transcript. Answer JSON only with verdict in {backchannel, acceptable, awkward, violation}, "
          "violated_duty = the sentence of the system prompt that is broken (or empty), and a one-sentence why.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", default="scores"); ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--prompt", default="system_prompt.md"); ap.add_argument("--yes", action="store_true")
    ap.add_argument("--max-calls", type=int, default=0); ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    files = sorted(Path(a.scores).glob("L*.json"))
    files = [f for f in files if not f.name.endswith(".judge.json")]
    jobs = []
    for f in files:
        sc = json.load(open(f))
        for r in sc["triggers"]:
            if r.get("judge_packet"): jobs.append((f, "trigger", r["probe_id"], r["judge_packet"]))
        for i, x in enumerate(sc["non_trigger"]):
            if x.get("judge_packet"): jobs.append((f, "non_trigger", i, x["judge_packet"]))
    print(f"packets: {len(jobs)} from {len(files)} debates")
    if a.dry:
        for f, kind, key, pk in jobs[:3]:
            print("---", f.name, kind, key); print(json.dumps(pk, ensure_ascii=False)[:600])
        return
    if not a.yes: sys.exit("refused: paid calls need --yes")
    if not a.max_calls or len(jobs) > a.max_calls: sys.exit(f"refused: {len(jobs)} packets > --max-calls {a.max_calls}")
    from openai import OpenAI
    cl = OpenAI(api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("GPT_API_KEY"))
    sysp = Path(a.prompt).read_text() if Path(a.prompt).exists() else ""
    res = {}
    for f, kind, key, pk in jobs:
        did = f.stem
        res.setdefault(did, {"triggers": {}, "non_trigger": {}})
        if kind == "trigger":
            msgs = [{"role": "system", "content": SYS_CONTENT},
                    {"role": "user", "content": json.dumps({k: pk[k] for k in ("code", "criteria", "trigger", "names", "utterance")}, ensure_ascii=False)}]
            schema, name = CONTENT_SCHEMA, "content"
        else:
            msgs = [{"role": "system", "content": SYS_NT},
                    {"role": "user", "content": "SYSTEM PROMPT GIVEN TO THE MODERATOR:\n" + sysp + "\n\nCONTEXT:\n" + "\n".join(pk.get("context", [])) + "\n\nUTTERANCE: " + str(pk.get("utterance"))}]
            schema, name = NT_SCHEMA, "non_trigger"
        try:
            o = cl.chat.completions.create(model=a.model, max_completion_tokens=400, messages=msgs,
                                           response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}})
            res[did][kind + "s" if kind == "trigger" else "non_trigger"][key] = json.loads(o.choices[0].message.content)
        except Exception as e:
            res[did][kind + "s" if kind == "trigger" else "non_trigger"][key] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    for did, r in res.items():
        r["non_trigger"] = [r["non_trigger"].get(i) for i in range(len(json.load(open(Path(a.scores) / f"{did}.json"))["non_trigger"]))]
        (Path(a.scores) / f"{did}.judge.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print("wrote", len(res), "judge files")


if __name__ == "__main__":
    main()
