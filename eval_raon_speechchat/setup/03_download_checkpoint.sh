#!/usr/bin/env bash
# khs_claude_code: new file - download checkpoint step for this evaluation.
# Download the official Raon-SpeechChat 9B checkpoint at a pinned revision.
#
# About 19.5 GB over 20 files. The checkpoint also carries modeling_raon.py,
# which is the code trust_remote_code executes, so this download brings both the
# weights and the duplex implementation.
#
# The checkpoint is left PRISTINE. This branch changes none of it. If a change
# ever becomes necessary it goes into a sibling overlay of symlinks with only the
# changed python file replaced, so a diff against this copy is the whole record.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CKPT_ROOT="${CKPT_ROOT:-$HERE/../ckpt}"
ENV_NAME="${ENV_NAME:-raon}"
CONDA="${CONDA:-$HOME/miniconda3}"
REPO_ID="KRAFTON/Raon-SpeechChat-9B"
REVISION="a8bac78f596839edde5fb977fa435abf52a07a2b"   # main as of 2026-09-06
DEST="$CKPT_ROOT/Raon-SpeechChat-9B"

PY="$CONDA/envs/$ENV_NAME/bin/python"
[ -x "$PY" ] || { echo "[setup] no interpreter at $PY. Run 01_conda_env.sh first."; exit 1; }

# khs_claude_code: the version bound is not cosmetic. transformers pins huggingface_hub below
# 1.0, and installing the cli extra with --upgrade pulls 1.x and breaks every
# transformers import in the environment. Install inside the bound instead.
"$PY" -m pip install --quiet "huggingface_hub[cli]>=0.34.0,<1.0"
HF="$CONDA/envs/$ENV_NAME/bin/hf"

mkdir -p "$CKPT_ROOT"
echo "[setup] downloading $REPO_ID at $REVISION into $DEST"
echo "[setup] about 19.5 GB. Resumes if interrupted, so rerun the same command."
"$HF" download "$REPO_ID" --revision "$REVISION" --local-dir "$DEST"

echo "[setup] verifying the files the duplex path needs"
for f in config.json modeling_raon.py configuration_raon.py \
         model.safetensors.index.json tokenizer.json chat_template.jinja; do
  [ -f "$DEST/$f" ] || { echo "[setup] MISSING $f"; exit 1; }
done
echo "[setup] checkpoint ready at $DEST"
du -sh "$DEST"
