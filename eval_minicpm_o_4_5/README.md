# MiniCPM-o 4.5 on the debate moderator probes

Runs the official MiniCPM-o 4.5 full duplex speech loop over a probe set and writes, per
probe, whether the model spoke, when, and what it said. Scoring is not done here.

This branch adds one directory and changes nothing else. The model code is the official
code, unmodified. Everything here is a driver around it, and every place where the
driver departs from the official example is marked `KHS` in a comment saying why.

## What scoring gets

One line per probe in `out/<tag>/results.jsonl`:

```json
{"probe_id": "L000_p02", "model": "MiniCPM-o-4_5",
 "spoke": true, "spoke_at": 39.0, "audible_at": 39.24,
 "text": "Ten seconds left.", "wav": "audio/L000_p02.wav",
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

**`spoke_at` and `audible_at` are different things.** `spoke_at` is when the model
decided to speak. `audible_at` is when sound actually starts, measured from the
generated waveform, and it can be later because synthesized speech can open with
silence. The window is a few seconds wide, so the difference is not negligible. Both are
reported and which one to score is the scorer's choice.

Both are in seconds from the start of the probe audio, which is the same timeline as
`t_earliest`, `t_deadline` and `t_latest`, because `make_probe_audio.py` builds each
probe as `mix[:window_end]`, so sample zero of the probe wav is second zero of the
debate. No offset is needed.

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
everything lands in `out/<tag>/run_config.json`. Two settings never collide and a run
describes itself, so a later comparison does not depend on shell history.

```bash
$E run_probes.py --ckpt ... --tag chunk05 --chunk-seconds 0.5   # finer timing
$E run_probes.py --ckpt ... --tag noref   --no-reference        # no voice conditioning
$E run_probes.py --ckpt ... --tag clock   --kinds clock         # one probe family
$E run_probes.py --ckpt ... --tag full    --run-to-end          # capture whole replies
```

| group | flags |
|---|---|
| decoding | `--chunk-seconds` `--max-speak-tokens` `--decode-mode` `--run-to-end` |
| model | `--ckpt` `--dtype` `--attn` `--with-vision` |
| probe set | `--data-sample` `--probes` `--debates-file` `--system-prompt` `--probe-audio` `--voices` `--no-reference` |
| selection | `--debates` `--probe-ids` `--labels` `--kinds` `--limit` |
| output | `--out` `--tag` |

Nothing about the probe set is hard coded, so a later version with more debates,
different windows or a rewritten prompt is a flag rather than an edit.

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

## The three departures from the official example

Each is marked `KHS` at the line it happens.

**No video.** The README's duplex example always passes video frames. This benchmark is
speech only, so `init_vision=False` and `frame_list` is empty.

**The benchmark's system prompt** instead of the example's
`"Streaming Omni Conversation."`, with the four placeholders substituted from
`debates.jsonl`.

**Stopping at the first spoken chunk.** What is measured is settled the moment
`is_listen` turns false, so continuing would only cost time. `--run-to-end` keeps going.

## Choices worth arguing with

**The moderator reference voice is used for voice conditioning.** The moderator already
speaks in the probe audio in a cloned voice, and `voices/` holds the clip it came from.
Conditioning on it stops the model answering in a voice nobody in the debate has heard.
`--no-reference` drops it.

**The model hears its own past turns as input.** In the probe audio the moderator is part
of the mix, so earlier moderator turns arrive on the input channel rather than as
assistant history. That is what `make_probe_audio.py` produces and what the data README
prescribes. Injecting them as assistant history would be a different experiment and
would require modifying official code.

**Timing resolution is the chunk length.** `is_listen` is reported once per chunk, so
`spoke_at` lands on a one second grid by default. `audible_at` is continuous because it
is measured from the waveform. `--chunk-seconds` trades resolution against cost.
