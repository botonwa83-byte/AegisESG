#!/usr/bin/env bash
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
staging="${repo_root}/var/ci-data-staging"
mkdir -p "$staging"
rm -rf "$staging"/*

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required; install it and run gh auth login" >&2
  exit 2
fi

gh run download --repo "${GH_REPO:-botonwa83-byte/AegisESP}" --name "aegis-official-data" --dir "$staging"
if [ ! -f "$staging/output/sync/collection_run_summary.json" ]; then
  echo "artifact missing collection_run_summary.json; refusing local sync" >&2
  exit 3
fi

mkdir -p "$repo_root/data/raw/ci_collection" "$repo_root/output/sync"
cp -R "$staging/data/raw/ci_collection/." "$repo_root/data/raw/ci_collection/" 2>/dev/null || true
cp -R "$staging/output/sync/." "$repo_root/output/sync/"
echo "CI data staged and copied after artifact validation"
