#!/usr/bin/env bash
# khs_claude_code: new file - download checkpoint step for this evaluation.
# Download the official MiniCPM-o 4.5 checkpoint at a pinned revision.
#
# About 20 GB over 54 files. It includes assets/token2wav, which holds the
# speech decoder weights, so this one download covers audio output as well.
#
# The checkpoint is left PRISTINE. It also carries the model code that
# trust_remote_code executes, so it is the file set our own edits would touch.
# When that happens we do not edit in place: build_overlay.sh makes a sibling
# directory of symlinks with only the changed python files replaced, so
# `diff` against the pristine copy is the whole record of what we changed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CKPT_ROOT="${CKPT_ROOT:-$HERE/../ckpt}"
ENV_NAME="${ENV_NAME:-mcpmo45}"
CONDA="${CONDA:-$HOME/miniconda3}"
REPO_ID="openbmb/MiniCPM-o-4_5"
REVISION="503e754207c94da6bb26850b4469f367c9ea3582"   # main as of 2026-09-06
DEST="$CKPT_ROOT/MiniCPM-o-4_5"

PY="$CONDA/envs/$ENV_NAME/bin/python"
[ -x "$PY" ] || { echo "[setup] no interpreter at $PY. Run 01_conda_env.sh first."; exit 1; }

# khs_claude_code: the version bound is not cosmetic. transformers pins huggingface_hub below
# 1.0, and installing the cli extra with --upgrade pulls 1.x and breaks every
# transformers import in the environment. Install inside the bound instead.
"$PY" -m pip install --quiet "huggingface_hub[cli]>=0.34.0,<1.0"
HF="$CONDA/envs/$ENV_NAME/bin/hf"

mkdir -p "$CKPT_ROOT"
echo "[setup] downloading $REPO_ID at $REVISION into $DEST"
echo "[setup] about 20 GB. Resumes if interrupted, so rerun the same command."
"$HF" download "$REPO_ID" --revision "$REVISION" --local-dir "$DEST"

echo "[setup] verifying the files the duplex path needs"
for f in config.json modeling_minicpmo.py processing_minicpmo.py \
         model.safetensors.index.json \
         assets/token2wav/flow.pt assets/token2wav/hift.pt \
         assets/token2wav/campplus.onnx \
         assets/token2wav/speech_tokenizer_v2_25hz.onnx; do
  [ -f "$DEST/$f" ] || { echo "[setup] MISSING $f"; exit 1; }
done
echo "[setup] checkpoint ready at $DEST"
du -sh "$DEST"
