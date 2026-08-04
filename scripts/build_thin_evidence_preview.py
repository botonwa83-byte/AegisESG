#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_population_gap_diagnostics_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_evidence_preview_v1_2025.csv"
SUMMARY = ROOT / "output/audit/thin_evidence_preview_summary_v1_2025.json"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected = [row for row in rows if row["diagnostic_category"] in {
        "possible_clean_energy_revenue_closure", "ambiguous_intensity_disclosure",
        "related_disclosure_without_compatible_intensity",
    }]
    preview = []
    for row in selected:
        preview.append({
            "company_code": row["company_code"], "company_name": row["company_name"],
            "report_year": row.get("report_year", "2025"), "indicator_code": row["indicator_code"],
            "indicator_name": row["indicator_name"], "diagnostic_category": row["diagnostic_category"],
            "source_file": row["diagnostic_text_files"], "source_pages": row["source_pages"],
            "evidence_text": row["diagnostic_excerpt"], "status": "pending_basis_review",
            "recommended_action": "核验同口径分母、单位、边界和报告期后再决定是否形成候选",
            "scoring_authorized": "False",
        })
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(preview[0]) if preview else ["company_code"])
        writer.writeheader(); writer.writerows(preview)
    summary = {"policy_version": "thin-evidence-preview-v1", "preview_count": len(preview),
               "category_counts": {}, "scoring_authorized": False}
    for row in preview:
        summary["category_counts"][row["diagnostic_category"]] = summary["category_counts"].get(row["diagnostic_category"], 0) + 1
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
