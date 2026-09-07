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
| `audio/mix/<id>.wav` + `.json` | the full debate mix and its timeline (every turn with `start_sec`, `end_sec`, `speaker`, `text`). The **debater channel for the model = all non-MOD turns** placed at their `start_sec` (use `audio/turns/`) |
| `audio/turns/<id>_<i>.wav` | one file per turn; MOD turns are the reference answers, never fed to the model |
| `eval_rubric.json` | machine-readable windows and binary content criteria per code, and the non-trigger judge spec |
| `score_freerun.py` | scorer: model utterance log → timing classes, judge packets, non-trigger list |
| `transcripts/<id>.txt` | human-readable script |

## The nine actions

| code | when (from the debater audio) | deadline | window | content = pass if |
|---|---|---|---|---|
| A4 | a 30 s opening/closing speech passes 20 s | speaker start + 20 | [18, 22] | says "ten seconds" |
| A4 (crossfire) | crossfire reaches 2:20 | crossfire start + 140 | [138, 142] | says "ten seconds" |
| A2-2 | PRO finishes inside 30 s | end of PRO speech | [end, end+2] | hands over (name / other side / next) |
| A3-1 | both openings done | end of CON opening | [end, end+2] | round change **and** the length (two and a half minutes) |
| A3-2 | crossfire reaches 2:30 | crossfire start + 150 | [148, 152] | time is up **and** move to closings |
| A1 | CON (last speaker of a round) passes 30 s | speaker start + 30 | [30, 32] | stops the speaker for time |
| A2-1 | PRO (first speaker of a round) passes 30 s | speaker start + 30 | [30, 32] | stops the speaker for time |
| A5 | the other debater cuts into an opening/closing | interruption start | [0, +2] | tells the interrupter to stop or wait |
| B1 | a crossfire turn stays off the motion to its end | end of that turn | [end, end+2] | redirects the speaker back to the motion |
| B2 | a speaker breaks an absolute rule they stated earlier | end of the second claim | [end, end+2] | mentions both claims **and** asks them to reconcile |

Crossfire start = the moment the reference moderator finished opening it (`xf_open_sec` in the timeline). In a free run the model's own opening line ends within a few seconds of that, so for A4 (crossfire) and A3-2 report the onset−deadline distribution, not only the ON_TIME rate. A1 and A2-1 are the same 30-second cut; the code only records whether someone is next in the round (A2-1) or the round ends (A1). In openings, A1 is immediately followed by A3-1 — two triggers, two windows.

Mandatory codes appear in every debate (A4, A2-2, A3-1, A3-2); optional codes (A1, A2-1, A5, B1, B2) are placed 2–3 per debate and balanced across the set.

## Running the model

1. Render the prompt: `system_prompt.md` with the three placeholders replaced.
2. Build the debater channel: all PRO/CON turns from `audio/turns/` at their `start_sec` (24 kHz mono). Do not include MOD turns.
3. Stream it to the model in real time. Leave the model's output channel free from 0 s to the end. Do not force silence, do not inject reference lines.
4. Log every model utterance: `{"debate_id", "start_sec", "end_sec", "text"}` — `start_sec` is the speech onset on the model channel (energy VAD: 20 ms frames, min speech 200 ms, min silence 600 ms), `text` is the model's text stream for that utterance (or ASR of its audio). One line per utterance in `utterances.jsonl`.

## Scoring

```bash
python3 score_freerun.py --probes probes.jsonl --debates debates.jsonl --utts utterances.jsonl --out scores/
```

- Per trigger: first non-backchannel onset in `[deadline−5, latest+3]` → `PREMATURE` (before `t_earliest`), `ON_TIME` (inside the window), `LATE` (after `t_latest`), else `MISSED`. Backchannels (filler-only text such as mm-hm / yeah / okay, or under 0.4 s with at most one word) are never attributed; one-word moderator lines like "Time." count. Overlapping windows (A1 then A3-1) may both take the same utterance.
- Content: `scores/<id>.json` carries a judge packet per attributed utterance (code, binary criteria, trigger text, names). Give it to an LLM judge; `pass` requires every criterion. Record `predicted_label` (which action the utterance actually performed) for the confusion matrix. `joint = ON_TIME and pass`.
- Non-trigger utterances: also in `scores/<id>.json` with a judge packet (system prompt, ±20 s context, the utterance). Judge: `backchannel` / `acceptable` / `awkward` / `violation` (breaks a duty in the system prompt, or would create a problem in the debate; quote the sentence).
- Report per code: timing distribution, `onset − deadline` median/IQR, content pass rate, joint rate, confusion matrix; and per debate: non-trigger utterance count and verdict distribution. Always report two baselines: always silent, and speak at every trigger deadline.

## Notes for the harness

- The old probe-replay mode (teacher-force the reference moderator up to a release point, then free-run one trigger) still works with the same files and gives cleaner per-code timing; the free-run above is the primary protocol.
- Both debaters share one channel. A5 and B2 require telling the two voices apart; that is part of the task.
- `make_probe_audio.py` builds per-trigger clips for the replay mode; it is not needed for the free-run.
