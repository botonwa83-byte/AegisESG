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


def _valid_year(value: str) -> bool:
    try:
        year = int(str(value).strip())
    except ValueError:
        return False
    return 1990 <= year <= 2100


def _identity(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        (row.get("company_code") or "").strip(),
        str(row.get("report_year") or "").strip(),
        (row.get("document_type") or "").strip(),
    )


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

    manifest_urls = {row.get("source_url", "").strip() for row in manifest if row.get("source_url", "").strip()}
    indexed_urls = {row.get("source_url", "").strip() for row in indexed if row.get("source_url", "").strip()}
    manifest_ids = {_identity(row) for row in manifest if _identity(row)[0] and _identity(row)[2]}
    valid_manifest_ids = {key for key in manifest_ids if _valid_year(key[1])}
    indexed_ids = {_identity(row) for row in indexed if _identity(row)[0] and _identity(row)[2] and _valid_year(_identity(row)[1])}
    missing_urls = manifest_urls - indexed_urls
    missing_identities = valid_manifest_ids - indexed_ids
    invalid_year_ids = {key for key in manifest_ids if not _valid_year(key[1])}
    # URL missing but identity already collected via another URL.
    redundant_url_gaps = 0
    for row in manifest:
        url = (row.get("source_url") or "").strip()
        if url and url not in indexed_urls and _identity(row) in indexed_ids:
            redundant_url_gaps += 1

    result = {
        "policy_version": "scheduled-collection-coverage-v2",
        "manifest_rows": len(manifest),
        "manifest_identities": len(manifest_ids),
        "manifest_valid_identities": len(valid_manifest_ids),
        "downloaded_rows": len(indexed),
        "downloaded_identities": len(indexed_ids),
        "missing_rows": len(missing_urls),
        "missing_identities": len(missing_identities),
        "redundant_url_gaps": redundant_url_gaps,
        "invalid_year_identities": len(invalid_year_ids),
        "identity_coverage_rate": round(len(indexed_ids) / len(valid_manifest_ids), 4) if valid_manifest_ids else 0.0,
        "failure_rows": len(failed),
        "downloaded_by_host": dict(Counter(urlparse(row.get("source_url", "")).hostname or "" for row in indexed)),
        "missing_by_document_type": dict(Counter(row.get("document_type", "") for row in manifest if row.get("source_url", "").strip() in missing_urls)),
        "missing_identities_by_document_type": dict(
            Counter(kind for _, _, kind in missing_identities)
        ),
        "retry_manifest": "output/audit/scheduled_collection_retry_v1_2025.csv",
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "identity口径才是真实缺口；URL缺口含同文档备用链接。",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
