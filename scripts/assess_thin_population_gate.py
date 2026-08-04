#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_population_gap_diagnostics_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_population_gate_assessment_v1_2025.json"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["indicator_code"]].append(row)
    indicators = []
    for code, items in sorted(grouped.items()):
        categories = Counter(row["diagnostic_category"] for row in items)
        has_closure = any("closure" in category for category in categories)
        indicators.append({
            "indicator_code": code,
            "indicator_name": items[0]["indicator_name"],
            "diagnostic_task_count": len(items),
            "diagnostic_categories": dict(categories),
            "gate_status": "methodology_review_required" if not has_closure else "evidence_review_required",
            "minimum_population": 20,
            "current_population": int(items[0]["indicator_population"]),
            "scoring_authorized": False,
            "required_decision": "确认同口径公开数据是否足以达到最低人口；否则保留薄样本警告并冻结缺失策略",
        })
    result = {"policy_version": "thin-population-gate-assessment-v1", "minimum_population": 20,
              "indicator_count": len(indicators), "scoring_authorized": False, "indicators": indicators}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
