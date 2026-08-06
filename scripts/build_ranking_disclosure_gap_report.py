#!/usr/bin/env python3
"""Explain why research ranking indicators still lack values (download vs disclosure vs rules)."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025_research_sasac.json"
OBS = ROOT / "output/research/2025/full_auto_observations_v34_enriched.csv"
BASELINE = ROOT / "output/research/2025/full_auto_v34_enriched/population_baseline.json"
COVERAGE = ROOT / "output/audit/all_markets_document_coverage_embedded_esg_2025.csv"
ISSUER_QUEUE = ROOT / "output/audit/issuer_website_gap_queue_v11_2025.csv"
OUT_JSON = ROOT / "output/audit/ranking_disclosure_gap_report_v1_2025.json"
OUT_CSV = ROOT / "output/audit/ranking_disclosure_gap_report_v1_2025.csv"


def main() -> None:
    methodology = json.loads(METHODOLOGY.read_text(encoding="utf-8"))
    indicators = {item["code"]: item for item in methodology["indicators"]}
    quant = [code for code, item in indicators.items() if item.get("kind") == "quantitative"]
    qual = [code for code, item in indicators.items() if item.get("kind") == "qualitative"]

    has_value: dict[str, set[str]] = defaultdict(set)
    for row in csv.DictReader(OBS.open(encoding="utf-8-sig")):
        if (row.get("value") or "").strip() in ("", "None"):
            continue
        has_value[row["indicator_code"]].add(row["company_code"])

    coverage_rows = list(csv.DictReader(COVERAGE.open(encoding="utf-8-sig"))) if COVERAGE.is_file() else []
    annual_ok = sum(1 for row in coverage_rows if row.get("annual_status") == "collected")
    esg_independent = sum(1 for row in coverage_rows if row.get("esg_status") == "collected")
    esg_embedded = sum(1 for row in coverage_rows if row.get("esg_status") == "embedded_in_annual")
    annual_missing = [
        row["stock_code"] for row in coverage_rows if row.get("annual_status") != "collected"
    ]

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    universe_n = int(baseline.get("universe_company_count") or 614)

    rows = []
    for code in quant:
        n = len(has_value.get(code, set()))
        rate = round(100.0 * n / universe_n, 2) if universe_n else 0.0
        item = indicators[code]
        if n >= 20 and rate >= 30:
            reason = "coverage_acceptable_for_research"
            next_action = "keep_monitoring"
        elif n >= 20:
            reason = "above_minimum_population_but_still_sparse_disclosure"
            next_action = "issuer_website_and_rule_recall_for_high_impact_gaps"
        elif code.startswith("Q_E_"):
            reason = "company_rarely_discloses_revenue_denominated_environmental_intensity"
            next_action = "issuer_website_esg_harvest_then_strict_extract_or_keep_missing"
        else:
            reason = "layout_or_formula_gap_or_true_non_disclosure"
            next_action = "diagnose_high_impact_queue_before_relaxing_rules"
        rows.append({
            "indicator_code": code,
            "name": item.get("name", ""),
            "dimension": item.get("dimension", ""),
            "key_indicator": str(bool(item.get("key_indicator"))),
            "disclosed_companies": n,
            "universe_companies": universe_n,
            "disclosure_rate_pct": rate,
            "gap_reason": reason,
            "next_action": next_action,
            "download_blocker": "false" if annual_ok >= 600 else "true",
        })

    rows.sort(key=lambda item: item["disclosed_companies"])
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    issuer_gap_rows = 0
    if ISSUER_QUEUE.is_file():
        issuer_gap_rows = sum(1 for _ in csv.DictReader(ISSUER_QUEUE.open(encoding="utf-8-sig")))

    summary = {
        "policy_version": "ranking-disclosure-gap-report-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "observations": str(OBS.relative_to(ROOT)),
        "universe_companies": universe_n,
        "observed_companies_with_any_obs": len({c for codes in has_value.values() for c in codes}),
        "document_coverage": {
            "annual_collected": annual_ok,
            "independent_esg_collected": esg_independent,
            "embedded_esg": esg_embedded,
            "annual_missing_codes": annual_missing,
        },
        "quantitative_indicator_count": len(quant),
        "qualitative_indicator_count": len(qual),
        "lowest_disclosure_quantitative": rows[:12],
        "reason_counts": dict(Counter(row["gap_reason"] for row in rows)),
        "issuer_website_gap_queue_rows": issuer_gap_rows,
        "channels": {
            "exchange_filings": "primary_complete_for_identity_coverage",
            "cninfo_fallback": "enabled_for_szse_antibot",
            "issuer_official_website": "research_harvest_available_unverified_document_declared_domains",
            "commercial_databases": "not_used",
        },
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": (
            "排名缺数主因是公司未按方法论口径披露（尤其环境强度收入分母），"
            "不是交易所PDF没下完。官网通道可补独立ESG，但不得伪造域名核验。"
        ),
        "output_csv": str(OUT_CSV.relative_to(ROOT)),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "annual_collected": annual_ok,
        "independent_esg": esg_independent,
        "lowest": [
            {"code": row["indicator_code"], "n": row["disclosed_companies"], "reason": row["gap_reason"]}
            for row in rows[:8]
        ],
        "output": str(OUT_JSON.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
