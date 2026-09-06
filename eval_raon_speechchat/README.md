# Raon-SpeechChat 9B on the debate moderator probes

Runs the official Raon-SpeechChat full duplex path over `data_sample`, and records for
every probe whether the model spoke and when.

This branch adds one directory and changes nothing else in the repository. The official
code is called, not modified: `RaonPipeline.duplex` already accepts a system prompt and
a speaker reference wav, and every sampling parameter is left at the value in the
official `config/duplex_infer.yaml`. The driver passes the two things the benchmark
defines and nothing else.

## What it produces

One line per probe in `out/raon_speechchat/results.jsonl`:

```json
{"probe_id": "L000_p02", "model": "Raon-SpeechChat-9B", "spoke": true, "spoke_at": 39.04,
 "first_speech_frame": 488, "first_audio_at": 39.04, "text": "Ten seconds left.",
 "wav": "probes/L000_p02/assistant.wav", "frame_rate": 12.5,
 "label": "A4", "kind": "clock",
 "t_earliest": 36.56, "t_deadline": 38.56, "t_latest": 41.56}
```

`spoke_at` is in seconds from the start of the probe audio, which is the same timeline
as `t_earliest`, `t_deadline` and `t_latest`, because `make_probe_audio.py` builds each
probe as `mix[:window_end]` and so sample zero of the probe wav is second zero of the
debate. It can be compared to the window with no offset:

```python
should_speak = probe["label"] != "none"
in_time      = probe["t_earliest"] <= row["spoke_at"] <= probe["t_latest"]
```

Scoring is not done here. This branch only produces the two numbers scoring needs.

## Where the timing comes from

The official duplex loop writes a frame log with one line per frame:

```
[SIL]    f=487 text=- out_rms=0.0000 in_rms=0.0141 ntok=2
[SPEECH] f=488 text='Ten' out_rms=0.0512 in_rms=0.0139 ntok=3
```

`SIL` and `SPEECH` are the two states of the model's own duplex state machine, and the
model runs at 12.5 frames per second, so the first `SPEECH` frame gives `spoke_at` to
within 80 ms. The frame rate is read from `pipe.processor.frame_rate` rather than hard
coded, so a checkpoint with a different rate cannot silently rescale every timestamp.

`first_audio_at`, the first frame whose output energy is above zero, is recorded next to
it as an independent check. The two should agree. A results file where they do not is a
reason to look again before the numbers are used, which is why both are kept rather
than only the one that is scored.

## Setup, from nothing

Four steps. Each is idempotent, so a rerun after an interruption is safe.

```bash
cd eval_raon_speechchat

bash setup/01_conda_env.sh                  # new conda env, python 3.11
bash setup/02_clone_official.sh             # official repo at a pinned commit
bash setup/03_download_checkpoint.sh        # official checkpoint, about 19.5 GB

CUDA_VISIBLE_DEVICES=1 ~/miniconda3/envs/raon/bin/python \
  setup/04_verify.py --ckpt ckpt/Raon-SpeechChat-9B
```

`01_conda_env.sh` refuses to touch an environment that already exists. This machine is
shared, so it creates `raon` or stops. Override with `ENV_NAME`.

Step 4 is not decoration. It runs a real duplex pass on ten seconds of silence and
checks that the number of frames in the log matches the audio length times the frame
rate. If it does not, every timestamp this branch produces is scaled wrong, and the
script exits rather than letting a run start. It also measures the speed and prints an
estimate for the whole set.

## Pinned versions

Nothing floats. These are the exact official artifacts this branch was written against.

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

## Running

Probe audio first, once, from the data directory:

```bash
cd ../data_sample && python make_probe_audio.py && cd -
```

Then a pilot before the full set, always:

```bash
CUDA_VISIBLE_DEVICES=1 ~/miniconda3/envs/raon/bin/python run_probes.py \
  --ckpt ckpt/Raon-SpeechChat-9B --out out/raon_speechchat --limit 3
```

Then everything:

```bash
CUDA_VISIBLE_DEVICES=1 ~/miniconda3/envs/raon/bin/python run_probes.py \
  --ckpt ckpt/Raon-SpeechChat-9B --out out/raon_speechchat
```

It resumes: rerunning skips probes already in `results.jsonl`.

| flag | default | what it does |
|---|---|---|
| `--keep-stereo` | off | keep the official stereo mix of user and assistant, about 14 MB per probe |
| `--attn` | `sdpa` | `sdpa`, `eager` or `fa` for FlashAttention 2 |
| `--limit` | `0` | pilot on the first N probes |
| `--debates` | all | restrict to given debate ids |

## Sampling parameters are the official ones

`duplex()` falls back to the values in `config/duplex_infer.yaml` for every parameter
this driver does not pass, and this driver passes none of them:

```
do_sample true   temperature 0.9   top_p 0.95   top_k 66
eos_penalty 0.0  sil_penalty 0.0   bc_penalty 0.0   speak_first false
```

`sil_penalty` is worth knowing about. Raising it makes the model speak sooner and more
often, which would raise recall on the intervention probes and destroy the silence
probes at the same time. It is left at the official zero so the number measured is the
model as released. Changing it is a legitimate experiment, but it is a different one and
should be reported as such.

## Choices worth arguing with

**The moderator reference voice is used for speaker conditioning.** The moderator
already speaks in the probe audio in a particular cloned voice, and `voices/` holds the
clip it was cloned from. Conditioning on it stops the model from answering in a voice
nobody in the debate has heard. This is a choice, not a requirement of the benchmark,
and passing no reference is a one line change.

**The model hears its own past turns as input.** In the probe audio the moderator is
part of the mix, so earlier moderator turns arrive on the input channel rather than as
assistant history. That is what `make_probe_audio.py` produces and what the data README
prescribes, so it is what this driver does. Injecting those turns as assistant history
instead would be a different experiment and would need the official code to be modified,
which this branch does not do.

**The whole probe is decoded, with no early stop.** The official loop consumes the
entire input, so a probe costs its full audio length even after the model has already
spoken. Stopping early would need the official function to be modified. The cost is
bounded and known, so the official code is left alone.
