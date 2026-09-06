# MiniCPM-o 4.5 on the debate moderator probes

Runs the official MiniCPM-o 4.5 full duplex speech loop over `data_sample`, and records
for every probe whether the model spoke and when.

This branch adds one directory and changes nothing else in the repository. The model
code is the official code, unmodified. Everything written here is a driver around it,
and every place where this driver departs from the official example is marked `KHS` in
a comment that says why.

## What it produces

One line per probe in `out/minicpm_o_4_5/results.jsonl`:

```json
{"probe_id": "L000_p02", "model": "MiniCPM-o-4_5", "spoke": true, "spoke_at": 39.0,
 "spoke_chunk": 38, "text": "Ten seconds left.", "wav": "audio/L000_p02.wav",
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

## Setup, from nothing

Four steps. Each is idempotent, so a rerun after an interruption is safe.

```bash
cd eval_minicpm_o_4_5

bash setup/01_conda_env.sh                  # new conda env, python 3.10
bash setup/02_clone_official.sh             # official repo at a pinned commit
bash setup/03_download_checkpoint.sh        # official checkpoint, about 20 GB

CUDA_VISIBLE_DEVICES=0 ~/miniconda3/envs/mcpmo45/bin/python \
  setup/04_verify.py --ckpt ckpt/MiniCPM-o-4_5
```

`01_conda_env.sh` refuses to touch an environment that already exists. This machine is
shared, so it creates `mcpmo45` or stops. Override with `ENV_NAME`.

Step 4 is not decoration. It answers two questions the official README leaves open for a
speech only benchmark: whether the duplex path runs with `init_vision=False` and an
empty `frame_list`, and whether the model's own `current_time` advances by the chunk
length. `spoke_at` is derived from the chunk index, so if that clock disagrees the
timing arithmetic is wrong and has to be fixed before any number here is worth reading.
It also measures the per chunk cost and prints an estimate for the whole run.

## Pinned versions

Nothing floats. These are the exact official artifacts this branch was written against.

| what | source | pin |
|---|---|---|
| repository | `github.com/OpenBMB/MiniCPM-o` | `f0866559fae0305bc7cacfb6a950640a927f6984` |
| checkpoint | `huggingface.co/openbmb/MiniCPM-o-4_5` | `503e754207c94da6bb26850b4469f367c9ea3582` |
| transformers | official README pin | `4.51.0` exactly |
| torch | official README range | `>=2.3.0,<=2.8.0` |
| helper package | official README | `minicpmo-utils[all]>=1.0.5` |

The model code is not in the repository. It ships inside the checkpoint and is loaded
through `trust_remote_code`, so the checkpoint is the file set that a code change would
touch. It is kept pristine. If a change ever becomes necessary, it goes into a sibling
overlay directory of symlinks with only the changed python file replaced, so `diff`
against the pristine copy is the entire record of what was changed.

## Running

Probe audio first, once, from the data directory:

```bash
cd ../data_sample && python make_probe_audio.py && cd -
```

Then a pilot before the full set, always:

```bash
CUDA_VISIBLE_DEVICES=0 ~/miniconda3/envs/mcpmo45/bin/python run_probes.py \
  --ckpt ckpt/MiniCPM-o-4_5 --out out/minicpm_o_4_5 --limit 3
```

Then everything:

```bash
CUDA_VISIBLE_DEVICES=0 ~/miniconda3/envs/mcpmo45/bin/python run_probes.py \
  --ckpt ckpt/MiniCPM-o-4_5 --out out/minicpm_o_4_5
```

It resumes: rerunning skips probes already in `results.jsonl`.

| flag | default | what it does |
|---|---|---|
| `--chunk-seconds` | `1.0` | audio fed per step, and therefore the resolution of `spoke_at` |
| `--run-to-end` | off | keep streaming after the model starts speaking, to capture the whole reply rather than only its start time |
| `--with-vision` | off | build the vision tower as well, for the case where the duplex path refuses to run without it |
| `--limit` | `0` | pilot on the first N probes |
| `--debates` | all | restrict to given debate ids |

## The three deliberate departures from the official example

Each is marked `KHS` at the line it happens.

**No video.** The README's duplex example always passes video frames. This benchmark is
speech only, so the model is built with `init_vision=False` and `frame_list` is empty.

**The benchmark's system prompt.** The example passes `"Streaming Omni Conversation."`.
This passes `data_sample/system_prompt.md` with its four placeholders substituted from
`debates.jsonl`, which is what the data specifies.

**Stopping at the first spoken chunk.** What is measured is when the model decides to
speak, and that is settled the moment `is_listen` turns false. Continuing would only
cost time. `--run-to-end` keeps going when the reply itself is wanted.

## Choices worth arguing with

**The moderator reference voice is used for voice conditioning.** The moderator already
speaks in the probe audio in a particular cloned voice, and `voices/` holds the clip it
was cloned from. Conditioning on it stops the model from answering in a fourth voice
that nobody in the debate has heard. This is a choice, not a requirement of the
benchmark, and passing no reference is a one line change.

**The model hears its own past turns as input.** In the probe audio the moderator is
part of the mix, so earlier moderator turns arrive on the input channel rather than as
assistant history. That is what `make_probe_audio.py` produces and what the data
README prescribes, so it is what this driver does. Injecting those turns as assistant
history instead would be a different experiment and would need the official code to be
modified, which this branch does not do.

**Timing resolution is the chunk length.** `is_listen` is reported once per chunk, so
`spoke_at` lands on a one second grid. The scoring window is five seconds wide, from
`t_deadline` minus 2.0 to `t_deadline` plus 3.0, so a one second grid sits inside it,
but `spoke_chunk` and `chunk_seconds` are recorded so the arithmetic can be redone.
