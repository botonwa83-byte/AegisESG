#!/usr/bin/env python3
"""Turn high-impact diagnostic categories into safe next actions."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/data_gap_high_impact_diagnostics_v1_2025.csv"
OUTPUT = ROOT / "output/audit/data_gap_diagnostic_action_queue_v1_2025.csv"
SUMMARY = ROOT / "output/audit/data_gap_diagnostic_action_queue_summary_v1_2025.json"


def action(category: str, indicator: str) -> tuple[str, str]:
    if category in {"possible_balance_sheet_formula_closure", "possible_rd_revenue_formula_closure",
                    "possible_safety_revenue_formula_closure", "possible_two_year_ghg_formula_closure",
                    "possible_hazardous_waste_revenue_closure", "possible_clean_energy_revenue_closure"}:
        return "formula_recompute_preview", "重跑公式派生并保留输入字段"
    if category in {"disclosed_foreign_currency_denominator", "disclosed_non_revenue_denominator",
                    "disclosed_scope_mismatch_requires_review", "dividend_disclosed_foreign_currency",
                    "ambiguous_intensity_disclosure"}:
        return "manual_basis_review", "人工核验单位、分母、边界和报告期"
    if category in {"related_fields_incomplete", "related_disclosure_without_compatible_intensity"}:
        return "inspect_source_table", "检查原始PDF表格并判断是否可形成同口径值"
    if category in {"no_matching_disclosure_in_text", "no_dividend_per_share_disclosure"}:
        return "retain_missing_pending_scan", "保留缺失并记录已扫描范围，避免伪造零值"
    return "specialist_diagnostic", "进入专项方法论诊断"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    output = []
    for row in rows:
        next_action, instruction = action(row["diagnostic_category"], row["indicator_code"])
        output.append({**row, "diagnostic_action": next_action, "action_instruction": instruction,
                       "scoring_authorized": "False"})
    output.sort(key=lambda row: (row["diagnostic_action"], int(row["batch_task_rank"]), row["company_code"]))
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(output)
    summary = {"policy_version": "diagnostic-action-queue-v1", "task_count": len(output),
               "action_counts": dict(Counter(row["diagnostic_action"] for row in output)),
               "scoring_authorized": False}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
