#!/usr/bin/env python3
"""Assess research-ranking stability without changing ranking outputs."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/research/2025/ranking_sensitivity.json"
OUTPUT = ROOT / "output/audit/research_stability_gate_v1_2025.json"


def main() -> None:
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    unstable = int(data.get("unstable_company_count", 0))
    companies = int(data.get("company_count", 0))
    max_span = float(data.get("max_rank_span", 0) or 0)
    result = {
        "policy_version": "research-stability-gate-v1",
        "report_year": 2025,
        "company_count": companies,
        "unstable_company_count": unstable,
        "unstable_rate": round(unstable / companies, 6) if companies else None,
        "max_rank_span": max_span,
        "strategy_comparisons": data.get("strategy_comparisons", []),
        "status": "blocked_stability" if unstable else "stable_for_research_review",
        "research_preview_allowed": True,
        "formal_publishable": False,
        "required_action": "补充可审计观测并复核缺失策略敏感性；稳定性未达标前不得正式发布",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "status": result["status"], "unstable_company_count": unstable, "formal_publishable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
