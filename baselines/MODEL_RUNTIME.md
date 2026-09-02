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
.venv-model/bin/python -m pip install -e .
```

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
Every `generation.json` records that limitation. A later aligner-backed text
schedule can add exact text-token forcing without changing the input manifest.

## Required compatibility smoke test

Run one probe with each checkpoint before a batch. The RL checkpoint is expected
to share the PersonaPlex architecture, but compatibility with the pinned NVIDIA
runtime must be demonstrated rather than assumed. Preserve any load error as a
negative result; do not change the base and RL runtime independently.
