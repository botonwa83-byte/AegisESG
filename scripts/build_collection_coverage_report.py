#!/usr/bin/env python3
"""Report scheduled-download coverage without treating missing rows as failures."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "output/audit/scheduled_collection_manifest_v1_2025.csv"
INDEX = ROOT / "output/sync/official_document_index.csv"
FAILURES = ROOT / "output/sync/official_collection_failures.csv"
OUTPUT = ROOT / "output/audit/scheduled_collection_coverage_v1_2025.json"


def main() -> None:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as stream:
        manifest = list(csv.DictReader(stream))
    indexed = []
    if INDEX.is_file():
        with INDEX.open(encoding="utf-8-sig", newline="") as stream:
            indexed = list(csv.DictReader(stream))
    failed = []
    if FAILURES.is_file():
        with FAILURES.open(encoding="utf-8-sig", newline="") as stream:
            failed = list(csv.DictReader(stream))
    manifest_urls = {row.get("source_url", "") for row in manifest}
    indexed_urls = {row.get("source_url", "") for row in indexed}
    result = {"policy_version": "scheduled-collection-coverage-v1", "manifest_rows": len(manifest),
              "downloaded_rows": len(indexed), "missing_rows": len(manifest_urls - indexed_urls),
              "failure_rows": len(failed), "downloaded_by_host": dict(Counter(urlparse(row.get("source_url", "")).hostname or "" for row in indexed)),
              "missing_by_document_type": dict(Counter(row.get("document_type", "") for row in manifest if row.get("source_url", "") not in indexed_urls)),
              "scoring_authorized": False, "formal_publishable": False}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
