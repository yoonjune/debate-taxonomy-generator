#!/usr/bin/env bash
# Clone the official MiniCPM-o repository at a pinned commit.
#
# The repository is reference material: the README it carries is the source of
# the duplex API this branch drives, and its assets are used by the smoke test.
# The model code itself does NOT come from here. It ships inside the checkpoint
# and is loaded with trust_remote_code, so any code change we ever need lands in
# the checkpoint overlay built by 03_download_checkpoint.sh, not here.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
THIRD_PARTY="${THIRD_PARTY:-$HERE/../third_party}"
REPO_URL="https://github.com/OpenBMB/MiniCPM-o.git"
PIN="f0866559fae0305bc7cacfb6a950640a927f6984"   # main as of 2026-09-06

mkdir -p "$THIRD_PARTY"
DEST="$THIRD_PARTY/MiniCPM-o"

if [ -d "$DEST/.git" ]; then
  echo "[setup] already cloned at $DEST"
else
  echo "[setup] cloning $REPO_URL"
  git clone "$REPO_URL" "$DEST"
fi

git -C "$DEST" fetch --quiet origin "$PIN" 2>/dev/null || true
git -C "$DEST" checkout --quiet --detach "$PIN"
echo "[setup] official repo pinned at $(git -C "$DEST" rev-parse HEAD)"
