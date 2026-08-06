#!/usr/bin/env python3
"""Build a ranked-company missing-data queue focused on key quantitative indicators.

Research tracking only. Does not authorize formal scoring or forge review signatures.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025_research_sasac.json"
OBS = ROOT / "output/research/2025/full_auto_observations_v39_enriched.csv"
RANKING = ROOT / "output/research/2025/full_auto_v39_enriched/ranking.csv"
COVERAGE = ROOT / "output/audit/all_markets_document_coverage_embedded_esg_2025.csv"
OUT_CSV = ROOT / "output/audit/ranked_company_key_data_gap_queue_v1_2025.csv"
OUT_JSON = ROOT / "output/audit/ranked_company_key_data_gap_queue_v1_2025.json"

KEY_CODES = (
    "Q_E_GHG_INTENSITY",
    "Q_E_ENERGY_INTENSITY",
    "Q_E_NOX_INTENSITY",
    "Q_E_SO2_INTENSITY",
    "Q_E_WATER_INTENSITY",
    "Q_E_SOLID_WASTE_INTENSITY",
    "Q_S_SAFETY_INVEST_RATE",
    "Q_S_RD_RATE",
    "Q_S_DIVIDEND_PER_SHARE",
    "Q_G_DEBT_ASSET_RATE",
)


def main() -> None:
    methodology = json.loads(METHODOLOGY.read_text(encoding="utf-8"))
    names = {item["code"]: item.get("name", "") for item in methodology["indicators"]}
    weights = {item["code"]: float(item.get("weight") or 0) for item in methodology["indicators"]}

    ranks: dict[str, dict[str, str]] = {}
    if RANKING.is_file():
        for row in csv.DictReader(RANKING.open(encoding="utf-8-sig")):
            # Client export has value+score twin rows; keep the numeric-value row.
            category = (row.get("数值类别") or row.get("value_kind") or "").strip()
            if category and category != "指标数值":
                continue
            code = (
                row.get("company_code")
                or row.get("stock_code")
                or row.get("证券代码")
                or ""
            ).strip()
            if code:
                ranks[code] = row

    coverage = {
        row["stock_code"]: row
        for row in csv.DictReader(COVERAGE.open(encoding="utf-8-sig"))
    } if COVERAGE.is_file() else {}

    present: dict[tuple[str, str], str] = {}
    company_names: dict[str, str] = {}
    for row in csv.DictReader(OBS.open(encoding="utf-8-sig")):
        code = row["company_code"]
        company_names[code] = row.get("company_name") or company_names.get(code, "")
        value = (row.get("value") or "").strip()
        if value and value != "None":
            present[(code, row["indicator_code"])] = value

    # Ranked pool: companies appearing in ranking, else observation companies.
    pool = sorted(ranks) if ranks else sorted(company_names)
    rows = []
    for code in pool:
        cov = coverage.get(code, {})
        rank_row = ranks.get(code, {})
        rank = (
            rank_row.get("rank")
            or rank_row.get("ranking")
            or rank_row.get("序号")
            or ""
        )
        missing = [ind for ind in KEY_CODES if (code, ind) not in present]
        if not missing:
            continue
        impact = sum(weights.get(ind, 0.0) for ind in missing)
        top200 = ""
        try:
            top200 = "true" if int(rank) <= 200 else "false"
        except ValueError:
            top200 = "unknown"
        esg_status = cov.get("esg_status") or "unknown"
        annual_status = cov.get("annual_status") or "unknown"
        if annual_status != "collected":
            action = "retry_annual_download"
        elif esg_status == "missing":
            action = "discover_independent_or_embedded_esg"
        else:
            action = "rule_recall_on_existing_text"
        rows.append({
            "company_code": code,
            "company_name": (
                company_names.get(code)
                or rank_row.get("company_name")
                or rank_row.get("公司简称")
                or ""
            ),
            "rank": rank,
            "top200": top200,
            "annual_status": annual_status,
            "esg_status": esg_status,
            "missing_key_count": str(len(missing)),
            "missing_key_weight_sum": f"{impact:.2f}",
            "missing_key_codes": "|".join(missing),
            "missing_key_names": "|".join(names.get(ind, ind) for ind in missing),
            "next_action": action,
            "scoring_authorized": "false",
        })

    rows.sort(
        key=lambda item: (
            -float(item["missing_key_weight_sum"]),
            -int(item["missing_key_count"]),
            int(item["rank"]) if str(item["rank"]).isdigit() else 10_000,
            item["company_code"],
        )
    )
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    action_counts = Counter(row["next_action"] for row in rows)
    indicator_miss = Counter()
    for row in rows:
        for code in row["missing_key_codes"].split("|"):
            if code:
                indicator_miss[code] += 1
    summary = {
        "policy_version": "ranked-company-key-data-gap-queue-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ranked_companies": len(pool),
        "companies_with_key_gaps": len(rows),
        "top200_with_key_gaps": sum(1 for row in rows if row["top200"] == "true"),
        "action_counts": dict(action_counts),
        "indicator_miss_counts": dict(indicator_miss.most_common()),
        "queue_csv": str(OUT_CSV.relative_to(ROOT)),
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "按关键定量缺数权重排序；优先对已有年报/ESG文本做规则召回，再补独立ESG下载。",
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
