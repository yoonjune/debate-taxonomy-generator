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
import argparse, json, multiprocessing, os, sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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


def isolated_http_request(api_key, body, timeout, queue):
    """Child process: a TLS read can ignore the Python socket timeout."""
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            queue.put((True, json.loads(response.read())["choices"][0]["message"]["content"]))
    except Exception as exc:
        queue.put((False, f"{type(exc).__name__}: {str(exc)[:240]}"))


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
    ap.add_argument("--take", type=int, default=0,
                    help="run only the first N packets (transport smoke test; not for final scoring)")
    ap.add_argument("--workers", type=int, default=1,
                    help="simultaneous independent judge requests (default: 1)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="per-request timeout in seconds; prevents a single judge packet from stalling a run")
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
    if a.take:
        jobs = jobs[:a.take]

    # Use the HTTP API directly.  The SDK transport has intermittently held a
    # request open even with a timeout; urlopen gives us a hard per-packet
    # boundary and exactly one paid request per packet.
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GPT_API_KEY")
    if not api_key:
        sys.exit("missing OPENAI_API_KEY or GPT_API_KEY")

    def request(messages, schema, name):
        body = json.dumps({
            "model": a.model,
            "reasoning_effort": "none",
            "max_completion_tokens": 400,
            "messages": messages,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": name, "strict": True, "schema": schema}},
        }).encode("utf-8")
        queue = multiprocessing.Queue()
        proc = multiprocessing.Process(target=isolated_http_request,
                                       args=(api_key, body, a.timeout, queue))
        proc.start()
        proc.join(a.timeout + 2)
        if proc.is_alive():
            proc.terminate()
            proc.join()
            raise TimeoutError(f"hard timeout after {a.timeout}s")
        if queue.empty():
            raise RuntimeError(f"request child exited {proc.exitcode} without a response")
        ok, value = queue.get()
        if not ok:
            raise RuntimeError(value)
        return value
    sysp = Path(a.prompt).read_text() if Path(a.prompt).exists() else ""
    res = {}

    def judge_one(job):
        f, kind, key, pk = job
        did = f.stem
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
            out = json.loads(request(msgs, schema, name))
            if kind == "trigger":
                g = grade(crit, out.get("met", []), out.get("misread", ""))
                g["why"] = out.get("why", [])
                value = g
            else:
                value = out
        except Exception as e:
            value = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        return did, slot, key, value

    if a.workers < 1:
        sys.exit("--workers must be at least 1")
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        results = pool.map(judge_one, jobs)
        for job_no, (did, slot, key, value) in enumerate(results, 1):
            res.setdefault(did, {"triggers": {}, "non_trigger": {}})
            res[did][slot][key] = value
            if job_no == 1 or job_no % 25 == 0 or job_no == len(jobs):
                print(f"progress: {job_no}/{len(jobs)}", flush=True)

    for did, r in res.items():
        n = len(json.load(open(Path(a.scores) / f"{did}.json"))["non_trigger"])
        r["non_trigger"] = [r["non_trigger"].get(i) for i in range(n)]
        (Path(a.scores) / f"{did}.judge.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print("wrote", len(res), "judge files")


if __name__ == "__main__":
    main()
