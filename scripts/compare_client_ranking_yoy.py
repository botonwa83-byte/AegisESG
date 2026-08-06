#!/usr/bin/env python3
"""Soft year-over-year continuity check: client Top200 (FY2024) vs local ranking (FY2025).

Not a fit target. Large jumps are attributed for diagnosis only.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]

CLIENT_TOP200 = ROOT / "data/reference/2025_top200_securities_ocr.csv"
CLIENT_TOP35 = ROOT / "data/reference/2025_top35_excerpt.csv"
DEFAULT_RANKING = ROOT / "output/research/2025/full_auto_v34_enriched/ranking.json"
FALLBACK_RANKING = ROOT / "output/research/2025/full_auto_v33_enriched/ranking.json"
OUTPUT_JSON = ROOT / "output/audit/client_yoy_soft_check_v11.json"
OUTPUT_CSV = ROOT / "output/audit/client_yoy_soft_check_v11.csv"


def load_client_codes() -> list[str]:
    rows = list(csv.DictReader(CLIENT_TOP200.open(encoding="utf-8-sig")))
    codes: list[str] = []
    seen: set[str] = set()
    for row in rows:
        code = (row.get("current_stock_code") or row.get("stock_code") or "").strip()
        if code and code not in seen:
            codes.append(code)
            seen.add(code)
    return codes


def load_top35() -> dict[str, float]:
    out: dict[str, float] = {}
    for row in csv.DictReader(CLIENT_TOP35.open(encoding="utf-8-sig")):
        raw = row["证券代码"].split("/")[0].strip()
        out[raw] = float(row["ESG分值"])
    return out


def main() -> None:
    ranking_path = DEFAULT_RANKING if DEFAULT_RANKING.is_file() else FALLBACK_RANKING
    if not ranking_path.is_file():
        raise SystemExit(f"missing ranking: {ranking_path}")
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    ours = {row["company_code"]: row for row in ranking}
    client_codes = load_client_codes()
    top35 = load_top35()

    our_top200 = {row["company_code"] for row in ranking if int(row.get("rank") or 10**9) <= 200}
    overlap = len(our_top200 & set(client_codes))
    in_universe = [c for c in client_codes if c in ours]
    ranks = [int(ours[c]["rank"]) for c in in_universe]
    jumps = []
    for idx, code in enumerate(client_codes, 1):
        row = ours.get(code)
        if row is None:
            jumps.append({
                "client_rank_approx": idx,
                "company_code": code,
                "our_rank": None,
                "our_score": None,
                "disclosure_rate": None,
                "category": "missing_from_our_universe",
            })
            continue
        our_rank = int(row["rank"])
        category = "stable_like"
        if idx <= 50 and our_rank > 200:
            category = "client_top50_to_outside_our_top200"
        elif idx <= 200 and our_rank > 400:
            category = "client_top200_to_our_bottom_half"
        elif our_rank <= 50 and idx > 150:
            category = "our_top50_but_client_lower"
        jumps.append({
            "client_rank_approx": idx,
            "company_code": code,
            "company_name": row.get("company_name"),
            "our_rank": our_rank,
            "our_score": row.get("total_score"),
            "disclosure_rate": row.get("disclosure_rate"),
            "category": category,
        })

    top35_rows = []
    for code, client_score in top35.items():
        row = ours.get(code)
        top35_rows.append({
            "company_code": code,
            "client_score": client_score,
            "our_rank": None if row is None else row.get("rank"),
            "our_score": None if row is None else row.get("total_score"),
            "score_delta": None if row is None else round(float(row["total_score"]) - client_score, 2),
        })

    anomalous = [r for r in jumps if r["category"] not in {"stable_like"}]
    summary = {
        "audit_version": "client-yoy-soft-check-v2",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "client_evaluation_year": 2025,
        "client_report_year": 2024,
        "our_evaluation_year": 2026,
        "our_report_year": 2025,
        "our_ranking": str(ranking_path.relative_to(ROOT)),
        "client_unique_codes": len(client_codes),
        "our_company_count": len(ranking),
        "top200_overlap_count": overlap,
        "top200_overlap_rate": round(overlap / 200, 4),
        "client_codes_in_our_universe": len(in_universe),
        "mean_our_rank_of_client_top200": round(mean(ranks), 2) if ranks else None,
        "median_our_rank_of_client_top200": int(median(ranks)) if ranks else None,
        "client_top200_in_our_top50": sum(1 for c in client_codes if c in ours and int(ours[c]["rank"]) <= 50),
        "client_top200_in_our_top200": sum(1 for c in client_codes if c in ours and int(ours[c]["rank"]) <= 200),
        "anomalous_count": len(anomalous),
        "anomaly_categories": {
            key: sum(1 for r in anomalous if r["category"] == key)
            for key in sorted({r["category"] for r in anomalous})
        },
        "notice": (
            "相邻年度软对照：年差正常，不要求严格对齐。"
            "异常跳变用于检查算法偏离与披露缺口，禁止为提高重合率改分。"
        ),
        "top35_score_compare": top35_rows,
        "anomalies": anomalous[:80],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = [
            "client_rank_approx", "company_code", "company_name", "our_rank",
            "our_score", "disclosure_rate", "category",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(jumps)
    print(json.dumps({
        "output_json": str(OUTPUT_JSON.relative_to(ROOT)),
        "top200_overlap_rate": summary["top200_overlap_rate"],
        "anomalous_count": summary["anomalous_count"],
        "ranking": summary["our_ranking"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
