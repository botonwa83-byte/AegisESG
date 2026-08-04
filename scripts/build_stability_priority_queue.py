#!/usr/bin/env python3
"""Prioritize evidence remediation for companies whose preview rank is unstable."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/research/2025/ranking_sensitivity.json"
OUTPUT = ROOT / "output/audit/research_stability_priority_queue_v1_2025.csv"
SUMMARY = ROOT / "output/audit/research_stability_priority_queue_v1_2025_summary.json"


def main() -> None:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    rows = []
    for item in data.get("companies", []):
        disclosure = float(item.get("disclosure_rate", 0) or 0)
        # Rates above 1 can occur with multiple evidence records; cap only for prioritization.
        missing_factor = max(0.0, 1.0 - min(disclosure, 1.0))
        priority = round(float(item.get("rank_span", 0) or 0) * (0.5 + missing_factor), 6)
        rows.append({"company_code": item.get("company_code", ""), "company_name": item.get("company_name", ""),
                     "best_rank": item.get("best_rank", ""), "worst_rank": item.get("worst_rank", ""),
                     "rank_span": item.get("rank_span", ""), "score_span": item.get("score_span", ""),
                     "disclosure_rate": item.get("disclosure_rate", ""), "credibility_grade": item.get("credibility_grade", ""),
                     "stability_priority_score": priority, "next_action": "优先补证并复核缺失策略敏感性"})
    rows.sort(key=lambda row: row["stability_priority_score"], reverse=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["company_code"])
        writer.writeheader(); writer.writerows(rows)
    summary = {"policy_version": "research-stability-priority-v1", "company_count": len(rows),
               "top_priority_count": min(50, len(rows)), "scoring_authorized": False,
               "formal_publishable": False, "source": str(INPUT.relative_to(ROOT))}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "company_count": len(rows), "top_priority_count": summary["top_priority_count"], "formal_publishable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
