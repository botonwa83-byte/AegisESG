from __future__ import annotations

import csv
import json
from pathlib import Path


def recognize_embedded_esg_coverage(coverage_path: str | Path, evidence_path: str | Path) -> tuple[list[dict], dict]:
    with Path(evidence_path).open(encoding="utf-8-sig", newline="") as stream:
        evidence = list(csv.DictReader(stream))
    embedded = {row["company_code"].strip().upper() for row in evidence if row.get("company_code")}
    with Path(coverage_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    changed = 0
    for row in rows:
        code = row["stock_code"].strip().upper()
        if row["esg_status"].strip() != "collected" and code in embedded:
            row["esg_status"] = "embedded_in_annual"
            if row.get("next_action") == "discover_esg_report":
                row["next_action"] = "use_embedded_esg_section"
            changed += 1
    return rows, {
        "policy_version": "embedded-esg-coverage-v1", "company_count": len(rows),
        "embedded_evidence_company_count": len(embedded), "upgraded_company_count": changed,
        "annual_coverage_count": sum(row.get("annual_status", "").strip() == "collected" for row in rows),
        "esg_coverage_count": sum(
            row.get("esg_status", "").strip() in {"collected", "embedded_in_annual"} for row in rows
        ),
        "independent_esg_coverage_count": sum(row.get("esg_status", "").strip() == "collected" for row in rows),
        "complete": True,
    }


def write_embedded_esg_coverage(output_path: str | Path, summary_path: str | Path,
                                rows: list[dict], summary: dict) -> None:
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
        if rows: writer.writeheader(); writer.writerows(rows)
    summary_output = Path(summary_path); summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
