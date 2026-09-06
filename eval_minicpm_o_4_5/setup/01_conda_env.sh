#!/usr/bin/env bash
# Create a dedicated conda environment for MiniCPM-o 4.5.
#
# It is a NEW environment. Nothing installs into an environment that already
# exists, because this machine is shared and other environments belong to other
# work. If the name is taken the script stops instead of writing into it.
#
# The pins come from the official README, section "Offline Inference Examples
# with Transformers": python 3.10, transformers 4.51.0 exactly, torch in the
# range 2.3 to 2.8, and minicpmo-utils with the [all] extra, which is what pulls
# in the speech decoder needed for audio output.
set -euo pipefail

ENV_NAME="${ENV_NAME:-mcpmo45}"
CONDA="${CONDA:-$HOME/miniconda3}"

if [ -d "$CONDA/envs/$ENV_NAME" ]; then
  echo "[setup] environment '$ENV_NAME' already exists at $CONDA/envs/$ENV_NAME"
  echo "[setup] refusing to modify an existing environment. Set ENV_NAME to another name."
  exit 1
fi

echo "[setup] creating conda environment '$ENV_NAME' with python 3.10"
"$CONDA/bin/conda" create -y -n "$ENV_NAME" python=3.10

PY="$CONDA/envs/$ENV_NAME/bin/python"
echo "[setup] installing the official pinned stack"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install \
  "transformers==4.51.0" \
  accelerate \
  "torch>=2.3.0,<=2.8.0" \
  "torchaudio<=2.8.0" \
  "minicpmo-utils[all]>=1.0.5"

# KHS: setuptools is not incidental. librosa still imports pkg_resources, which a
# bare conda python no longer ships, and the failure surfaces far from the cause:
# transformers reports the model file as requiring librosa, which is installed.
echo "[setup] installing what the probe driver needs on top of the official stack"
"$PY" -m pip install "setuptools<81" soundfile librosa tqdm

echo "[setup] done. interpreter: $PY"
"$PY" - <<'PYCHECK'
import torch, transformers
print("[setup] torch", torch.__version__, "cuda", torch.version.cuda,
      "available", torch.cuda.is_available())
print("[setup] transformers", transformers.__version__)
PYCHECK
