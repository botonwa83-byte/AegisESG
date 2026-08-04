#!/usr/bin/env python3
"""Merge reviewed exchange manifests into one deduplicated scheduled manifest."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "data/manifests/sse_all_2025.csv",
    ROOT / "data/manifests/szse_candidates_2025.csv",
    ROOT / "data/manifests/bse_candidates_2025.csv",
    ROOT / "data/manifests/hkex_reports_all_2026-07-29.csv",
    ROOT / "data/manifests/rediscovery_2025.csv",
)
OUTPUT = ROOT / "output/audit/scheduled_collection_manifest_v1_2025.csv"
SUMMARY = ROOT / "output/audit/scheduled_collection_manifest_v1_2025_summary.json"
FIELDS = ("company_code", "company_name", "report_year", "document_type", "source_url")


def main() -> None:
    seen: set[tuple[str, str, str, str]] = set()
    rows = []
    source_counts = {}
    for path in SOURCES:
        if not path.is_file():
            continue
        count = 0
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for raw in csv.DictReader(stream):
                kind = (raw.get("document_type") or "").strip()
                url = (raw.get("source_url") or "").strip()
                code = (raw.get("company_code") or "").strip()
                year = (raw.get("report_year") or "").strip()
                if kind not in {"annual_report", "esg_report"} or not code or not year or not url:
                    continue
                key = (code, year, kind, url)
                if key in seen:
                    continue
                seen.add(key); count += 1
                rows.append({"company_code": code, "company_name": (raw.get("company_name") or "").strip(),
                             "report_year": year, "document_type": kind, "source_url": url})
        source_counts[path.name] = count
    rows.sort(key=lambda row: (row["company_code"], row["report_year"], row["document_type"], row["source_url"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    summary = {"policy_version": "scheduled-collection-manifest-v1", "source_counts": source_counts,
               "deduplicated_rows": len(rows), "company_count": len({row["company_code"] for row in rows}),
               "download_authorized": True, "scoring_authorized": False, "official_website_rows": 0,
               "note": "交易所公开清单合并去重；官网来源在域名验证后另行并入"}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
