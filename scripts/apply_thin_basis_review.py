#!/usr/bin/env python3
"""Safely evaluate completed thin-population reviews without silently authorizing scores."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_basis_review_template_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_basis_review_application_v1_2025.json"
REQUIRED = ("basis_decision", "selected_value", "selected_unit", "selected_denominator",
            "scope_decision", "reviewer", "reviewed_at", "review_note")
CONFIRM = {"confirm", "confirmed", "确认", "通过"}
DECISIONS = CONFIRM | {"reject", "rejected", "拒绝", "保留缺失", "retain_missing"}


def evaluate(rows: list[dict[str, str]]) -> dict:
    missing = []
    confirmed = []
    invalid_decisions = []
    for row in rows:
        code = row.get("company_code", "")
        empty = [field for field in REQUIRED if not (row.get(field) or "").strip()]
        if empty:
            missing.append({"company_code": code, "indicator_code": row.get("indicator_code", ""), "fields": empty})
        if (row.get("basis_decision") or "").strip().lower() in CONFIRM:
            confirmed.append(code)
        decision = (row.get("basis_decision") or "").strip().lower()
        if decision and decision not in DECISIONS:
            invalid_decisions.append({"company_code": code, "indicator_code": row.get("indicator_code", ""), "decision": decision})
    ready = bool(rows) and not missing and not invalid_decisions
    return {
        "policy_version": "thin-basis-review-application-v1",
        "row_count": len(rows),
        "incomplete_rows": len(missing),
        "confirmed_rows": len(confirmed),
        "incomplete_examples": missing[:20],
        "invalid_decisions": invalid_decisions[:20],
        "status": "ready_for_secondary_authorization" if ready else ("reject_template" if invalid_decisions else "blocked_external_review"),
        "candidate_observations_written": False,
        "scoring_authorized": False,
        "decision": "requires_independent_secondary_authorization" if ready else ("use_allowed_basis_decision" if invalid_decisions else "complete_all_required_review_fields"),
    }


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = evaluate(rows)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
