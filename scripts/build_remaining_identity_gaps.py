#!/usr/bin/env python3
"""Emit a focused packet for the remaining identity-level collection gaps."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETRY = ROOT / "output/audit/scheduled_collection_retry_v1_2025.csv"
OUTPUT = ROOT / "output/audit/remaining_identity_gaps_v1_2025.csv"
SUMMARY = ROOT / "output/audit/remaining_identity_gaps_v1_2025.json"


def main() -> None:
    rows = []
    if RETRY.is_file():
        with RETRY.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else [
        "company_code", "company_name", "report_year", "document_type",
        "source_url", "retry_reason", "failure_class", "next_action",
    ]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "policy_version": "remaining-identity-gaps-v1",
        "gap_count": len(rows),
        "scoring_authorized": False,
        "formal_publishable": False,
        "output": str(OUTPUT.relative_to(ROOT)),
        "notice": "身份口径剩余缺口；深交所反爬时可改走巨潮法定披露或官网同域通道。",
        "rows": [
            {
                "company_code": row.get("company_code"),
                "document_type": row.get("document_type"),
                "failure_class": row.get("failure_class"),
            }
            for row in rows
        ],
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
