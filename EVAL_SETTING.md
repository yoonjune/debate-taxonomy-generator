# Evaluation setting — final

The benchmark puts a full-duplex speech model in the **moderator's seat** of a three-person
Oxford-style debate and asks two questions at every scored moment: **did it speak at the right
time**, and **did it say the right thing**.

Timing is decided by rule. Content is decided by an LLM judge. Nothing else is scored.

- Package: [`data_sample_112/`](data_sample_112/) — 251 debates, 2,383 scored triggers, 4.6–5.5 min each.
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

**What the model hears inside a window.** For A1, A2-1, A3-2 and the crossfire cue the speaker is
still mid-sentence at the deadline and the audio keeps running into the window, then fades shortly
after it: the reference moderator cut them there, and the mix reproduces that cut rather than
letting the speech run on. The per-code figures are in the table below, and every probe carries
`speech_until_sec` and `hears_in_window` so a harness can check exactly what was audible. A2-2,
A3-1, B1 and B2 are the opposite by design — the speaker genuinely finished, so the window is
silence.

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
| `A4` | ten-second cue, opening/closing | speaker start + 20 s | −2 … +2 | speech continues throughout | 605 |
| `A4xf` | ten-second cue, crossfire | crossfire start + 140 s | −2 … +2 | crossfire continues | 251 |
| `A2-2` | hand over after an in-time finish | end of PRO's speech | 0 … +2 | silence where the reference moderator spoke | 378 |
| `A3-1` | open the crossfire | end of CON's opening | 0 … +2 | silence | 251 |
| `A3-2` | close the crossfire, open closings | crossfire start + 150 s | −2 … +2 | speech, cut inside the window | 251 |
| `A1` | cut an overrun, nobody next this round | speaker start + 30 s | 0 … +2 | speech, cut inside the window | 131 |
| `A2-1` | cut an overrun, then hand over | speaker start + 30 s | 0 … +2 | speech, cut inside the window | 124 |
| `A5` | block an out-of-turn interruption | interruption start | 0 … +2 | the interrupter keeps talking | 121 |
| `B1` | bring a drifting speaker back | end of the drifting turn | 0 … +2 | silence | 132 |
| `B2` | point out a self-contradiction | end of the contradicting turn | 0 … +2 | silence | 139 |

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
You judge one line from a debate moderator. Content only, never timing or style.
Given the situation and the rule, did the line do what it had to do? If it read the
situation wrong and did something else instead, say what. Credit only what the line
actually says. JSON only.
```

The user message is a plain readable transcript, not nested JSON: the five turns before
the line, the line itself marked so it cannot be mistaken, then the situation and the rule.

```
--- transcript ---
MOD (Patrick): Your time is up. Thank you. Nate.
CON (Nate): This motion asks us to reject confidence entirely, but Bahrain's record …
MOD (Patrick): Ten.
CON (Nate): Carissa treats imperfect progress as proof of bad faith … a framework for-
MOD (Patrick): I have to step in because we hit our time limit.
MOD (Patrick): Alright, let's move on to the discussion portion.      <<< judge this line

Situation: Both opening statements are done.
Rule — the moderator had to:
  1. announces that the debate moves on to the next round (any wording)
  2. states the length (two and a half minutes)
```

The five turns of context matter: in the example above they show that the moderator had
just cut the speaker off, which a bare list of debater turns would hide.

The judge answers with one verdict per rule and, when the line did something else
entirely, its own words for what that was.

```json
{ "met":     [true, false],
  "why":     ["says let's move on to the discussion portion", "no length stated"],
  "misread": "" }
```

**`misread` replaces the old action label.** The judge is given no list of actions, so the
expected answer cannot anchor the verdict; it writes in free text what the line did instead,
and mapping that to a code happens afterwards. A line that cut an in-time speaker where a
hand-off was due comes back as `"treated an in-time finish as an overrun and cut the speaker
instead of handing over"` — which separates *misreading the situation* from *failing the rule*.

**What the judge is deliberately not given.** The reference moderator's line, and any list of
the actions it could name. Either one lets the expected answer pull the verdict.

**Judge model.** `gpt-5.6-luna`, 400 completion tokens, output forced by a strict JSON schema.
Fixed in `eval_rubric.json["judge_model"]` so a run with a different judge is visible in the report.

### 3.2 The part that changes per code

The `criteria` array is the whole per-code specification.

| code | `criteria` sent to the judge | max |
|---|---|--:|
| `A4` | `says that ten seconds remain (the word 'ten')` | 1 |
| `A4xf` | `says that ten seconds remain (the word 'ten')` | 251 |
| `A2-2` | `hands the floor to the other side (name, side, or 'next')` | 1 |
| `A3-1` | `announces that the debate moves on to the next round (any wording)`<br>`states the length (two and a half minutes)` | 2 |
| `A3-2` | `moves the debate on to the closing round` | 251 |
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

### 4.1 Barge-in and delayed-action diagnostics

These are reported separately and never change the primary timing, content, or joint scores above.
A **barge-in** is a non-backchannel model utterance whose speech onset falls inside an audible
debater-speech interval. Count utterances, not audio chunks or overlap spans. A model utterance that
starts in silence and is later overlapped by the next debater is not a model barge-in. Backchannels
that begin over debater speech are reported separately; one-word moderator actions such as
`"Time."` remain interventions and are included.

For every barge-in, retain its existing trigger match, timing class, content score, and non-trigger
verdict, then report these disjoint diagnostic groups:

- **on-time required and correct**: matched to an expected trigger, `ON_TIME`, and content score 1;
- **late required and correct**: matched to an expected trigger, `LATE`, and content score 1;
- **premature but content-correct**: matched, `PREMATURE`, and content score 1;
- **other matched barge-in**: matched but content score below 1, broken down by timing class;
- **other contextually acceptable barge-in**: unmatched, not a delayed action below, and judged
  `acceptable` under the non-trigger rubric;
- **other awkward or violating barge-in**: unmatched and judged `awkward` or `violation`.

The normal `LATE` allowance ends at `t_latest + 3 s`. To expose a required action that arrives even
later, also run a secondary **stale required action** diagnostic on unmatched barge-ins. Compare the
utterance only with the most recent earlier missed trigger, and call it stale only when it satisfies
all of that trigger's content criteria and occurs before the earlier of the phase boundary or the
next trigger requiring the same action. This diagnostic must not rematch the utterance, change the
earlier trigger from `MISSED`, or give primary-score credit.

Report **delayed required and correct** as the two components `late required and correct` and
`stale required action`, rather than collapsing them into one opaque count. For a runtime that
pauses or skips input, map model onset and debater-speech intervals into the same source clock before
computing these groups.

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

Also report the barge-in diagnostics from §4.1: total non-backchannel barge-ins and their rate among
non-backchannel model utterances; backchannels over debater speech; on-time required-and-correct;
late required-and-correct; stale required actions; premature-but-content-correct; other matched;
other contextually acceptable; and other awkward or violating. Keep counts and denominators visible.

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
7. **The cut codes go quiet inside their window.** A1 and A2-1 fade about 0.7 s before the window
   closes and A3-2 about 1.2 s before, because the mix cuts the speaker where the reference
   moderator cut them. A model answering at the very end of the window is therefore talking over
   silence rather than over speech. This is the reference behaviour and was left as is; read the
   `LATE` rates for those codes with it in mind.

---

*Companion documents: [`history.md`](history.md) (how the benchmark was built),
[`TAXONOMY_DERIVATION.md`](TAXONOMY_DERIVATION.md) (how the nine codes were chosen),
[`skills/moderator-duplex-eval/SKILL.md`](skills/moderator-duplex-eval/SKILL.md) (how to run it).*
