#!/usr/bin/env python3
"""Rebuild CI document index from on-disk PDFs without re-downloading.

Skips invalid years. Merges with existing index URLs when possible.
Never authorizes scoring.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "data/raw/ci_collection"
INDEX = ROOT / "output/sync/official_document_index.csv"
MANIFEST = ROOT / "output/audit/scheduled_collection_manifest_v1_2025.csv"
SUMMARY = ROOT / "output/audit/ci_reindex_from_disk_v1.json"
FIELDS = (
    "company_code", "company_name", "report_year", "document_type",
    "source_url", "retrieval_url", "local_path", "sha256", "size",
)


def main() -> None:
    existing = {}
    if INDEX.is_file():
        with INDEX.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                key = (
                    (row.get("company_code") or "").strip(),
                    str(row.get("report_year") or "").strip(),
                    (row.get("document_type") or "").strip(),
                )
                if key[0] and key[2]:
                    existing[key] = row
    names: dict[str, str] = {}
    urls: dict[tuple[str, str, str], str] = {}
    if MANIFEST.is_file():
        with MANIFEST.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                code = (row.get("company_code") or "").strip()
                year = str(row.get("report_year") or "").strip()
                kind = (row.get("document_type") or "").strip()
                names.setdefault(code, (row.get("company_name") or "").strip())
                if code and year and kind and row.get("source_url"):
                    urls[(code, year, kind)] = row["source_url"].strip()

    rebuilt = []
    skipped_invalid_year = 0
    scanned = 0
    for path in sorted(PDF_ROOT.rglob("*.pdf")):
        scanned += 1
        try:
            rel = path.relative_to(PDF_ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 3:
            continue
        code, year_s, filename = parts[0], parts[1], parts[-1]
        kind = Path(filename).stem
        try:
            year = int(year_s)
        except ValueError:
            skipped_invalid_year += 1
            continue
        if year < 1990 or year > 2100:
            skipped_invalid_year += 1
            continue
        key = (code, str(year), kind)
        body = path.read_bytes()
        if not body.startswith(b"%PDF-"):
            continue
        digest = hashlib.sha256(body).hexdigest()
        local = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        prev = existing.get(key, {})
        source_url = prev.get("source_url") or urls.get(key) or f"local://{code}/{year}/{kind}"
        retrieval_url = prev.get("retrieval_url") or source_url
        rebuilt.append({
            "company_code": code,
            "company_name": prev.get("company_name") or names.get(code, ""),
            "report_year": str(year),
            "document_type": kind,
            "source_url": source_url,
            "retrieval_url": retrieval_url,
            "local_path": local,
            "sha256": digest,
            "size": str(len(body)),
        })

    rebuilt.sort(key=lambda row: (row["company_code"], row["report_year"], row["document_type"]))
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with INDEX.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rebuilt)

    summary = {
        "policy_version": "ci-reindex-from-disk-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "pdf_scanned": scanned,
        "indexed_rows": len(rebuilt),
        "skipped_invalid_year": skipped_invalid_year,
        "by_document_type": dict(Counter(row["document_type"] for row in rebuilt)),
        "missing_source_url": sum(1 for row in rebuilt if row["source_url"].startswith("local://")),
        "index": str(INDEX.relative_to(ROOT)),
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "仅从本地PDF重建索引；不下载、不评分。非法年份目录已跳过。",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
