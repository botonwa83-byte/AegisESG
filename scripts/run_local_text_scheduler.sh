#!/usr/bin/env bash
# Text extraction can run while PDF downloads hold the collection lock.
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
log_dir="$repo_root/var/local-data-collection"
mkdir -p "$log_dir"
cd "$repo_root"
python_bin="${AEGIS_PYTHON_BIN:-$(command -v python3)}"
export PYTHONPATH="$repo_root/src"
{
  echo "$(date -u +%FT%TZ) ci text extraction started"
  "$python_bin" scripts/run_ci_text_extraction.py
  "$python_bin" scripts/run_incremental_indicator_extraction.py || echo "incremental extraction deferred"
  "$python_bin" scripts/build_ci_incremental_coverage_packet.py || echo "ci coverage packet deferred"
  "$python_bin" scripts/build_ci_thin_text_packet.py || echo "ci thin-text packet deferred"
  "$python_bin" scripts/build_scan_esg_annual_fallback_packet.py || echo "scan esg fallback packet deferred"
  "$python_bin" scripts/refresh_live_collection_status.py || echo "live status refresh deferred"
  echo "$(date -u +%FT%TZ) ci text extraction finished"
} >> "$log_dir/text-extraction.log" 2>&1
