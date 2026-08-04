#!/usr/bin/env bash
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
lock_dir="/tmp/aegisesp-data-collection.lock"
log_dir="$repo_root/var/local-data-collection"
mkdir -p "$log_dir"
if ! mkdir "$lock_dir" 2>/dev/null; then
  echo "$(date -u +%FT%TZ) previous collection still running; skip" >> "$log_dir/scheduler.log"
  exit 0
fi
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT

cd "$repo_root"
python_bin="${AEGIS_PYTHON_BIN:-$(command -v python3)}"
export PYTHONPATH="$repo_root/src"
{
  echo "$(date -u +%FT%TZ) collection started python=$python_bin"
  "$python_bin" scripts/build_scheduled_collection_manifest.py
  "$python_bin" scripts/build_official_website_source_queue.py
  "$python_bin" scripts/validate_official_website_source_queue.py
  "$python_bin" scripts/prepare_official_download_manifest.py
  "$python_bin" scripts/run_scheduled_collection.py
  echo "$(date -u +%FT%TZ) collection finished"
} >> "$log_dir/scheduler.log" 2>&1
