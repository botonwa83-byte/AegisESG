#!/usr/bin/env python3
"""Collect toward the frozen energy universe and rescore with universe baselines.

Client-aligned policy:
- Industry μ/σ from disclosed values inside the evaluation universe only.
- Target subject count 632; current candidate freeze may be lower (external gap).
- Missing annuals are queued for retry; no forged universe rows.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.universe import audit_universe, read_universe  # noqa: E402

UNIVERSE = ROOT / "data/universe/energy_historical_candidates_2026.csv"
METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025_research_sasac.json"
OBS = ROOT / "output/research/2025/full_auto_observations_v23_authority_fill.csv"
COVERAGE = ROOT / "output/audit/all_markets_document_coverage_embedded_esg_2025.csv"
RANK_DIR = ROOT / "output/research/2025/full_auto_v24_universe_baseline"
SUMMARY = ROOT / "output/audit/universe_baseline_ranking_v1_2025.json"
GAP_CSV = ROOT / "output/audit/universe_collection_gaps_v1_2025.csv"
EXPECTED = 632
REPORT_YEAR = 2025


def _run(args: list[str]) -> str:
    completed = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout or "command failed")
    return (completed.stdout or "").strip()


def collection_gaps() -> list[dict]:
    universe = [c for c in read_universe(UNIVERSE) if c.included]
    coverage = {}
    if COVERAGE.is_file():
        coverage = {
            row["stock_code"]: row
            for row in csv.DictReader(COVERAGE.open(encoding="utf-8-sig"))
        }
    rows = []
    for company in universe:
        cov = coverage.get(company.stock_code, {})
        annual = cov.get("annual_status") or "missing_from_coverage"
        esg = cov.get("esg_status") or "missing_from_coverage"
        if annual != "collected" or esg in {"missing", "missing_from_coverage"}:
            rows.append({
                "stock_code": company.stock_code,
                "company_name": company.company_name,
                "exchange": company.exchange,
                "annual_status": annual,
                "esg_status": esg,
                "priority": "P0_annual" if annual != "collected" else "P1_esg",
                "next_action": (
                    "retry_exchange_annual_download"
                    if annual != "collected" else
                    "discover_esg_or_embedded_fallback"
                ),
            })
    # Also mark the 18-subject shortfall as external (not inventable).
    rows.append({
        "stock_code": "",
        "company_name": f"SUBJECT_SHORTFALL_{len(universe)}_OF_{EXPECTED}",
        "exchange": "ALL",
        "annual_status": "n/a",
        "esg_status": "n/a",
        "priority": "P0_external_universe",
        "next_action": "provide_signed_632_name_list_or_inclusion_evidence",
    })
    return rows


def main() -> None:
    if not UNIVERSE.is_file():
        raise SystemExit(f"missing universe: {UNIVERSE}")
    if not OBS.is_file():
        raise SystemExit(f"missing observations: {OBS}")
    if not METHODOLOGY.is_file():
        raise SystemExit(f"missing methodology: {METHODOLOGY}")

    gaps = collection_gaps()
    GAP_CSV.parent.mkdir(parents=True, exist_ok=True)
    with GAP_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = [
            "stock_code", "company_name", "exchange", "annual_status", "esg_status",
            "priority", "next_action",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(gaps)

    # Retry manifest for true annual gaps (exchange first).
    annual_gaps = [row for row in gaps if row["priority"] == "P0_annual" and row["stock_code"]]
    retry_manifest = ROOT / "output/audit/universe_annual_gap_retry_manifest_v1_2025.csv"
    if annual_gaps:
        # Reuse scheduled collection builder when available; otherwise write a minimal task list.
        with retry_manifest.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["stock_code", "company_name", "report_year", "document_type", "reason"],
                lineterminator="\n",
            )
            writer.writeheader()
            for row in annual_gaps:
                writer.writerow({
                    "stock_code": row["stock_code"],
                    "company_name": row["company_name"],
                    "report_year": REPORT_YEAR,
                    "document_type": "annual_report",
                    "reason": "universe_baseline_missing_annual",
                })
                writer.writerow({
                    "stock_code": row["stock_code"],
                    "company_name": row["company_name"],
                    "report_year": REPORT_YEAR,
                    "document_type": "esg_report",
                    "reason": "universe_baseline_missing_esg",
                })

    # Reuse latest authority-filled observations; optional re-fill via --refill.
    obs_path = ROOT / "output/research/2025/full_auto_observations_v23_authority_fill.csv"
    if "--refill" in sys.argv:
        fill = ROOT / "scripts/fill_missing_from_authoritative_sources.py"
        if fill.is_file():
            _run([sys.executable, str(fill)])
    score_out = _run([
        sys.executable, "-m", "aegis_esg.cli",
        "--methodology", str(METHODOLOGY),
        "score", str(obs_path),
        "--mode", "research",
        "--missing-strategy", "legacy_zero_v1",
        "--universe", str(UNIVERSE),
        "--expected-companies", str(EXPECTED),
        "--minimum-population", "20",
        "--output-dir", str(RANK_DIR),
        "--title", "能源ESG研究预排名v24-宇宙披露基准",
        "--limit", "0",
    ])

    demo = ROOT / "output/demo/real_data_demo_2025"
    if demo.is_dir() and RANK_DIR.is_dir():
        for name in (
            "ranking.html", "ranking.json", "ranking.csv",
            "ranking_metadata.json", "ranking_sensitivity.json", "population_baseline.json",
        ):
            src = RANK_DIR / name
            if src.is_file():
                (demo / name).write_bytes(src.read_bytes())

    universe = read_universe(UNIVERSE)
    obs_codes = set()
    with obs_path.open(encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            obs_codes.add(row["company_code"])
    audit = audit_universe(universe, EXPECTED, obs_codes).as_dict()
    baseline = {}
    baseline_path = RANK_DIR / "population_baseline.json"
    if baseline_path.is_file():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    summary = {
        "policy_version": "universe-baseline-ranking-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "expected_companies": EXPECTED,
        "universe": str(UNIVERSE.relative_to(ROOT)),
        "universe_audit": audit,
        "collection_gaps": str(GAP_CSV.relative_to(ROOT)),
        "annual_gap_retry_manifest": str(retry_manifest.relative_to(ROOT)) if annual_gaps else None,
        "annual_gap_count": len(annual_gaps),
        "subject_shortfall": max(EXPECTED - int(audit["included_company_count"]), 0),
        "ranking_dir": str(RANK_DIR.relative_to(ROOT)),
        "population_baseline": {
            "thin_population_indicator_count": baseline.get("thin_population_indicator_count"),
            "minimum_population_gate_passed": baseline.get("minimum_population_gate_passed"),
            "formal_baseline_ready": baseline.get("formal_baseline_ready"),
        },
        "score_cli": score_out,
        "official_release": False,
        "notice": (
            "已按宇宙内披露样本测算行业基准；主体未达632或薄样本未清零前不得正式发布。"
            "缺18家名录需外部输入；2家港股年报继续交易所重试。"
        ),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ranking_dir": summary["ranking_dir"],
        "included": audit["included_company_count"],
        "expected": EXPECTED,
        "annual_gaps": len(annual_gaps),
        "thin_indicators": baseline.get("thin_population_indicator_count"),
        "formal_baseline_ready": baseline.get("formal_baseline_ready"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
