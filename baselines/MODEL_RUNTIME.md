# PersonaPlex model runtime

Both baselines use the NVIDIA PersonaPlex Moshi runtime. The comparison changes
the Hugging Face checkpoint and revision only.

Pinned upstream runtime:

```text
https://github.com/NVIDIA/personaplex
commit 3428dfd95309a7f3c84fd93259ded0f810d1ff91
subdirectory moshi/
```

Create a separate CUDA environment; do not install this into the lightweight
data/scoring environment because the official runtime pins Torch and NumPy:

```bash
python3.10 -m venv .venv-model
.venv-model/bin/python -m pip install --upgrade pip
.venv-model/bin/python -m pip install \
  "git+https://github.com/NVIDIA/personaplex.git@3428dfd95309a7f3c84fd93259ded0f810d1ff91#subdirectory=moshi"
.venv-model/bin/python -m pip install -r requirements-model-extra.txt
.venv-model/bin/python -m pip install -e .
```

The pinned upstream package does not currently declare `pyloudnorm`, although
voice-prompt loading imports it. RunPod images can also set
`HF_HUB_ENABLE_HF_TRANSFER=1` without installing `hf_transfer`. Both observed
runtime dependencies are pinned in `requirements-model-extra.txt`.

Before downloading weights, authenticate with a Hugging Face token whose
account has accepted both model agreements. Never put the token in a config,
command transcript, or committed file.

The checkpoint revisions are pinned in `configs/models/`:

- base: `nvidia/personaplex-7b-v1`
- RL: `kyutai/personaplex-rl-seamless`

## Teacher-forcing boundary

Version 0.1 performs native two-stream replay:

```text
before release: user audio forced + moderator acoustic tokens forced
after release:  user audio forced + moderator acoustic/text tokens sampled
```

The parallel moderator text stream is sampled during the acoustic teacher
prefix. Therefore this is `agent_audio_only`, not exact audio+text state replay.
Every `generation.json` records that limitation. `agent_audio_text` instead
forces PAD on silent moderator frames and the known moderator text tokens on a
deterministic Qwen-aligned schedule before release.

## Qwen forced-alignment runtime

Keep the aligner separate from the pinned PersonaPlex environment, as the Qwen
project recommends an isolated environment and may require a newer Transformers
stack:

```bash
python3 -m venv baselines/.venv-aligner
baselines/.venv-aligner/bin/pip install -r baselines/requirements-aligner.txt
baselines/.venv-aligner/bin/pip install -e baselines
```

The committed config pins `Qwen/Qwen3-ForcedAligner-0.6B`, its model revision,
and `qwen-asr`. Alignment is a one-time preprocessing step over isolated
moderator turns:

```bash
baselines/.venv-aligner/bin/moderator-bench align-moderator \
  --data-root data_sample \
  --output-dir baselines/artifacts/alignments/qwen3-v1
```

The output timestamps are relative to each isolated turn and are stored before
any PersonaPlex token/frame scheduling. Alignment failures and zero-duration
word spans are retained as explicit artifacts, not silently edited. A
zero-duration word is a warning: its token keeps the reported boundary time and
the normal unique-frame packing rule resolves collisions. Non-monotonic or
overlapping word spans remain fatal.

Qwen returns English word timestamps, whereas PersonaPlex consumes one
SentencePiece token per 80-ms frame. The conversion preserves the exact
PersonaPlex token sequence and deterministically distributes subword and
punctuation tokens within the aligned word span. It is therefore an
aligner-backed replay, not a directly observed frame-level gold annotation.

Attach the alignment index while preparing the probe, then select the explicit
audio+text model config:

```bash
baselines/.venv-model/bin/moderator-bench prepare \
  --data-root data_sample \
  --probe-id L000_p02 \
  --alignment-index baselines/artifacts/alignments/qwen3-v1/alignment_index.json \
  --output-dir baselines/artifacts/prepared-audio-text

baselines/.venv-model/bin/moderator-bench run \
  --input-manifest baselines/artifacts/prepared-audio-text/L000_p02/input_manifest.json \
  --model-config baselines/configs/models/personaplex_base_audio_text.json \
  --output-dir baselines/artifacts/runs-audio-text
```

`output_text.json` uses the delayed output-frame clock, not the current input
step. It records both indices because Moshi returns a frame only after its codec
delay has elapsed.

## Required compatibility smoke test

Run one probe with each checkpoint before a batch. The RL checkpoint is expected
to share the PersonaPlex architecture, but compatibility with the pinned NVIDIA
runtime must be demonstrated rather than assumed. Preserve any load error as a
negative result; do not change the base and RL runtime independently.
