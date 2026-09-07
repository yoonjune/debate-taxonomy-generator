---
name: moderator-duplex-eval
description: Evaluate a full-duplex speech model as the MODERATOR of a synthetic three-person Oxford-style debate (MOD/PRO/CON). Use when asked to run, score, or explain the moderator benchmark (data_sample/), to build the model's input from debates.jsonl + audio, to score a free-run with score_freerun.py, or to explain the nine moderator actions A1, A2-1, A2-2, A3-1, A3-2, A4, A5, B1, B2 and their timing windows.
---

# Moderator duplex eval

The model sits in the moderator's seat. The debaters' audio plays from start to end exactly as recorded. The model's own channel is open for the whole debate: nothing is forced into it, nothing is muted. We record everything it says and score two things at every point where the reference moderator spoke (a *trigger*): **when** it spoke (timing window) and **what** it said (binary content rubric). Everything it says elsewhere is logged and judged separately.

## Data (data_sample/)

| file | what |
|---|---|
| `system_prompt.md` | the prompt for the model. Replace `{{MOTION}}`, `{{PRO_NAME}}`, `{{CON_NAME}}` per debate. Crossfire length is fixed at two and a half minutes and is written in the prompt |
| `debates.jsonl` | one debate per line: `motion`, `speakers{MOD,PRO,CON}{name,gender,voice_id}`, `turns[]` (realized transcript with `start`/`end` in `audio/mix/<id>.json`), `selective` (optional codes placed in this debate), `crossfire_sec` = 150 |
| `probes.jsonl` | one trigger per line: `label` (code), `before_turn`, `t_earliest`, `t_deadline`, `t_latest`, `trigger` (turns that caused it + the reference moderator line) |
| `audio/mix/<id>.json` (+ `.wav` once synthesised) | the timeline: every turn with `start_sec`, `end_sec`, `speaker`, `text`. The **debater channel for the model = all non-MOD turns** placed at their `start_sec` (from `audio/turns/`). Until TTS runs, timings are 170-wpm plans (`debates.jsonl: timing = simulated_170wpm`) |
| `audio/turns/<id>_<i>.wav` | one file per turn (pending TTS); MOD turns are the reference answers, never fed to the model |
| `eval_rubric.json` | machine-readable windows and binary content criteria per code, and the non-trigger judge spec |
| `score_freerun.py` · `run_judge.py` · `report.py` · `baselines.py` | scorer (utterance log → timing classes + judge packets), judge runner (OpenAI-compatible model, `--yes`), aggregator (per-code table, confusion matrix), trivial baselines |
| `transcripts/<id>.txt` | human-readable script |

## The nine actions

| code | what the moderator does | when (from the debater audio) | deadline | window | content = pass if |
|---|---|---|---|---|---|
| A4 | ten-second cue | a 30 s opening/closing speech passes 20 s | speaker start + 20 | [18, 22] | says "ten seconds" |
| A4 (crossfire) | ten-second cue for the round | crossfire reaches 2:20 | crossfire start + 140 | [138, 142] | says "ten seconds" |
| A2-2 | hand over after an in-time finish | PRO finishes inside 30 s | end of PRO speech | [end, end+2] | hands over (name / other side / next) |
| A3-1 | open the crossfire | both openings done | end of CON opening | [end, end+2] | round change **and** the length (two and a half minutes) |
| A3-2 | close the crossfire, open closings | crossfire reaches 2:30 | crossfire start + 150 | [148, 152] | time is up **and** move to closings |
| A1 | cut an overrun; nobody next in this round | CON (last speaker of a round) passes 30 s | speaker start + 30 | [30, 32] | stops the speaker for time |
| A2-1 | cut an overrun, then hand over | PRO (first speaker of a round) passes 30 s | speaker start + 30 | [30, 32] | stops the speaker for time |
| A5 | block an out-of-turn interruption | the other debater cuts into an opening/closing | interruption start | [0, +2] | tells the interrupter to stop or wait |
| B1 | bring a drifting speaker back | a crossfire turn stays off the motion to its end | end of that turn | [end, end+2] | redirects the speaker back to the motion |
| B2 | point out a self-contradiction | a speaker breaks an absolute rule they stated earlier | end of the second claim | [end, end+2] | mentions both claims **and** asks them to reconcile |

Crossfire start = the moment the reference moderator finished opening it (`xf_open_sec` in the timeline). In a free run the model's own opening line ends within a few seconds of that, so for A4 (crossfire) and A3-2 report the onset−deadline distribution, not only the ON_TIME rate. A1 and A2-1 are the same 30-second cut; the code only records whether someone is next in the round (A2-1) or the round ends (A1). In openings, A1 is immediately followed by A3-1 — two triggers, two windows.

Mandatory codes appear in every debate (A4, A2-2, A3-1, A3-2); optional codes (A1, A2-1, A5, B1, B2) are placed 2–3 per debate and balanced across the set.


## What the moderator is expected to say (reference lines from the data)

| code | example reference lines |
|---|---|
| A4 (opening/closing) | "Ten seconds please." · "Well, now ten." |
| A4 (crossfire) | "Ten seconds, ten seconds." · "Ten seconds, and then closing statements." |
| A2-2 | "Okay. I want to go to Rich." · "Roger, come on in your response." |
| A3-1 |  |
| A3-2 | "And that's time. We're gonna go onto our closing round. And first up will be Miriam, you're first up, right?" · "Time's up. And now we move on to Round three. And first to make his statement in support of the motion, Steve." |
| A1 | "I'm sorry, I'm sorry. Hit time." · "Time out. Time out." |
| A2-1 | "Thank you. Time is up on that. And now Rich." · "That's time, thank you. Rima, the floor is yours." |
| A5 | "Let him reply to that please." · "Just let him finish, please." |
| B1 | "We are talking about a u.s.-china space race is good for humanity right now." · "We're talking about the practicality or the morality of whether we should erase painful and damaging memories." |
| B2 | "You said every bad memory should be erased, but you see it as for a child, a bad memory should be preserved." · "Nadine, thank you very much indeed. You said i believe gerrymandering never destroys the political center. gerrymandering destroys the political center?" |

The model does not have to match these words. Content pass = the binary criteria in the table above; `predicted_label` records which action the utterance actually performed.

## Running the model

1. Render the prompt: `system_prompt.md` with the three placeholders replaced.
2. Build the debater channel: all PRO/CON turns from `audio/turns/` at their `start_sec` (24 kHz mono). Do not include MOD turns.
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
