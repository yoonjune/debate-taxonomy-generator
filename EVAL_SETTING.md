# Evaluation setting — final

The benchmark puts a full-duplex speech model in the **moderator's seat** of a three-person
Oxford-style debate and asks two questions at every scored moment: **did it speak at the right
time**, and **did it say the right thing**.

Timing is decided by rule. Content is decided by an LLM judge. Nothing else is scored.

- Package: [`data_sample_112/`](data_sample_112/) — 112 debates, 1,071 scored triggers, 4.4–5.5 min each.
- Machine-readable form of everything below: [`data_sample_112/eval_rubric.json`](data_sample_112/eval_rubric.json).
- Scripts: `score_freerun.py` (timing + judge packets) → `run_judge.py` (LLM) → `report.py` (table).

---

## 1. How a run works

The debater audio (every PRO and CON turn at its recorded time) plays from start to finish and is
**never modified**. The model's own channel is **open for the whole debate**: nothing is forced into
it, nothing is muted, no reference line is injected. Every utterance the model produces is logged
with its onset time and text.

This is the only mode we report. A probe-replay mode (reference moderator teacher-forced up to a
release point, then one trigger freed) exists as a secondary tool for clean per-code timing.

**Audio the harness must supply.** The debater audio is never cut, so the end of every scoring
window is inside the input. A harness that truncates must include audio up to `t_latest + 3 s`.

**Utterance onset.** Energy VAD on the model channel: 20 ms frames, minimum speech 200 ms, minimum
silence 600 ms.

**Speech-end marker.** Every opening or closing statement that finished inside its thirty seconds ends with
`That's all, thank you.`, spoken in that debater's own voice. Statements the moderator cut for time do not have it —
they were stopped mid-sentence. The `A2-2` and `A3-1` deadlines are the end of that marker, so a model that waits to
hear a statement finish is on time.

**Back-channels are never attributed to a trigger.** An utterance is a back-channel if its text is
only a filler (`mm, mm-hm, uh-huh, yeah, okay, right, hmm, sure`) or it is under 0.4 s with at most
one word. One-word moderator lines such as `"Time."` are **not** back-channels — they are real
interventions and are scored.

---

## 2. Timing — decided by rule

Every trigger in `probes.jsonl` carries three times: `t_earliest`, `t_deadline`, `t_latest`.
The window is the deadline ±2 s, except where the format guarantees the speaker has time left —
A1, A2-1, A2-2, A3-1, A5, B1 and B2 cannot be correct *before* their deadline, so those windows
open at the deadline.

| code | action | deadline | window (relative to deadline) | what the model hears in the window | n |
|---|---|---|---|---|--:|
| `A4` | ten-second cue, opening/closing | speaker start + 20 s | −2 … +2 | speech continues throughout | 278 |
| `A4xf` | ten-second cue, crossfire | crossfire start + 140 s | −2 … +2 | crossfire continues | 112 |
| `A2-2` | hand over after an in-time finish | end of PRO's speech | 0 … +2 | silence where the reference moderator spoke | 166 |
| `A3-1` | open the crossfire | end of CON's opening | 0 … +2 | silence | 112 |
| `A3-2` | close the crossfire, open closings | crossfire start + 150 s | −2 … +2 | speech, cut inside the window | 112 |
| `A1` | cut an overrun, nobody next this round | speaker start + 30 s | 0 … +2 | speech, cut inside the window | 59 |
| `A2-1` | cut an overrun, then hand over | speaker start + 30 s | 0 … +2 | speech, cut inside the window | 58 |
| `A5` | block an out-of-turn interruption | interruption start | 0 … +2 | the interrupter keeps talking | 53 |
| `B1` | bring a drifting speaker back | end of the drifting turn | 0 … +2 | silence | 57 |
| `B2` | point out a self-contradiction | end of the contradicting turn | 0 … +2 | silence | 64 |

**Classes.** An onset inside `[t_earliest, t_latest]` is `ON_TIME`. An onset in
`[t_deadline − 5, t_earliest)` is `PREMATURE`. An onset in `(t_latest, t_latest + 3]` is `LATE`.
No qualifying onset is `MISSED`. Windows can overlap — A1 is immediately followed by A3-1 in the
openings — and one utterance may then be scored against both.

**The crossfire clock.** `A4xf` and `A3-2` are measured from the moment the crossfire opened. In a
free run that is **the end of the model's own A3-1 utterance**, with the reference `xf_open_sec` as
the fallback when the model never opened it. Because that anchor moves, report the
`onset − deadline` distribution for these two codes, not only the `ON_TIME` rate.

---

## 3. Content — decided by an LLM judge

### 3.1 The fixed part

Every code uses the same system prompt. It never changes.

```
You judge one moderator utterance from a debate. For each criterion you are given, decide
whether the utterance meets it, and give a one-line reason. Judge only what the utterance
actually says; do not credit anything it does not state. Also name the single action the
utterance performs, copied verbatim from the actions list. Judge the text only, never the
timing. JSON only.
```

The user message is one JSON object:

```json
{ "criteria":  [...],          // the only field that differs between codes
  "trigger":   {"text": [...]},// the debater turn(s) that created the opening
  "names":     {"MOD": "...", "PRO": "...", "CON": "..."},
  "utterance": "...",          // what the model said (its text stream, or ASR of its audio)
  "actions":   [...] }         // the fixed action list, below
```

**What the judge is deliberately not given.** It does not see our taxonomy letters, and it does not
see the reference moderator's line. Both were removed because either one lets the expected answer
anchor the verdict: a correct utterance that differs from the reference would be marked wrong.

**Action list.** The judge names what it saw in plain words. Mapping back to a code happens
afterwards, in `eval_rubric.json["actions"]`.

```
ten-second cue · hand the floor to the other side · open the next round ·
open the closing round · stop the speaker for time · restrain an interrupter ·
redirect to the motion · point out a self-contradiction · none · other
```

`A1`/`A2-1` and `A4`/`A4xf` are separated by structure — is anyone next, which clock is running —
never by wording. The judge cannot tell them apart from text and is not asked to; the trigger slot
resolves them.

### 3.2 The part that changes per code

The `criteria` array is the whole per-code specification.

| code | `criteria` sent to the judge | max |
|---|---|--:|
| `A4` | `says that ten seconds remain (the word 'ten')` | 1 |
| `A4xf` | `says that ten seconds remain (the word 'ten')` | 1 |
| `A2-2` | `hands the floor to the other side (name, side, or 'next')` | 1 |
| `A3-1` | `announces that the debate moves on to the next round (any wording)`<br>`states the length (two and a half minutes)` | 2 |
| `A3-2` | `moves the debate on to the closing round` | 1 |
| `A1` | `stops the speaker for time` | 1 |
| `A2-1` | `stops the speaker for time`<br>`hands the floor to the other side (name, side, or 'next')` | 2 |
| `A5` | `tells the interrupter to stop or wait (restrains them)` | 1 |
| `B1` | `redirects the speaker back to the motion` | 1 |
| `B2` | `points out that the speaker contradicted themselves`<br>`asks the speaker to reconcile it` | 2 |

Three deliberate relaxations are baked into this list.

- **A3-1 does not require the word "crossfire."** Any wording for moving to the next round counts.
  Real chairs say "Let's debate" or "let's move on to the discussion portion."
- **A3-2 does not require saying that time is up.** Moving the debate to the closing round is enough.
- **B2 does not require quoting both claims.** Pointing out that the speaker contradicted themselves
  is enough, as long as the utterance also asks them to reconcile it.

### 3.3 Scoring, including half credit

The judge marks **each criterion separately** and gives a one-line reason for each.

```
score = criteria met / criteria total
```

A one-criterion code scores **0 or 1**. A two-criterion code scores **0, 0.5 or 1**. `pass` is
kept as the binary view and means `score == 1.0`.

When a code scores 0.5, the scorer records **which criterion was missing**, so half credit is always
explainable:

```json
{ "score": 0.5,
  "met":     ["stops the speaker for time"],
  "missing": ["hands the floor to the other side (name, side, or 'next')"],
  "why":     ["says 'That's time, Christina'", "names nobody and does not pass the floor"],
  "action":  "stop the speaker for time",
  "predicted_label": "A2-1" }
```

`report.py` prints a per-code breakdown of what caused every half credit, so the three two-criterion
codes can be re-weighted or split later without re-running the judge.

**Joint score** = `ON_TIME × content score`. A `LATE` or `PREMATURE` utterance scores 0 on joint even
if its content is perfect. Timing and content are also reported separately.

---

## 4. Utterances outside any window

There are no separate negative probes. Every model utterance that belongs to no trigger window is
logged and judged against the moderator's own system prompt.

Input: the system prompt, the transcript from 20 s before to 5 s after the utterance, the utterance,
and the distance to the nearest trigger.

| verdict | meaning |
|---|---|
| `backchannel` | filler only — acceptable by default |
| `acceptable` | breaks no rule and does the debate no harm |
| `awkward` | not a rule violation, but odd or disruptive |
| `violation` | breaks a duty stated in the system prompt |

A violation means the model stopped a speaker before time, policed an interruption during the
crossfire, argued a side, declared a winner, redirected a speaker who was on the motion, or said
something that would derail the debate.

The opening format announcement and the final closing line are expected, and are **not scored**.

**Planted traps.** Each debate carries situations that look like triggers but are not: a digression
the speaker corrects without help, two claims that merely sound opposed, and an interruption during
the crossfire, where interrupting is normal. Silence is the correct answer at all three. They are
kept as region labels, so "did the model take the bait" is read off this section rather than being
scored as its own code.

---

## 5. Baselines

| baseline | what it shows |
|---|---|
| always silent | floor; every trigger `MISSED` |
| speak at every trigger deadline | timing ceiling; content still has to be earned |
| speak whenever a debater stops | **the one that matters** |

The static debater audio keeps the pauses where the reference moderator spoke, so the third baseline
is `ON_TIME` for most turn-end codes on its own. It also produces one non-trigger utterance per
crossfire turn boundary. **A2-2, A3-1, B1 and B2 must always be reported next to this baseline** —
their windows are pure silence, and without the comparison their timing scores look better than they
are. For those four codes, content is where the real difficulty sits.

---

## 6. What to report

Per code: the timing distribution, the `onset − deadline` median and IQR, the content score, the
joint score, the half-credit breakdown, and the predicted-action confusion matrix.

Per debate: the number of non-trigger utterances and their verdicts.

Always alongside: the three baselines, and `A4` and `A4xf` kept apart — they share a criterion but
not a clock, and merging them hides a 20-second task inside a 140-second one.

---

## 7. The moderator's system prompt

This is given to the model under test. 295 words. `{{MOTION}}`, `{{PRO_NAME}}` and `{{CON_NAME}}`
are filled per debate. Shipped verbatim as
[`data_sample_112/system_prompt.md`](data_sample_112/system_prompt.md).

Each scored behaviour appears as exactly one sentence, so every judgement traces to a line the model
was actually given.

| paragraph | covers |
|---|---|
| 1 | the role; silence is the default |
| 2 | the format announcement (not scored) |
| 3 | A4 · A1 · A2-1 · A2-2 · A5 |
| 4 | A3-1 · A4xf · A3-2 |
| 5 | B1 · B2 |
| 6 | the planted traps, utterance length, no side and no winner |

---

## 8. Known limitations

1. **Four codes sit in silence.** See §5. Inherent to static playback, and realistic — debaters do
   wait for the chair — but it is a cue the model can exploit.
2. **The crossfire clock depends on the model's own A3-1.** If the model never opens the crossfire,
   it has no anchor for `A4xf` and `A3-2` and can only infer it from the debaters.
3. **Both debaters share one channel.** A5 and B2 require telling the two voices apart.
4. **A4 is enforced more strictly than real chairs behave.** Only 1.7 % of real moderator turns are
   time cues, and real chairs often cut without a prior warning. Our format requires the cue.
5. **The judge is a single LLM call per utterance.** No ensemble, no human double-check.
6. **Voices are cloned TTS.** Prosody is flatter than real debate speech.

---

*Companion documents: [`history.md`](history.md) (how the benchmark was built),
[`TAXONOMY_DERIVATION.md`](TAXONOMY_DERIVATION.md) (how the nine codes were chosen),
[`skills/moderator-duplex-eval/SKILL.md`](skills/moderator-duplex-eval/SKILL.md) (how to run it).*
