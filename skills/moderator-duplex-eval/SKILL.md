---
name: moderator-duplex-eval
description: Evaluate a full-duplex speech model as the MODERATOR of a synthetic three-person Oxford-style debate (MOD/PRO/CON). Use when asked to run, score, or explain the moderator benchmark (data_sample_112/), to build the model's input from debates.jsonl + audio, to score a free-run with score_freerun.py, or to explain the nine moderator actions A1, A2-1, A2-2, A3-1, A3-2, A4, A5, B1, B2 and their timing windows.
---

# Moderator duplex eval

The model sits in the moderator's seat. The debaters' audio plays from start to end exactly as recorded. The model's own channel is open for the whole debate: nothing is forced into it, nothing is muted. We record everything it says and score two things at every point where the reference moderator spoke (a *trigger*): **when** it spoke (timing window) and **what** it said (binary content rubric). Everything it says elsewhere is logged and judged separately.

## Data (data_sample_112/)

| file | what |
|---|---|
| `system_prompt.md` | the prompt for the model. Replace `{{MOTION}}`, `{{PRO_NAME}}`, `{{CON_NAME}}` per debate. Crossfire length is fixed at two and a half minutes and is written in the prompt |
| `debates.jsonl` | one debate per line: `motion`, `speakers{MOD,PRO,CON}{name,gender,voice_id}`, `turns[]` (realized transcript with `start`/`end` in `audio/mix/<id>.json`), `selective` (optional codes placed in this debate), `crossfire_sec` = 150 |
| `probes.jsonl` | one trigger per line: `code`, `before_turn`, `t_earliest`, `t_deadline`, `t_latest`, `trigger` (turns that caused it + the reference moderator line), and what is audible in the window: `speech_until_sec`, `next_debater_start_sec`, `hears_in_window` |
| `audio/mix/<id>.json` + `.mp3` | the realised timeline: every turn with `start_sec`, `end_sec`, `speaker`, `text`, and the full mixed debate for listening. The **debater channel for the model = all non-MOD turns** placed at their `start_sec` (from `audio/turns/`) |
| `audio/turns/<id>_<i>.mp3` | one file per turn (24 kHz mono, 64 kbps); MOD turns are the reference answers, never fed to the model |
| `eval_rubric.json` | machine-readable windows and binary content criteria per code, and the non-trigger judge spec |
| `score_freerun.py` · `run_judge.py` · `report.py` · `baselines.py` | scorer (utterance log → timing classes + judge packets), judge runner (OpenAI-compatible model, `--yes`), aggregator (per-code table, confusion matrix), trivial baselines |
| `remix.py` | the mixing recipe as code: rebuilds `audio/mix/<id>.mp3` from the turn files and the timeline (energy correlation 1.000 with the shipped mix); `--debaters-only` writes the model's input channel (PRO/CON only, moderator slots silent) |
| `transcripts/<id>.txt` | human-readable script |
| `audio/cues/*.mp3` | three phase cues spoken by a narrator from outside the debate, reused for every debate: `cue_begin` ("Please begin the debate."), `cue_openings_over` ("The opening statements are over."), `cue_crossfire_over` ("The crossfire is over."). Each says that a phase has ended, in the system prompt's own words, so the model knows to open the next one. The voice is held out of the dataset pool, so it belongs to no debater |
| `voices/` | the cloning references (one wav per voice) and `voices.json` (gender, natural speaking rate, which debates use it) |

## The nine actions

| code | what the moderator does | when (from the debater audio) | deadline | window | content = pass if |
|---|---|---|---|---|---|
| A4 | ten-second cue | a 30 s opening/closing speech passes 20 s | speaker start + 20 | [18, 22] | says "ten seconds" |
| A4 (crossfire) | ten-second cue for the round | crossfire reaches 2:20 | crossfire start + 140 | [138, 142] | says "ten seconds" |
| A2-2 | hand over after an in-time finish | PRO finishes inside 30 s (before 20 s: no cue was given; 20–30 s: after the ten-second cue) | end of PRO speech | [end, end+2] | hands over (name / other side / next) |
| A3-1 | open the crossfire | both openings done | end of CON opening | [end, end+2] | moves on to the next round (any wording) + states the length (2:30) — **half credit for one of the two** |
| A3-2 | close the crossfire, open closings | crossfire reaches 2:30 | crossfire start + 150 | [148, 152] | moves on to the closing round (saying time is up is not required) |
| A1 | cut an overrun; nobody next in this round | CON (last speaker of a round) passes 30 s | speaker start + 30 | [30, 32] | stops the speaker for time |
| A2-1 | cut an overrun, then hand over | PRO (first speaker of a round) passes 30 s | speaker start + 30 | [30, 32] | stops the speaker for time + hands over — **half credit for one of the two** |
| A5 | block an out-of-turn interruption | the other debater cuts into an opening/closing | interruption start | [0, +2] | tells the interrupter to stop or wait |
| B1 | bring a drifting speaker back | a crossfire turn stays off the motion to its end | end of that turn | [end, end+2] | redirects the speaker back to the motion |
| B2 | point out a self-contradiction | a speaker breaks an absolute rule they stated earlier | end of the second claim | [end, end+2] | points out the self-contradiction + asks them to reconcile — **half credit for one of the two** |

Crossfire start = the moment the reference moderator finished opening it (`xf_open_sec` in the timeline). In a free run the model's own opening line ends within a few seconds of that, so for A4 (crossfire) and A3-2 report the onset−deadline distribution, not only the ON_TIME rate. A1 and A2-1 are the same 30-second cut; the code only records whether someone is next in the round (A2-1) or the round ends (A1). In openings, A1 is immediately followed by A3-1 — two triggers, two windows.

Mandatory codes appear in every debate (A4, A2-2, A3-1, A3-2); optional codes (A1, A2-1, A5, B1, B2) are placed 2–3 per debate and balanced across the set.


## What the moderator is expected to say (reference lines from the data)

| code | example reference lines |
|---|---|
| A4 (opening/closing) | "Wendy, ten seconds." · "I'll give you ten more seconds to nail this." |
| A4 (crossfire) | "You've got ten seconds." · "Ten seconds please." |
| A2-2 | "Okay. Go on, Nadine." · "Amy has the floor right now." |
| A3-1 | "Now we're gonna talk. This round runs two and a half minutes from the moment I finish. I will call ten seconds before the end." · "Great. So let's move on to the discussion portion of the debate. It runs two and a half minutes, starting the moment I stop. Go." |
| A3-2 | "Time. I'm going to jump in because we're going to go to closing statements. Now we move on to our final round. Hina, you are up first." · "And that's time. Now, we move on to round three, and round three are closing statements by each debater in turn. And making her closing statement, Annette." |
| A1 | "Thank you, Amy. Your time is up." · "I'm gonna cut you off just for time." |
| A2-1 | "You're out of time. And here to summarize her position, Genevieve." · "Thank you, your time is up. And here to summarize his position against the motion, Todd." |
| A5 | "Amy, excuse me." · "Can we let her reply please?" |
| B1 | "We're talking about the practicality or the morality of whether we should erase painful and damaging memories." · "Okay, again, it's not on our topic about grandma's benefits imperil junior's future and threaten his independence." |
| B2 | "So, so while saying I believe nuclear power should never be expanded, you're saying this reactor should be expanded now?" · "One moment you're saying I believe armed citizens always make us safer, then you're having them in a school, unarmed guards make us safer. Which?" |

The model does not have to match these words. Content pass = the binary criteria in the table above; `predicted_label` records which action the utterance actually performed.

## What the model hears during each window

The debater audio plays from start to end, so the window end (deadline + 2 s) is always inside the input. What is audible there differs by code (measured on the 30 debates):

| code | window | audible during the window |
|---|---|---|
| A4 (speech) | [18, 22] | the speaker keeps talking without a pause (4.8–11 s past the cue point); the reference cue was overlaid and is not in the input |
| A4 (crossfire) | [138, 142] | the crossfire goes on (0.2–1 s gaps between turns) |
| A3-2 | [148, 152] | the running turn fades at 150.8 s, then silence; the first closing starts +3.5–13 s later |
| A1 · A2-1 | [30, 32] | the speaker keeps talking until 31.3 s, then fades; next debater at +2.7–6.4 s (A2-1) or +11.6–17 s (A1) |
| A5 | [0, +2] | the interrupter keeps talking until at least +2.3 s, then fades; the floor-holder resumes at +3.1–5.5 s |
| A2-2 · A3-1 · B1 · B2 | [end, end+2] | silence (the gap where the reference moderator spoke); next debater turn at A2-2 +1.4–6.1 s (median 2.0) · A3-1 +8.8–16 s · B1 +3.8–9.8 s · B2 +4.8–13.5 s |

Every probe carries the exact values: `speech_until_sec` (how far debater speech continues after the deadline), `next_debater_start_sec`, `hears_in_window` (`speech` / `speech_then_silence` / `silence`). A harness that truncates the input must include audio up to at least `t_latest + 3` s (end of the LATE zone).

## Running the model

1. Render the prompt: `system_prompt.md` with the three placeholders replaced.
2. Build the debater channel: all PRO/CON turns from `audio/turns/` at their `start_sec` from `audio/mix/<id>.json` (24 kHz mono). Do not include MOD turns; leave their time as silence. `python3 remix.py <id> --debaters-only` does exactly this; `--all` for every debate.
   Optionally play `audio/cues/cue_begin.mp3` before the first debater turn, `cue_openings_over.mp3` right after the second opening ends, and `cue_crossfire_over.mp3` at crossfire start + 150 s. They are outside the debate and are never scored; report whether you used them.
3. Stream it to the model in real time. Leave the model's output channel free from 0 s to the end. Do not force silence, do not inject reference lines.
4. Log every model utterance: `{"debate_id", "start_sec", "end_sec", "text"}` — `start_sec` is the speech onset on the model channel (energy VAD: 20 ms frames, min speech 200 ms, min silence 600 ms), `text` is the model's text stream for that utterance (or ASR of its audio). One line per utterance in `utterances.jsonl`.

## Scoring

```bash
python3 score_freerun.py --probes probes.jsonl --debates debates.jsonl --utts utterances.jsonl --out scores/
python3 run_judge.py --scores scores/ --model <judge> --yes --max-calls 500   # content + non-trigger judging
python3 report.py --scores scores/                                             # per-code table, confusion matrix
python3 baselines.py --probes probes.jsonl --debates debates.jsonl --out baselines/   # then score each baseline log
```
The crossfire clock for A4 (crossfire) and A3-2 is anchored on the end of the model's own A3-1 utterance (`--anchor-xf model`, default); if the model never opened the crossfire, the reference opening end is used.

- Per trigger: first non-backchannel onset in `[deadline−5, latest+3]` → `PREMATURE` (before `t_earliest`), `ON_TIME` (inside the window), `LATE` (after `t_latest`), else `MISSED`. Backchannels (filler-only text such as mm-hm / yeah / okay, or under 0.4 s with at most one word) are never attributed; one-word moderator lines like "Time." count. Overlapping windows (A1 then A3-1) may both take the same utterance.
- Content: `scores/<id>.json` carries a judge packet per attributed utterance (code, binary criteria, trigger text, names). Give it to an LLM judge; `pass` requires every criterion. Record `predicted_label` (which action the utterance actually performed) for the confusion matrix. `joint = ON_TIME and pass`.
- Non-trigger utterances: also in `scores/<id>.json` with a judge packet (system prompt, transcript from 20 s before to 5 s after, the utterance, nearest trigger, trap label if inside a planted trap region). The format announcement before the first debater turn and the closing after the last one are logged as `opening_announcement` / `closing` and not judged. Judge: `backchannel` / `acceptable` / `awkward` / `violation` (breaks a duty in the system prompt, or would create a problem in the debate; quote the sentence).
- Report per code: timing distribution, `onset − deadline` median/IQR, content pass rate, joint rate, confusion matrix; and per debate: non-trigger utterance count and verdict distribution. Always report two baselines: always silent, and speak at every trigger deadline.

## Notes for the harness

- Both debaters share one channel. A5 and B2 require telling the two voices apart; that is part of the task.
- The debater audio keeps the pauses where the reference moderator spoke, so a hand-off point is audible as a gap. The `on_pause` baseline shows how much that gives away.
- Trap regions (`debates.jsonl: traps`) mark planted non-events: a brief digression that returns on its own, two claims that only sound opposed, an interruption inside the crossfire. Speech there is a non-trigger utterance like any other; the label just tells you what tempted the model.
