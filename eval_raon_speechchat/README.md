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
 "spoke": true, "spoke_at": 39.04, "audible_at": 39.04,
 "first_speech_frame": 488, "frame_rate": 12.5,
 "text": "Ten seconds left.", "wav": "probes/L000_p02/assistant.wav",
 "label": "A4", "kind": "clock",
 "t_earliest": 36.56, "t_deadline": 38.56, "t_latest": 41.56}
```

That covers the three checks in `data_sample/README.md` directly:

```python
should_speak = probe["label"] != "none"                            # -> row["spoke"]
in_time      = probe["t_earliest"] <= t <= probe["t_latest"]       # -> row["spoke_at"]
# right action                                                     -> row["text"], row["wav"]
```

The window fields are copied into every row, so scoring can join on `probe_id` alone.

**`spoke_at` and `audible_at` are different things.** `spoke_at` is the first frame in
the model's `SPEECH` state, that is when it decided to speak. `audible_at` is the first
frame whose output energy is above zero, that is when sound actually leaves it. They
usually agree, and where they do not, that is worth seeing rather than hiding. The
window is a few seconds wide, so the difference is not negligible.

Both are in seconds from the start of the probe audio, which is the same timeline as
`t_earliest`, `t_deadline` and `t_latest`, because `make_probe_audio.py` builds each
probe as `mix[:window_end]`, so sample zero of the probe wav is second zero of the
debate. No offset is needed.

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
everything lands in `out/<tag>/run_config.json`, including which sampling parameters were
overridden and which stayed official. Two settings never collide and a run describes
itself, so a later comparison does not depend on shell history.

```bash
$E run_probes.py --ckpt ... --tag sil03  --sil-penalty 0.3    # make it speak more
$E run_probes.py --ckpt ... --tag greedy --temperature 0.0
$E run_probes.py --ckpt ... --tag noref  --no-reference       # no voice conditioning
$E run_probes.py --ckpt ... --tag neg    --kinds negative     # only the silence probes
```

| group | flags |
|---|---|
| sampling | `--temperature` `--top-p` `--top-k` `--sil-penalty` `--bc-penalty` `--eos-penalty` `--speak-first` |
| model | `--ckpt` `--dtype` `--attn` |
| probe set | `--data-sample` `--probes` `--debates-file` `--system-prompt` `--probe-audio` `--voices` `--no-reference` |
| selection | `--debates` `--probe-ids` `--labels` `--kinds` `--limit` |
| output | `--out` `--tag` `--keep-stereo` |

Nothing about the probe set is hard coded, so a later version with more debates,
different windows or a rewritten prompt is a flag rather than an edit.

**Sampling defaults are the official ones.** Any flag left unset is not passed at all, so
`duplex()` falls back to `config/duplex_infer.yaml`:

```
do_sample true   temperature 0.9   top_p 0.95   top_k 66
eos_penalty 0.0  sil_penalty 0.0   bc_penalty 0.0   speak_first false
```

`sil_penalty` is the one to know about. Raising it makes the model speak sooner and more
often, which would lift recall on the 77 intervention probes and cost the 66 silence
probes at the same time. It is left at the official zero so the headline number is the
model as released. Sweeping it is a legitimate experiment and `--tag` keeps it separate.

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

**The moderator reference voice is used for speaker conditioning.** The moderator already
speaks in the probe audio in a cloned voice, and `voices/` holds the clip it came from.
Conditioning on it stops the model answering in a voice nobody in the debate has heard.
`--no-reference` drops it.

**The model hears its own past turns as input.** In the probe audio the moderator is part
of the mix, so earlier moderator turns arrive on the input channel rather than as
assistant history. That is what `make_probe_audio.py` produces and what the data README
prescribes. Injecting them as assistant history would be a different experiment and
would require modifying official code.

**The whole probe is decoded, with no early stop.** The official loop consumes the entire
input, so a probe costs its full audio length even after the model has spoken. Stopping
early would mean modifying official code, so it is left alone.
