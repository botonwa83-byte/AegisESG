#!/usr/bin/env python3
"""Run a resumable collection job for CI and emit a compact sync manifest."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from aegis_esg.collector import collect_batch

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(os.getenv("AEGIS_COLLECTION_MANIFEST", ROOT / "output/audit/scheduled_collection_manifest_v1_2025.csv"))
OUTPUT_ROOT = Path(os.getenv("AEGIS_COLLECTION_OUTPUT_ROOT", ROOT / "data/raw/ci_collection"))
INDEX = Path(os.getenv("AEGIS_COLLECTION_INDEX", ROOT / "output/sync/official_document_index.csv"))
FAILURES = Path(os.getenv("AEGIS_COLLECTION_FAILURES", ROOT / "output/sync/official_collection_failures.csv"))
SUMMARY = ROOT / "output/sync/collection_run_summary.json"


def main() -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.is_file():
        raise SystemExit(f"collection manifest not found: {MANIFEST}")
    records, failures = collect_batch(MANIFEST, OUTPUT_ROOT, INDEX, FAILURES, delay_seconds=1.0, workers=2, reuse_existing=True)
    result = {
        "policy_version": "scheduled-collection-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest": str(MANIFEST.relative_to(ROOT)) if MANIFEST.is_relative_to(ROOT) else str(MANIFEST),
        "record_count": len(records), "failure_count": len(failures),
        "index": str(INDEX.relative_to(ROOT)) if INDEX.is_relative_to(ROOT) else str(INDEX),
        "output_root": str(OUTPUT_ROOT.relative_to(ROOT)) if OUTPUT_ROOT.is_relative_to(ROOT) else str(OUTPUT_ROOT),
        "download_started": bool(records or failures), "scoring_authorized": False,
        "formal_publishable": False,
    }
    SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
