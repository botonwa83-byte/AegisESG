#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_basis_consistency_audit_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_basis_review_template_v1_2025.csv"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    fields = ["company_code", "company_name", "report_year", "indicator_code", "indicator_name", "located_page",
              "source_file", "evidence_text", "currency_flag", "revenue_denominator_flag", "physical_unit_flag",
              "scope_flag", "basis_decision", "selected_value", "selected_unit", "selected_denominator",
              "scope_decision", "reviewer", "reviewed_at", "review_note", "scoring_authorized"]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({**{field: row.get(field, "") for field in fields},
                             "basis_decision": "", "selected_value": "", "selected_unit": "",
                             "selected_denominator": "", "scope_decision": "", "reviewer": "",
                             "reviewed_at": "", "review_note": "", "scoring_authorized": "False"})
    print(OUTPUT)


if __name__ == "__main__":
    main()
