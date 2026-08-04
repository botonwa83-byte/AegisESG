#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_evidence_page_located_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_basis_consistency_audit_v1_2025.csv"
SUMMARY = ROOT / "output/audit/thin_basis_consistency_audit_summary_v1_2025.json"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        text = row.get("evidence_text", "")
        row["currency_flag"] = "foreign_currency" if re.search(r"HKD|HK\$|USD|US\$|港元|美元", text, re.I) else "not_detected"
        row["revenue_denominator_flag"] = "revenue_present" if re.search(r"revenue|营业收入|营收", text, re.I) else "revenue_not_found"
        row["physical_unit_flag"] = "physical_unit_present" if re.search(r"吨|千克|公斤|tCO2e|MWh|kWh|GJ|立方米|tonnes?", text, re.I) else "physical_unit_not_found"
        row["scope_flag"] = "scope_language_present" if re.search(r"范围|边界|集团|基地|子公司|sites?|facilit", text, re.I) else "scope_language_not_found"
        row["basis_status"] = "needs_manual_basis_confirmation" if row["provenance_status"] == "ready_for_basis_review" else "blocked_provenance"
        row["scoring_authorized"] = "False"
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    summary = {"policy_version": "thin-basis-consistency-audit-v1", "task_count": len(rows),
               "basis_status_counts": dict(Counter(row["basis_status"] for row in rows)),
               "foreign_currency_count": sum(row["currency_flag"] == "foreign_currency" for row in rows),
               "scoring_authorized": False}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
