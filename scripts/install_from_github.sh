#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${PALLETPROOF_REPO_DIR:-$(pwd)}"
TARGET_REF="${PALLETPROOF_TARGET_REF:-main}"
TARGET_COMMIT="${PALLETPROOF_TARGET_COMMIT:-}"

cd "$REPO_DIR"

git fetch --prune origin "$TARGET_REF"
git checkout "$TARGET_REF"

if [[ -n "$TARGET_COMMIT" ]]; then
  git merge --ff-only "$TARGET_COMMIT"
else
  git merge --ff-only "origin/$TARGET_REF"
fi

if [[ ! -x ".venv/bin/pip" ]]; then
  python3 -m venv --system-site-packages .venv
fi

.venv/bin/pip install -e . --no-deps
