# Raon-SpeechChat 9B on the debate moderator probes

Runs the official Raon-SpeechChat full duplex path over a probe set and writes, per
probe, whether the model spoke, when, and what it said. Scoring is not done here.

This branch adds one directory and changes nothing else. The official code is called,
not modified: `RaonPipeline.duplex` already accepts a system prompt and a speaker
reference wav, and every sampling parameter is left at the value in the official
`config/duplex_infer.yaml`.

## What scoring gets

One line per probe in `out/<tag>/results.jsonl`:

```json
{"probe_id": "L000_p02", "model": "Raon-SpeechChat-9B",
 "spoke": true, "spoke_at": 0.08, "audible_at": 0.08,
 "segments": [{"start": 0.08, "end": 0.96, "duration": 0.88, "text": "Okay", "is_backchannel": true},
              {"start": 18.4, "end": 21.44, "duration": 3.04, "text": "Gotcha I'll start the countdown", "is_backchannel": false},
              {"start": 37.76, "end": 41.6, "duration": 3.84, "text": "Kirsten has 30 seconds to respond.", "is_backchannel": false}],
 "n_segments": 3, "speech_frames": 96, "frame_rate": 12.5,
 "onset_in_window": 37.76, "nearest_onset": 37.76, "onset_offset": -0.8,
 "text": "Gotcha I'll start the countdown Kirsten has 30 seconds to respond.",
 "wav": "probes/L000_p02/assistant.wav",
 "label": "A4", "kind": "clock",
 "t_earliest": 36.56, "t_deadline": 38.56, "t_latest": 41.56}
```

That covers the three checks in `data_sample/README.md`:

```python
should_speak = probe["label"] != "none"                     # -> row["spoke"]
in_time      = row["onset_in_window"] is not None           # -> or redo it from segments
# right action                                              -> row["text"], row["wav"]
```

The window fields are copied into every row, so scoring joins on `probe_id` alone.

### Read segments, not just the first onset

**A full duplex model speaks many times in one probe, and the first time is not the
interesting one.** Raon opens by announcing the debate format, because
`system_prompt.md` says to do that at the start while every probe begins in the middle
of a debate where the human moderator already announced it. Measured on three probes:
taking the first onset alone puts **0 of 3** in the window; reading the segment list
puts **2 of 3** in it. Same run, same data, different field.

| field | meaning |
|---|---|
| `onset_in_window` | the first onset inside `[t_earliest, t_latest]`, or null |
| `nearest_onset` | the onset closest to `t_deadline`, in window or not |
| `onset_offset` | `nearest_onset` minus `t_deadline`, so the sign says early or late |

`nearest_onset` is there for the boundary. One onset landed 0.08 s, a single frame,
before `t_earliest`. Whether that counts is the scorer's call, so the verdict and the
distance are both reported rather than one of them.

### Backchannels are flagged and excluded

Raon has an explicit backchannel state and the token appears in the frame log. A
backchannel is `mm-hmm` while somebody else holds the floor. **It is not a moderator
intervention**, and on one pilot probe 8 of 16 segments were backchannels, so counting
them would make every probe look like the model spoke. Segments carry `is_backchannel`
and are left out of the onset search. `--count-backchannels` puts them back.

**`spoke_at` and `audible_at` are different things.** `spoke_at` is the first frame in
the model's `SPEECH` state, when it decided to speak. `audible_at` is the first frame
with output energy, when sound actually leaves it. They usually agree, and where they do
not, that is worth seeing rather than hiding.

All times are seconds from the start of the probe audio, which is the same timeline as
`t_earliest`, `t_deadline` and `t_latest`, because `make_probe_audio.py` builds each
probe as `mix[:window_end]`, so sample zero of the probe wav is second zero of the
debate. Checked against the data: all 143 probe wavs are `min(t_latest + 6.0, mix
length)` long. No offset is needed.

No transcription step is involved. Raon interleaves text and speech, so the text is what
the model itself produced, not a guess about its audio.

## Where the timing comes from

The official duplex loop writes a frame log, one line per frame:

```
[SIL]    f=487 text=- out_rms=0.0000 in_rms=0.0141 ntok=2
[SPEECH] f=488 text='Ten' out_rms=0.0512 in_rms=0.0139 ntok=3
```

`SIL` and `SPEECH` are the two states of the model's own duplex state machine, and the
model runs at 12.5 frames per second, so timing lands on an **80 ms** grid. The frame
rate is read from `pipe.processor.frame_rate`, not hard coded, so a checkpoint with a
different rate cannot silently rescale every timestamp.

## Setup, from nothing

```bash
cd eval_raon_speechchat

bash setup/01_conda_env.sh                  # new conda env, python 3.11
bash setup/02_clone_official.sh             # official repo at a pinned commit
bash setup/03_download_checkpoint.sh        # official checkpoint, about 19.5 GB

CUDA_VISIBLE_DEVICES=1 ~/miniconda3/envs/raon/bin/python \
  setup/04_smoke.py --ckpt ckpt/Raon-SpeechChat-9B
```

`01_conda_env.sh` refuses to touch an environment that already exists. Override the name
with `ENV_NAME`.

The smoke step runs one duplex pass on ten seconds of silence and prints the speed and
an estimate for a full run. It reports, it does not gate. The one line worth reading is
whether the frame count matches audio length times frame rate, since `spoke_at` is a
frame index divided by that rate.

## Running

Probe audio first, once:

```bash
cd ../data_sample && python make_probe_audio.py && cd -
```

Then:

```bash
E=~/miniconda3/envs/raon/bin/python
CUDA_VISIBLE_DEVICES=1 $E run_probes.py --ckpt ckpt/Raon-SpeechChat-9B --limit 3  # pilot
CUDA_VISIBLE_DEVICES=1 $E run_probes.py --ckpt ckpt/Raon-SpeechChat-9B            # all
```

Runs resume: rerunning skips probes already in `results.jsonl`.

## Turning the knobs

Every setting is a flag, results go to `out/<tag>/`, and the effective value of
everything lands in `out/<tag>/run_config.json`, including which sampling parameters
were overridden and which stayed official.

```bash
$E run_probes.py --ckpt ... --tag sil03  --sil-penalty 0.3      # make it speak more
$E run_probes.py --ckpt ... --tag noref  --no-reference         # no voice conditioning
$E run_probes.py --ckpt ... --tag neg    --kinds negative       # only the silence probes
$E run_probes.py --ckpt ... --tag withbc --count-backchannels   # backchannels count
```

| group | flags |
|---|---|
| sampling, official defaults | `--temperature` `--top-p` `--top-k` `--sil-penalty` `--bc-penalty` `--eos-penalty` `--speak-first` |
| model | `--ckpt` `--dtype` `--attn` `--decoder-timeout` `--no-warmup` |
| probe set | `--data-sample` `--probes` `--debates-file` `--system-prompt` `--probe-audio` `--voices` `--no-reference` |
| selection | `--debates` `--probe-ids` `--labels` `--kinds` `--limit` |
| parallel | `--shard` `--num-shards` |
| output | `--out` `--tag` `--seed` `--keep-stereo` `--count-backchannels` |

Nothing about the probe set is hard coded, so a later version with more debates,
different windows or a rewritten prompt is a flag rather than an edit.

**Sampling defaults are the official ones.** Any flag left unset is not passed at all,
so `duplex()` falls back to `config/duplex_infer.yaml`:

```
do_sample true   temperature 0.9   top_p 0.95   top_k 66
eos_penalty 0.0  sil_penalty 0.0   bc_penalty 0.0   speak_first false
```

`sil_penalty` is the one to know about. Raising it makes the model speak sooner and more
often, which lifts recall on the 77 intervention probes and costs the 66 silence probes
at the same time. It is left at the official zero so the headline number is the model as
released, and `--tag` keeps a sweep separate.

**Official decoding samples, so two runs of the same probe differ.** `--seed` fixes one
draw; it does not remove the spread. Whether one run per probe is enough is a question
for whoever scores this.

### Running on both gpus

```bash
CUDA_VISIBLE_DEVICES=0 $E run_probes.py --ckpt ... --shard 0 --num-shards 2 &
CUDA_VISIBLE_DEVICES=1 $E run_probes.py --ckpt ... --shard 1 --num-shards 2 &
```

Shards are taken round robin so each sees a mix of short and long probes, and each
writes `results.shard<n>.jsonl`. Scoring globs `results*.jsonl`. This matters here
because the full set takes about 22 hours on one gpu.

## Prefill: giving the model its own past

By default the moderator's earlier turns reach the model as audio on the **input**
channel, because that is what `make_probe_audio.py` produces. The model hears its own
past as a third party and does not know it has already spoken, and it shows: both models
open every probe by announcing the debate format, since `system_prompt.md` says to do
that at the start and every probe begins mid debate where the format was already
announced. A model that follows the prompt is punished for it.

`--prefill` does the other thing. The moderator's earlier turns go into the **assistant**
channel, frame by frame, as if the model had generated them, and the input is rebuilt
from the debaters alone.

```bash
CUDA_VISIBLE_DEVICES=1 $E tools/build_alignments.py --out assets/alignments.json   # once
CUDA_VISIBLE_DEVICES=1 $E run_probes.py --ckpt ... --tag prefill --prefill
```

Measured on `L000_p02`, label `A4`, window 36.56 to 41.56:

```
without prefill   37.76  "Kirsten has 30 seconds to respond. Kirsten to rebuttal!"
                         in window, but it is Nina who is speaking

with prefill      0.08 - 19.20  [prefilled] "Tonight's motion is America is to blame
                                 for Mexico's drug war Nina argues for it and Kirsten
                                 argues against it Each debater gets thirty seconds..."
                  39.20  "20 seconds remaining for Nina."
                         in window, right action, right speaker, and no format
                         re announcement because it knows it already did that
```

### The three numbers it rests on

**Where each word is spoken.** `tools/build_alignments.py` force aligns every moderator
turn against its own isolated audio in `data_sample/audio/turns`, using
Qwen3-ForcedAligner. All 97 turns aligned, 1714 words, no failures. The mix cannot be
used because the moderator deliberately overlaps a debater there.

**How far ahead of its audio the model emits text: three frames, 240 ms.** Measured with
`tools/measure_text_audio_offset.py` on the model's own output, 292 words over 28 speech
runs: 47 percent at exactly minus three frames, 26 percent at minus two, 12 percent at
minus four, and the median does not move between the first word of an utterance and the
later ones. The technical report says "one-frame text lookahead" for a training stage,
which is a statement about how speech tokens are conditioned rather than about the
distance to audible audio, so the measured number is the one used.

**What the token stream is allowed to look like.** Read out of the released model's own
`DuplexStateManager.apply_logit_mask`, not the paper:

```
SIL phase                  SIL, EPAD or BC
SPEECH, last was EPAD/BC   a real text token only
SPEECH, last was text      text, PAD, EPAD or SIL
SPEECH, last was PAD       PAD, EPAD or SIL, and no text
```

That last line is the one that matters. **A text token cannot follow a PAD frame**, so
every word that resumes after a pause needs `EPAD` immediately before it. `EPAD` is what
the report calls `BOW`, "a special token emitted immediately before each assistant text
token". A schedule that gets this wrong is not rejected, it is masked to negative
infinity along with everything else and the model emits whatever index zero happens to
be, which reads as fluent nonsense. That is exactly what the first attempt produced:

```
before the grammar was right   "Tonight's碼", "ۦzł blame", "Ire gekanium尺 anden江门"
after                          "Tonight's motion is America is to blame for Mexico's..."
```

`prefill.validate_schedule` walks that grammar over every schedule before the model is
touched, and all 143 probes pass. It refuses to run one that does not.

### The resulting schedule

```
SIL SIL ... SIL   EPAD w1 PAD PAD   EPAD w2 PAD   EPAD w3 ...   SIL SIL
                  ^ onset            ^ every word after a pause needs its own
```

### What the prefilled history is, exactly

Both the text and the audio are forced. The schedule says which word the model said on
which frame, and the moderator's real recording is encoded with the model's own audio
tokenizer so the codes it "produced" are the original waveform, not a re synthesis.

Forcing only the text was tried first and is still available as `--no-force-audio-codes`.
It leaves the acoustic side to the model, and the model does not reliably follow: over
six draws of one eighteen second turn the forced span came out 11 to 94 percent voiced,
median 43, collapsing partway through and never recovering. With the codes forced the
first draw was 89 percent, the remainder being the pauses in the recording itself.

### The forced history has to be heard, not just written

Forcing the text does not guarantee the acoustic side follows. Measured on the model's
own output, the same forced turn came out **11 percent voiced on one draw and 93 percent
on another**, with the audio collapsing partway through and never recovering. Nothing in
the frame or chunk counts shows that: the state machine says SPEECH, the tokens are
right, and the decoder emits silence. A history the model can read but not hear is not
the experiment.

So the forced span is measured from the decoder's own output level and reported:

```json
"prefill": {"release_sec": 18.48, "turns_prefilled": 1,
            "voiced_overall": 0.93, "voiced_ok": true, "attempts": 2,
            "per_turn": [{"turn": 0, "frames": 232, "voiced": 0.93}]}
```

A draw below `--min-voiced` is discarded and redrawn, up to `--prefill-retries`. A probe
that never clears the bar is kept with `voiced_ok` false rather than silently counted,
so a run can be filtered on it.

### The row describes the model, not what we forced

`spoke`, `spoke_at`, `text`, `segments` and `n_segments` all cover **only what happens
after the release point**. What we forced is in `prefilled_segments`. Without that split
`spoke` is true on every probe in prefill mode and `spoke_at` is the forced onset, which
says nothing about the model.

Everything after the last prefilled frame is the model's own.

| flag | default | effect |
|---|---|---|
| `--prefill` | off | path to the alignments, `assets/alignments.json` when bare |
| `--lookahead-frames` | `3` | measured; `1` reproduces the paper's training stage number |
| `--force-audio-codes` | on | force the real recording's audio codes as well as the text |
| `--min-voiced` | `0.5` | least of the forced history that must come out as sound |
| `--prefill-retries` | `2` | redraws allowed before a probe is kept with `voiced_ok` false |

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
IN  L000_p02  A4     window 36.56-41.56   onset 37.76 (-0.8)
IN  L000_p04  A2-2   window 49.76-52.76   onset 49.68 (-0.08)  20 segments, 8 backchannel
IN  L000_p06  A4     window 70.6-75.6     onset 70.8  (-1.8)
IN  L000_p08  A3-1   window 79.24-82.24   onset 79.92 (+0.68)

with prefill
IN  L000_p02  A4     window 36.56-41.56   onset 39.20 (+0.64)  "20 seconds remaining for Nina."
```

Speed: 0.27 times real time, so all 143 probes would be about 22 hours on one gpu, or
about 11 on two.

### Do not read a high in window count as a score

**Speaking rate confounds the timing metric.** Without prefill Raon speaks in 14 to 60
percent of each probe, so an onset lands in a five second window by luck fairly often:
20 to 41 percent on those four, against 5 to 12 percent for MiniCPM-o. The 66 probes
where silence is the answer are what separates the two, and none have been run yet.
Ranking on intervention probes alone rewards whichever model talks more.

## Pinned versions

| what | source | pin |
|---|---|---|
| repository | `github.com/krafton-ai/Raon-Speech` | `afec41185e27653aa905d4ad28a7b8497681275e` |
| checkpoint | `huggingface.co/KRAFTON/Raon-SpeechChat-9B` | `a8bac78f596839edde5fb977fa435abf52a07a2b` |
| transformers | official requirements | `>=4.57.1,<5.0` |
| python | official requirements | `>=3.11` |

The duplex implementation is not in the repository. It ships inside the checkpoint as
`modeling_raon.py` and is loaded through `trust_remote_code`, which is why the driver
resolves `RaonPipeline` out of the checkpoint directly, the way Option A of the official
duplex example notebook does. The repository is cloned for its official inference
defaults and its example, both of which this branch follows.

## Choices worth arguing with

**The moderator reference voice is cloned, zero shot.** The clip is
`voices/<MOD voice_id>.wav`, the same one the debate audio itself was cloned from, and
it is passed as `speaker_audio` to `duplex()`, which loads it and computes a speaker
embedding that goes into the decoding state. Without it the model answers in a voice
nobody in the debate has heard, and with prefill on the history would be in the wrong
voice too. The reference transcript in `voices.json` is not used because the official
entry point does not accept one. `--no-reference` drops it, and each row records
`voice_id` and `ref_wav` so a reader can tell what conditioned the run.

**The model hears its own past turns as input.** In the probe audio the moderator is part
of the mix, so earlier moderator turns arrive on the input channel rather than as
assistant history. That is what `make_probe_audio.py` produces and what the data README
prescribes. Injecting them as assistant history would be a different experiment and
would require modifying official code.

**The whole probe is decoded, with no early stop.** The official loop consumes the entire
input, so a probe costs its full audio length even after the model has spoken. Stopping
early would mean modifying official code, so it is left alone.
