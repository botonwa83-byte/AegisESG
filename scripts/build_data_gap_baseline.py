#!/usr/bin/env python3
"""Create the single, explainable data-gap queue used by the next collection stage."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from aegis_esg.methodology import load_methodology

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "output/audit/all_markets_quantitative_candidate_tasks_v22_2025.csv"
COVERAGE = ROOT / "output/audit/all_markets_document_coverage_embedded_esg_2025.csv"
METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025.json"
OUT = ROOT / "output/audit/data_gap_baseline_v1_2025.csv"
SUMMARY = ROOT / "output/audit/data_gap_baseline_summary_v1_2025.json"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    tasks = read_csv(TASKS)
    coverage = {row["stock_code"]: row for row in read_csv(COVERAGE)}
    methodology = load_methodology(METHODOLOGY)
    weights = {item.code: float(item.weight) for item in methodology.quantitative}
    result = []
    for row in tasks:
        doc = coverage.get(row["company_code"], {})
        annual = doc.get("annual_status", "unknown")
        if row["status"] == "candidate_available":
            reason, action = "candidate_available", "review_candidates"
        elif annual in {"missing", "failed"}:
            reason, action = "missing_document", "discover_or_download_annual_report"
        else:
            reason, action = "candidate_not_found_needs_diagnostic", "diagnose_extraction_or_disclosure"
        score = (float(row.get("priority") or 0) + weights.get(row["indicator_code"], 0) * 10
                 + (20 if row["key_indicator"] == "True" else 0)
                 + (15 if row["status"] == "candidate_available" else 0))
        result.append({**row, "annual_status": annual, "esg_status": doc.get("esg_status", "unknown"),
                       "missing_reason": reason, "next_action": action, "impact_priority": round(score, 4)})
    result.sort(key=lambda row: (-row["impact_priority"], row["company_code"], row["indicator_code"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as stream:
        fields = list(result[0])
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(result)
    summary = {"version": "data-gap-baseline-v1", "task_count": len(result),
               "reason_counts": dict(Counter(row["missing_reason"] for row in result)),
               "action_counts": dict(Counter(row["next_action"] for row in result)),
               "top_priority": result[:50]}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("task_count", "reason_counts", "action_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
