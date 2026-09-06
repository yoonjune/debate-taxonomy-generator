# MiniCPM-o 4.5 on the debate moderator probes

Runs the official MiniCPM-o 4.5 full duplex speech loop over a probe set and writes, per
probe, whether the model spoke, when, and what it said. Scoring is not done here.

This branch adds one directory and changes nothing else. The model code is the official
code, unmodified. Everything here is a driver around it, and every place where the
driver departs from the official example is marked `KHS` in a comment saying why.

## What scoring gets

One line per probe in `out/<tag>/results.jsonl`:

```json
{"probe_id": "L000_p08", "model": "MiniCPM-o-4_5",
 "spoke": true, "spoke_at": 19.0, "audible_at": 19.28,
 "segments": [{"start": 19.0, "end": 23.0, "duration": 4.0, "text": "All right, thank you..."},
              {"start": 50.0, "end": 53.0, "duration": 3.0, "text": "Time is up for Nina."},
              {"start": 80.0, "end": 87.0, "duration": 7.0, "text": "Time is up for Kirsten. Now we move to crossfire..."}],
 "n_segments": 3,
 "onset_in_window": 80.0, "nearest_onset": 80.0, "onset_offset": 0.76,
 "text": "All right, thank you... Time is up for Nina. Time is up for Kirsten...",
 "wav": "audio/L000_p08.wav",
 "label": "A3-1", "kind": "event",
 "t_earliest": 79.24, "t_deadline": 79.24, "t_latest": 82.24}
```

That covers the three checks in `data_sample/README.md`:

```python
should_speak = probe["label"] != "none"                     # -> row["spoke"]
in_time      = row["onset_in_window"] is not None           # -> or redo it from segments
# right action                                              -> row["text"], row["wav"]
```

The window fields are copied into every row, so scoring joins on `probe_id` alone.

### Read segments, not just the first onset

**A full duplex model speaks more than once in one probe, and the first time is usually
not the interesting one.** Both models here open by announcing the debate format,
because `system_prompt.md` says to do that at the start while every probe begins in the
middle of a debate where the human moderator already announced it. Scoring the opening
line would hide a correct intervention a minute later.

So every stretch of speech is recorded with its own `start`, `end` and `text`, and three
derived fields say where those onsets sit relative to the window:

| field | meaning |
|---|---|
| `onset_in_window` | the first onset inside `[t_earliest, t_latest]`, or null |
| `nearest_onset` | the onset closest to `t_deadline`, in window or not |
| `onset_offset` | `nearest_onset` minus `t_deadline`, so the sign says early or late |

`nearest_onset` is there for the boundary. In the pilot one Raon onset landed 0.08 s,
a single 80 ms frame, before `t_earliest`. Whether that counts is the scorer's call, so
the verdict and the distance are both reported rather than one of them.

`spoke_at` stays the first onset, so a reader who wants one number still gets one.

**`spoke_at` and `audible_at` are different things.** `spoke_at` is when the model
decided to speak. `audible_at` is when sound actually starts, measured from the
generated waveform, and it can be later because synthesized speech can open with
silence.

All times are seconds from the start of the probe audio, which is the same timeline as
`t_earliest`, `t_deadline` and `t_latest`, because `make_probe_audio.py` builds each
probe as `mix[:window_end]`, so sample zero of the probe wav is second zero of the
debate. Checked against the data: all 143 probe wavs are `min(t_latest + 6.0, mix
length)` long. No offset is needed.

No transcription step is involved. MiniCPM-o interleaves text and speech, so the text is
what the model itself produced, not a guess about its audio.

## Setup, from nothing

```bash
cd eval_minicpm_o_4_5

bash setup/01_conda_env.sh                  # new conda env, python 3.10
bash setup/02_clone_official.sh             # official repo at a pinned commit
bash setup/03_download_checkpoint.sh        # official checkpoint, about 20 GB

CUDA_VISIBLE_DEVICES=0 ~/miniconda3/envs/mcpmo45/bin/python \
  setup/04_smoke.py --ckpt ckpt/MiniCPM-o-4_5
```

`01_conda_env.sh` refuses to touch an environment that already exists. Override the name
with `ENV_NAME`.

The smoke step loads the model, runs a few duplex chunks on silence and prints the per
chunk cost and an estimate for a full run. It reports, it does not gate. The one line
worth reading is whether the model's own `current_time` advances by the chunk length,
since `spoke_at` is derived from the chunk index.

## Running

Probe audio first, once:

```bash
cd ../data_sample && python make_probe_audio.py && cd -
```

Then:

```bash
E=~/miniconda3/envs/mcpmo45/bin/python
CUDA_VISIBLE_DEVICES=0 $E run_probes.py --ckpt ckpt/MiniCPM-o-4_5 --limit 3   # pilot
CUDA_VISIBLE_DEVICES=0 $E run_probes.py --ckpt ckpt/MiniCPM-o-4_5             # all
```

Runs resume: rerunning skips probes already in `results.jsonl`.

## Turning the knobs

Every setting is a flag, results go to `out/<tag>/`, and the effective value of
everything lands in `out/<tag>/run_config.json`, including which generation parameters
were overridden and which stayed official. Two settings never collide and a run
describes itself, so a later comparison does not depend on shell history.

```bash
$E run_probes.py --ckpt ... --tag speak  --listen-prob-scale 0.5   # make it speak more
$E run_probes.py --ckpt ... --tag chunk05 --chunk-seconds 0.5      # finer timing
$E run_probes.py --ckpt ... --tag noref  --no-reference            # no voice conditioning
$E run_probes.py --ckpt ... --tag clock  --kinds clock             # one probe family
$E run_probes.py --ckpt ... --tag fast   --stop-at-onset           # timing only, cheaper
```

| group | flags |
|---|---|
| generation, official defaults | `--temperature` `--top-k` `--top-p` `--listen-prob-scale` `--listen-top-k` `--decode-mode` `--max-new-speak-tokens-per-chunk` `--text-repetition-penalty` |
| loop | `--chunk-seconds` `--stop-at-onset` `--max-speak-chunks` `--output-sample-rate` |
| model | `--ckpt` `--dtype` `--attn` `--with-vision` |
| probe set | `--data-sample` `--probes` `--debates-file` `--system-prompt` `--probe-audio` `--voices` `--no-reference` |
| selection | `--debates` `--probe-ids` `--labels` `--kinds` `--limit` |
| parallel | `--shard` `--num-shards` |
| output | `--out` `--tag` `--seed` |

Nothing about the probe set is hard coded, so a later version with more debates,
different windows or a rewritten prompt is a flag rather than an edit.

**Generation defaults are the official ones.** Any flag left unset is not passed at all,
so `streaming_generate` falls back to its own signature:

```
decode_mode sampling   temperature 0.7   top_k 100   top_p 0.8
listen_prob_scale 1.0  listen_top_k None  max_new_speak_tokens_per_chunk 20
text_repetition_penalty 1.05
```

`listen_prob_scale` is the one to know about. It scales the probability of choosing to
listen, so below 1.0 the model speaks sooner and more often, which lifts recall on the
77 intervention probes and costs the 66 silence probes at the same time. It is the
counterpart of Raon's `sil_penalty`. It is left official so the headline number is the
model as released, and `--tag` keeps a sweep separate.

**Official decoding samples, so two runs of the same probe differ.** In the pilot the
same probe gave `38.0 s, "20 seconds remain"` on one run and `19.0 s, continuing the
debater's argument` on another. `--seed` fixes one draw; it does not remove the spread.
Whether one run per probe is enough is a question for whoever scores this.

### Running on both gpus

```bash
CUDA_VISIBLE_DEVICES=0 $E run_probes.py --ckpt ... --shard 0 --num-shards 2 &
CUDA_VISIBLE_DEVICES=1 $E run_probes.py --ckpt ... --shard 1 --num-shards 2 &
```

Shards are taken round robin so each sees a mix of short and long probes, and each
writes `results.shard<n>.jsonl`. Scoring globs `results*.jsonl`.

## Pinned versions

| what | source | pin |
|---|---|---|
| repository | `github.com/OpenBMB/MiniCPM-o` | `f0866559fae0305bc7cacfb6a950640a927f6984` |
| checkpoint | `huggingface.co/openbmb/MiniCPM-o-4_5` | `503e754207c94da6bb26850b4469f367c9ea3582` |
| transformers | official README pin | `4.51.0` exactly |
| torch | official README range | `>=2.3.0,<=2.8.0` |
| helper package | official README | `minicpmo-utils[all]>=1.0.5` |

The model code is not in the repository. It ships inside the checkpoint and is loaded
through `trust_remote_code`, so the checkpoint is the file set a code change would
touch. It is kept pristine. If a change ever becomes necessary it goes into a sibling
overlay of symlinks with only the changed python file replaced, so a `diff` against the
pristine copy is the entire record.

## Prefill: giving the model its own past

By default the moderator's earlier turns reach the model as audio on the **input**
channel, because that is what `make_probe_audio.py` produces. The model hears its own
past as a third party and does not know it has already spoken, and it shows: both models
open every probe by announcing the debate format, since `system_prompt.md` says to do
that at the start and every probe begins mid debate where the format was already
announced. A model that follows the prompt is punished for it.

`--prefill` does the other thing. The moderator's earlier turns go into the **assistant**
channel, chunk by chunk, as if the model had generated them, and the input is rebuilt
from the debaters alone.

```bash
CUDA_VISIBLE_DEVICES=0 $E tools/build_alignments.py --out assets/alignments.json   # once
CUDA_VISIBLE_DEVICES=0 $E run_probes.py --ckpt ... --tag prefill --prefill
```

Measured on two probes of `L000`:

```
L000_p02  A4    window 36.56-41.56
  prefilled   1.0 - 18.0   "Tonight's motion is America is to blame for Mexico's drug war..."
  model      40.0          "Nina, twenty seconds remain."          in window, right speaker
  model      48.0          "Time is up."

L000_p04  A2-2  window 49.76-52.76
  prefilled   1.0 - 18.0   turn 0
  prefilled  37.0 - 41.0   "I can give you ten seconds to do this"
  model      50.0          "Time is up for the opening"            in window
```

Without prefill the same `L000_p02` run had the model at 19.0 s continuing the debater's
argument, a miss. No format re announcement appears with prefill on, because the model
knows it already did that.

### The three things it rests on

**Where each word is spoken.** `tools/build_alignments.py` force aligns every moderator
turn against its own isolated audio in `data_sample/audio/turns`, using
Qwen3-ForcedAligner. All 97 turns aligned, 1714 words, no failures. The mix cannot be
used because the moderator deliberately overlaps a debater there.

**How far ahead of its audio the model emits text: one chunk, about 1.1 s.** Measured
with `tools/measure_text_audio_offset.py` on the model's own output, 121 words over 13
segments: 69 percent at exactly minus one chunk, 21 percent at minus two. The technical
report describes TAIL assigning a text token to the chunk its start time falls in, plus
"a bounded look-ahead mechanism: the speech tokens of the last few text tokens in chunk
k are deferred to chunk k+1", but quantifies neither the deferral nor inference
behaviour, so the measured number is the one used.

**What a chunk is allowed to look like.** Read out of the released model: a silent chunk
is the single token `<|listen|>`; a speaking chunk is `<|speak|>`, then text tokens, then
`<|chunk_eos|>`, with `<|turn_eos|>` before the close on the last chunk of an utterance.
At most `max_new_speak_tokens_per_chunk` tokens fit, 20 by default, and a terminator in
the middle would end the chunk early. `prefill.validate_schedule` checks all of that
before the model is touched and refuses to run a schedule that breaks it.

### What the prefilled history is, exactly

Only the text side is forced here. The schedule says which word the model said in which
chunk, and the model generates the speech for those words itself, conditioned on the
moderator's reference clip, so the history is the right words at the right times in the
right voice, re synthesised rather than the original recording.

The Raon branch forces the audio codes as well, because its acoustic side did not
reliably follow the forced text. This one's does: every forced span measured so far came
out fully voiced, so there is nothing here for that change to fix, and its speech units
live in a different space that would need its own encoder path.

The Raon branch forces the audio codes as well, because its acoustic side did not
reliably follow the forced text. This one's does: every forced span measured so far came
out fully voiced, so there is nothing here for that change to fix, and the speech units
live in a different space that would need its own encoder path.

### The forced history has to be heard, not just written

Forcing the text does not guarantee the acoustic side follows. Measured on the model's
own output, the same forced turn came out **11 percent voiced on one draw and 93 percent
on another**, with the audio collapsing partway through and never recovering. Nothing in
the frame or chunk counts shows that: the state machine says SPEECH, the tokens are
right, and the decoder emits silence. A history the model can read but not hear is not
the experiment.

So the forced span is measured from the decoder's own output level and reported:

```json
"prefill": {"release_sec": 18.0, "release_chunk": 18, "turns_prefilled": 1,
            "voiced_overall": 1.0, "voiced_ok": true,
            "per_span": [{"start": 1.0, "samples": 408960, "voiced": 1.0}]}
```

There is no redraw here, unlike the Raon branch: this model's forced spans have not been
seen to fall short, so a draw is measured and recorded rather than repeated. `voiced_ok`
is what a run should be filtered on.

### The row describes the model, not what we forced

`spoke`, `spoke_at`, `text`, `segments` and `n_segments` all cover **only what happens
after the release point**. What we forced is in `prefilled_segments`. Without that split
`spoke` is true on every probe in prefill mode and `spoke_at` is the forced onset, which
says nothing about the model.

Everything after the last prefilled chunk is the model's own.

| flag | default | effect |
|---|---|---|
| `--prefill` | off | path to the alignments, `assets/alignments.json` when bare |
| `--lookahead-chunks` | `1` | measured; how many chunks before its audio a word's text is placed |
| `--min-voiced` | `0.5` | least of the forced history that must come out as sound |

`--stop-at-onset`, `--no-reference` and any `--chunk-seconds` other than `1.0` are
rejected when combined with `--prefill` or outright, because each of them produces a
full results file that reads like a model result: breaking at the first forced chunk,
dropping the speech decoder's prompt so nothing decodes, and buffering audio the duplex
grid cannot take.

## What a code review caught, after this was first pushed

The first version of this was published with eight defects, two of them serious. They
are listed here because the fixes are the interesting part of the design, and because
"verified" was claimed for it before the review, which was not true.

**All 66 silence probes leaked the answer.** `make_probe_audio.py` silences
`turns[before_turn]` whatever speaker holds it. The rebuilt input removed only moderator
audio, and on this data every negative probe's `before_turn` is a debater, so the
debater talked straight through the decision point. That absence of an interruption is
itself the answer, which would have made half the benchmark free. The input now drops
the answer turn whoever speaks it.

**The schedule was applied one frame early.** `init_duplex_decoding_state` calls the
wrapped function once before the frame loop, for the forced first prediction, so
counting from zero put every scheduled frame one frame ahead. Confirmed against the
frame log: a schedule with EPAD at frame 2 landed at log frame 1. The counter now starts
at minus one.

**`spoke` was true on every probe.** Only the window search filtered by the release
point; the rest of the row counted forced segments as if the model had chosen them.

**The last word of each forced turn was cut.** The lookahead was being subtracted from
the end of a turn as well as the start, but it is the offset of the text token; the
speaking phase has to last until the audio finishes.

**Nothing checked that the forced history was voiced**, and on the run that was published
it largely was not. See the section above.

The rest: a moderator turn missing from the alignments vanished from both channels
silently and is now a hard error; overlapping turns could fuse and now raise; and the
bare `--prefill` default was resolved against the working directory rather than the
file.

The lesson is narrow and worth stating. `validate_schedule` checked the part that had a
validator, and all 143 schedules passed it. The leak was in the input audio, which had
nothing checking it against `make_probe_audio.py`. The checks now cover both sides.

## What was actually run

Not the full set. Four probes of `L000` without prefill and two with, on one A6000,
seed 0, everything else official.

```
without prefill
    L000_p02  A4     window 36.56-41.56   nearest onset 19.0   (-19.56)  miss
IN  L000_p04  A2-2   window 49.76-52.76   51.0  (+1.24)   "Nina, time's up. Kirsten?"
    L000_p06  A4     window 70.6-75.6     82.0  (+9.4)    late
IN  L000_p08  A3-1   window 79.24-82.24   80.0  (+0.76)   "Time is up for Kirsten.
                                                           Now we move to crossfire..."
with prefill
IN  L000_p02  A4     window 36.56-41.56   40.0  (+1.44)   "Nina, twenty seconds remain."
IN  L000_p04  A2-2   window 49.76-52.76   50.0  (+0.24)   "Time is up for the opening"
```

Speed: 3.5 times real time without prefill, so all 143 probes would be about 1.7 hours
on one gpu.

### Two things a reader should know before comparing models

**Speaking rate confounds the timing metric.** A model that talks through half the probe
lands an onset in a five second window by luck. On these probes MiniCPM-o speaks in 4 to
16 percent of the probe, which puts the chance of a lucky hit at 5 to 12 percent. Raon
speaks in 14 to 60 percent, which puts it at 20 to 41 percent. The 66 probes where
silence is the answer are what separates the two, and none have been run yet.

**MiniCPM-o truncates its own audio context.** The log repeats
`audio_past_key_values length 1502 exceed 1500, reset.` on longer probes. The model
drops early audio, which should hurt most on `B1` and `B2`, the two codes that require
remembering what a speaker said much earlier. The size of that effect has not been
measured.

## The three departures from the official example

Each is marked `KHS` at the line it happens.

**No video.** The README's duplex example always passes video frames. This benchmark is
speech only, so `init_vision=False` and `frame_list` is empty.

**The benchmark's system prompt** instead of the example's
`"Streaming Omni Conversation."`, with the four placeholders substituted from
`debates.jsonl`.

**Stopping at the first spoken chunk.** What is measured is settled the moment
`is_listen` turns false, so nothing after the utterance is measured.

## Choices worth arguing with

**The moderator reference voice is cloned, zero shot, through both official paths.** The
clip is `voices/<MOD voice_id>.wav`, the same one the debate audio itself was cloned
from, and it goes in twice:

```python
model.prepare(prefix_system_prompt=..., ref_audio=<waveform>, prompt_wav_path=<path>)
model.streaming_generate(prompt_wav_path=<path>, ...)
```

`ref_audio` is prefilled into the context as audio embeddings, wrapped in
`<|audio_start|>` and `<|audio_end|>` after the system prompt, so the model knows what
voice it has. `prompt_wav_path` initialises the token to waveform cache, which is the
actual voice cloning for the output. Without it the model answers in a voice nobody in
the debate has heard, and with prefill on the history would be in the wrong voice too.
The reference transcript in `voices.json` is not used because neither official entry
point accepts one. `--no-reference` drops the whole thing, and each row records
`voice_id` and `ref_wav` so a reader can tell what conditioned the run.

**The model hears its own past turns as input.** In the probe audio the moderator is part
of the mix, so earlier moderator turns arrive on the input channel rather than as
assistant history. That is what `make_probe_audio.py` produces and what the data README
prescribes. Injecting them as assistant history would be a different experiment and
would require modifying official code.

**Timing resolution is the chunk length.** `is_listen` is reported once per chunk, so
`spoke_at` lands on a one second grid by default. `audible_at` is continuous because it
is measured from the waveform. `--chunk-seconds` trades resolution against cost.
