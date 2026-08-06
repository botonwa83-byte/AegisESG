#!/usr/bin/env bash
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
lock_dir="/tmp/aegisesp-data-collection.lock"
log_dir="$repo_root/var/local-data-collection"
mkdir -p "$log_dir"
cd "$repo_root"
python_bin="${AEGIS_PYTHON_BIN:-$(command -v python3)}"
export PYTHONPATH="$repo_root/src"
export PYTHONPATH_SCRIPTS="$repo_root/scripts"

acquire_collection_lock() {
  "$python_bin" - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
from aegis_locks import acquire_lock
raise SystemExit(0 if acquire_lock("/tmp/aegisesp-data-collection.lock") else 1)
PY
}

release_collection_lock() {
  "$python_bin" - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
from aegis_locks import release_lock
release_lock("/tmp/aegisesp-data-collection.lock")
PY
}

# Reclaim dead locks, then either take the collection lock or refresh live status.
"$python_bin" scripts/reclaim_stale_locks.py --reclaim-stale >/dev/null 2>&1 || true

if ! acquire_collection_lock; then
  {
    echo "$(date -u +%FT%TZ) previous collection still running; refresh live status only"
    "$python_bin" scripts/refresh_live_collection_status.py || echo "live status refresh deferred"
    "$python_bin" scripts/run_ci_text_extraction.py || echo "text catch-up deferred"
    "$python_bin" scripts/run_incremental_indicator_extraction.py || echo "partial indicator extraction deferred"
  } >> "$log_dir/scheduler.log" 2>&1
  exit 0
fi
trap 'release_collection_lock' EXIT

{
  echo "$(date -u +%FT%TZ) collection started python=$python_bin"
  export AEGIS_COLLECTION_DOC_PRIORITY="${AEGIS_COLLECTION_DOC_PRIORITY:-esg}"
  export AEGIS_SZSE_CURL_MAX_TIME="${AEGIS_SZSE_CURL_MAX_TIME:-1200}"
  export AEGIS_HTTP_CURL_MAX_TIME="${AEGIS_HTTP_CURL_MAX_TIME:-300}"
  export AEGIS_HTTP_URLOPEN_TIMEOUT="${AEGIS_HTTP_URLOPEN_TIMEOUT:-90}"
  "$python_bin" scripts/build_scheduled_collection_manifest.py
  "$python_bin" scripts/build_official_website_source_queue.py
  "$python_bin" scripts/validate_official_website_source_queue.py
  "$python_bin" scripts/prepare_official_download_manifest.py
  "$python_bin" scripts/run_scheduled_collection.py
  "$python_bin" scripts/classify_collection_failures.py || echo "failure classification deferred"
  "$python_bin" scripts/build_collection_retry_manifest.py
  "$python_bin" scripts/build_collection_coverage_report.py
  "$python_bin" scripts/build_ci_research_merge_preview.py || echo "ci/research merge preview deferred"
  "$python_bin" scripts/refresh_live_collection_status.py || echo "live status refresh deferred"
  "$python_bin" -m aegis_esg.cli prepare-official-report-discovery-packet \
    output/audit/official_website_source_queue_v1_2025.csv \
    --csv output/audit/official_report_discovery_candidates_v1_2025.csv \
    --html output/audit/official_report_discovery_packet_v1_2025.html \
    --summary output/audit/official_report_discovery_packet_v1_2025.json || echo "official report discovery packet deferred"
  "$python_bin" scripts/run_ci_text_extraction.py || echo "ci text extraction reported failures; download remains valid"
  "$python_bin" scripts/run_incremental_indicator_extraction.py
  echo "$(date -u +%FT%TZ) collection finished"
} >> "$log_dir/scheduler.log" 2>&1
