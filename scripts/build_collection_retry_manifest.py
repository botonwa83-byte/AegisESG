#!/usr/bin/env python3
"""Build a retry manifest from timed-out/failed scheduled downloads.

Only includes true identity gaps with valid report years. Alternate URLs for
already-indexed identities are skipped.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "output/audit/scheduled_collection_manifest_v1_2025.csv"
INDEX = ROOT / "output/sync/official_document_index.csv"
FAILURES = ROOT / "output/sync/official_collection_failures.csv"
CLASSIFICATION = ROOT / "output/audit/collection_failure_classification_v1_2025.csv"
OUTPUT = ROOT / "output/audit/scheduled_collection_retry_v1_2025.csv"
SUMMARY = ROOT / "output/audit/scheduled_collection_retry_v1_2025_summary.json"
FIELDS = (
    "company_code", "company_name", "report_year", "document_type", "source_url",
    "retry_reason", "failure_class", "next_action",
)

CLASS_PRIORITY = {
    "timeout_partial_resume": 0,
    "timeout_empty": 1,
    "ssl_eof": 2,
    "connection_reset": 2,
    "connection_closed": 2,
    "exchange_antibot_html": 3,
    "other_download_error": 4,
    "invalid_report_year": 9,
    "non_pdf_payload": 8,
    "pdf_too_small": 8,
}


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


def _load_classification() -> dict[str, dict[str, str]]:
    if not CLASSIFICATION.is_file():
        return {}
    with CLASSIFICATION.open(encoding="utf-8-sig", newline="") as stream:
        return {
            (row.get("source_url") or "").strip(): row
            for row in csv.DictReader(stream)
            if (row.get("source_url") or "").strip()
        }


def main() -> None:
    with MANIFEST.open(encoding="utf-8-sig", newline="") as stream:
        manifest = list(csv.DictReader(stream))
    indexed_urls = set()
    indexed_ids = set()
    if INDEX.is_file():
        with INDEX.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                url = (row.get("source_url") or "").strip()
                if url:
                    indexed_urls.add(url)
                key = _identity(row)
                if key[0] and key[2] and _valid_year(key[1]):
                    indexed_ids.add(key)
    failed_urls = {}
    if FAILURES.is_file():
        with FAILURES.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                url = (row.get("source_url") or "").strip()
                if url:
                    failed_urls[url] = (row.get("error") or "download_failed")[:160]
    classified = _load_classification()
    retry = []
    skipped_redundant = 0
    skipped_invalid_year = 0
    for row in manifest:
        url = (row.get("source_url") or "").strip()
        key = _identity(row)
        if not url or not key[0] or not key[2]:
            continue
        if not _valid_year(key[1]):
            skipped_invalid_year += 1
            continue
        if key in indexed_ids:
            if url not in indexed_urls:
                skipped_redundant += 1
            continue
        if url in indexed_urls:
            continue
        info = classified.get(url, {})
        failure_class = info.get("failure_class") or ("previous_failure" if url in failed_urls else "still_missing")
        next_action = info.get("next_action") or ("retry_later" if url in failed_urls else "download_missing")
        class_rank = CLASS_PRIORITY.get(failure_class, 5 if url in failed_urls else 6)
        type_rank = 0 if row.get("document_type") == "esg_report" else 1
        retry.append({
            "company_code": row.get("company_code", ""),
            "company_name": row.get("company_name", ""),
            "report_year": row.get("report_year", ""),
            "document_type": row.get("document_type", ""),
            "source_url": url,
            "retry_reason": failed_urls.get(url, "still_missing"),
            "failure_class": failure_class,
            "next_action": next_action,
            "_priority": (class_rank, type_rank),
        })
    # One URL per identity (prefer previously failed / classified).
    best: dict[tuple[str, str, str], dict] = {}
    for row in retry:
        key = _identity(row)
        current = best.get(key)
        if current is None or row["_priority"] < current["_priority"]:
            best[key] = row
    retry = list(best.values())
    retry.sort(key=lambda item: (*item["_priority"], item["document_type"], item["company_code"]))
    for row in retry:
        row.pop("_priority", None)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(retry)
    summary = {
        "policy_version": "scheduled-collection-retry-v2",
        "retry_rows": len(retry),
        "by_document_type": dict(Counter(row["document_type"] for row in retry)),
        "by_failure_class": dict(Counter(row["failure_class"] for row in retry)),
        "previous_failure_rows": sum(1 for row in retry if row["source_url"] in failed_urls),
        "skipped_redundant_url_gaps": skipped_redundant,
        "skipped_invalid_year": skipped_invalid_year,
        "timeout_partial_resume": sum(1 for row in retry if row["failure_class"] == "timeout_partial_resume"),
        "download_authorized": True,
        "scoring_authorized": False,
        "output": str(OUTPUT.relative_to(ROOT)),
        "usage": "AEGIS_COLLECTION_MANIFEST=output/audit/scheduled_collection_retry_v1_2025.csv python scripts/run_scheduled_collection.py",
        "notice": "仅真实身份缺口；已收集文档的备用URL与非法年份不进入重试。",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
