#!/usr/bin/env bash
# Clone the official Raon-Speech repository at a pinned commit.
#
# Reference material. The duplex API this branch drives, RaonPipeline.duplex,
# ships inside the checkpoint as modeling_raon.py and is loaded with
# trust_remote_code, so the repository is not on the import path at run time.
# What it gives us is the official inference defaults in config/duplex_infer.yaml
# and the duplex example notebook, both of which this branch follows exactly.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THIRD_PARTY="${THIRD_PARTY:-$HERE/../third_party}"
REPO_URL="https://github.com/krafton-ai/Raon-Speech.git"
PIN="afec41185e27653aa905d4ad28a7b8497681275e"   # main as of 2026-09-06

mkdir -p "$THIRD_PARTY"
DEST="$THIRD_PARTY/Raon-Speech"

if [ -d "$DEST/.git" ]; then
  echo "[setup] already cloned at $DEST"
else
  echo "[setup] cloning $REPO_URL"
  git clone "$REPO_URL" "$DEST"
fi

git -C "$DEST" fetch --quiet origin "$PIN" 2>/dev/null || true
git -C "$DEST" checkout --quiet --detach "$PIN"
echo "[setup] official repo pinned at $(git -C "$DEST" rev-parse HEAD)"
echo "[setup] official duplex defaults:"
sed -n '1,20p' "$DEST/config/duplex_infer.yaml"
