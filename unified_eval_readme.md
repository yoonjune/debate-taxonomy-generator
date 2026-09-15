# Unified free-run evaluation

This is the reproducible evaluator used for Raon-SpeechChat-9B and MiniCPM-o:
deterministic timing, blinded `gpt-5.6-luna` content judgment, then
trigger-weighted timing/content/joint aggregation. Use the same procedure for
Gemini, GPT-Live, or PersonaPlex-RL-Seamless. `EVAL_SETTING.md` is the task
authority.

## Required inference artifact

Run the moderator model in free-run mode. The moderator channel is open over
the full debater-only debate: never inject reference MOD lines, force silence,
or stop at a trigger. Log every model utterance as one line of JSONL:

```json
{"debate_id":"L000","start_sec":38.90,"end_sec":40.10,"text":"Ten seconds, Nina."}
```

`start_sec` is the first speech onset and all times must be in **source-debate
seconds**. If the inference harness pauses debater audio in registered gaps, it
must map session time back to source time before it writes `utterances.jsonl`.
Include silent debates by simply omitting their utterance lines.

## 1. Score timing and make judge packets

```bash
cd data_sample_112
python3 score_freerun.py \
  --probes probes.jsonl --debates debates.jsonl \
  --utts /absolute/path/to/utterances.jsonl \
  --out /absolute/path/to/<model>_scores \
  --anchor-xf model
```

This deterministic command writes `Lxxx.json` files and `summary.json`; it
makes no API call. `--anchor-xf model` is required: the crossfire clock is
anchored to the end of the model's own Open utterance, with the reference anchor
only as fallback.

Timing uses the first qualifying non-backchannel onset: `ON_TIME` in the
trigger window, `PREMATURE` from deadline minus 5 seconds until the window,
`LATE` up to 3 seconds after it, and `MISSED` otherwise.

## 2. Run the Luna content judge

Set `OPENAI_API_KEY` or `GPT_API_KEY`. Inspect the exact paid-call count first:

```bash
python3 run_judge.py --scores /absolute/path/to/<model>_scores --dry
```

Then replace `N` below with that count and run one paid call per packet:

```bash
python3 run_judge.py \
  --scores /absolute/path/to/<model>_scores \
  --model gpt-5.6-luna --yes --max-calls N \
  --workers 8 --timeout 30
```

The comparable configuration is fixed: `gpt-5.6-luna`,
`reasoning_effort="none"`, strict JSON-schema output, 400 completion tokens,
no retries, eight workers, and a hard 30-second timeout per packet. Use fewer
workers only when the account is rate-limited.

### Exact content evidence

The fixed Luna system prompt is:

```text
You judge one line from a debate moderator. Content only, never timing or style.
Given the situation and the rule, did the line do what it had to do?
If it read the situation wrong and did something else instead, say what.
Credit only what the line actually says. JSON only.
```

The user message contains up to five preceding English transcript turns, the
model's MOD line marked `<<< judge this line`, a plain-language situation, and
the one or two action criteria. Luna does **not** see the reference/GT moderator
utterance, taxonomy labels such as `A2-1`, timing labels, a list of actions, or
the expected answer. It returns `met[]` (one Boolean per criterion), `why[]`,
and `misread`.

Content is `met criteria / total criteria`. Single-criterion actions are 0 or
1; Open, Cut&Pass, and Reconcile may be 0, 0.5, or 1. `pass` is `score == 1`.
Non-trigger utterances use a separate Luna packet and are labelled
`backchannel`, `acceptable`, `awkward`, or `violation`; they are not part of the
main-table Content score.

## 3. Aggregate

```bash
# Full diagnostic
python3 report.py --scores /absolute/path/to/<model>_scores

# Paper table: 249-debate release subset
python3 report.py --scores /absolute/path/to/<model>_scores \
  --exclude-debates L185 L226
```

The report writes `report.md` and `report.json`. `All` is trigger-weighted, not
a mean of taxonomy means: Timing is total ON_TIME / total triggers; Content is
the sum of judged content scores / judged trigger count; Joint is the sum of
`ON_TIME × content` / its trigger denominator. Timing is rule-based; Luna never
decides timing.

## Handoff to an inference agent

Tell the agent to read `EVAL_SETTING.md`, this file,
`data_sample_112/score_freerun.py`, and `data_sample_112/eval_rubric.json`.
Require it to return: immutable `utterances.jsonl`, the generated
`<model>_scores/` directory, and a manifest with model revision, harness
revision, prompt filename, source-clock conversion, and exact judge command.
Never overwrite another model's score directory.
