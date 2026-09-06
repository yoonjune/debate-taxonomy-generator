#!/usr/bin/env bash
# khs_claude_code: new file - conda env step for this evaluation.
# Create a dedicated conda environment for Raon-SpeechChat 9B.
#
# It is a NEW environment. Nothing installs into an environment that already
# exists, because this machine is shared and other environments belong to other
# work. If the name is taken the script stops instead of writing into it.
#
# Pins come from the official Raon-Speech repository: python 3.11 or newer, and
# transformers at least 4.57.1 below 5. speechbrain is in the official
# requirements and is what computes the speaker embedding from a reference wav,
# which this benchmark uses, so it is not optional here.
set -euo pipefail

ENV_NAME="${ENV_NAME:-raon}"
CONDA="${CONDA:-$HOME/miniconda3}"

if [ -d "$CONDA/envs/$ENV_NAME" ]; then
  echo "[setup] environment '$ENV_NAME' already exists at $CONDA/envs/$ENV_NAME"
  echo "[setup] refusing to modify an existing environment. Set ENV_NAME to another name."
  exit 1
fi

echo "[setup] creating conda environment '$ENV_NAME' with python 3.11"
"$CONDA/bin/conda" create -y -n "$ENV_NAME" python=3.11

PY="$CONDA/envs/$ENV_NAME/bin/python"
echo "[setup] installing the official stack"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install \
  "transformers>=4.57.1,<5.0" \
  torch torchaudio \
  accelerate einops kernels \
  "pydantic>=2.11.10" requests \
  "soundfile>=0.13.1" speechbrain tqdm \
  "datasets>=3.0.0"

# khs_claude_code: setuptools is not incidental. librosa still imports pkg_resources, which a
# bare conda python no longer ships, and the failure surfaces far from the cause:
# transformers reports the model file as requiring librosa, which is installed.
echo "[setup] installing what the probe driver needs on top of the official stack"
"$PY" -m pip install "setuptools<81" librosa

echo "[setup] done. interpreter: $PY"
"$PY" - <<'PYCHECK'
import torch, transformers
print("[setup] torch", torch.__version__, "cuda", torch.version.cuda,
      "available", torch.cuda.is_available())
print("[setup] transformers", transformers.__version__)
PYCHECK
