#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_basis_review_template_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_basis_review_template_validation_v1_2025.json"
REQUIRED = {"basis_decision", "selected_value", "selected_unit", "selected_denominator", "scope_decision", "reviewer", "reviewed_at", "review_note"}


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or [])
        rows = list(reader)
    missing_fields = sorted(REQUIRED - fields)
    signed = [row for row in rows if any((row.get(field) or "").strip() for field in REQUIRED)]
    result = {"policy_version": "thin-basis-review-template-validation-v1", "row_count": len(rows),
              "missing_required_fields": missing_fields, "partially_filled_rows": len(signed),
              "template_valid": not missing_fields and not signed, "scoring_authorized": False,
              "decision": "blocked_until_complete_signed_review" if not missing_fields and not signed else "reject_template"}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
