#!/usr/bin/env python3
"""Refresh research-only ranking under exchange-disclosure / zero-missing rules.

Research scoring policy (user-directed, informal only):
1. Key quantitative indicators: accept exchange-listed disclosure values as-is
   (no extra raw-value confirmation gate).
2. Undisclosed / missing indicators score 0 (legacy_zero_v1).
3. Conflicts: prefer exchange official Chinese disclosure over English/derived;
   among equals prefer the current CI harvest.

Never authorizes formal release.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.io import read_observations, write_observations  # noqa: E402
from aegis_esg.methodology import load_methodology  # noqa: E402
from aegis_esg.models import Observation, ValueStatus  # noqa: E402
from aegis_esg.source_authority import (  # noqa: E402
    AUTHORITY_POLICY_VERSION,
    disclosure_authority,
    is_exchange_source,
)

METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025.json"
BASE_OBS = ROOT / "output/research/2025/full_auto_observations_v19.csv"
CI_CANDIDATES = ROOT / "output/audit/ci_incremental_candidates_v1_2025.csv"
CI_CONFIRMED = ROOT / "output/review/ci_auto_confirmed_research_2025.csv"
CI_UNRESOLVED = ROOT / "output/review/ci_unresolved_research_2025.csv"
CI_DECISIONS = ROOT / "output/audit/ci_auto_resolution_decisions_research_2025.csv"
MERGED_OBS = ROOT / "output/research/2025/full_auto_observations_v21_exchange_zero.csv"
RANK_DIR = ROOT / "output/research/2025/full_auto_v21_exchange_zero"
OVERLAY_SUMMARY = ROOT / "output/audit/research_ci_overlay_summary_v2_2025.json"
CONFLICT_AUDIT = ROOT / "output/audit/research_ci_conflict_resolution_v2_2025.csv"
KEY_ACCEPT_AUDIT = ROOT / "output/audit/research_exchange_key_accept_v1_2025.csv"
RUN_SUMMARY = ROOT / "output/audit/research_ranking_refresh_v2_2025.json"
TAG = "[research-only:exchange-zero-v1;not-formal]"
KEY_ACCEPT_TAG = "[research-only:exchange-key-accept-v1;no-raw-confirm;not-formal]"
MISSING_STRATEGY = "legacy_zero_v1"


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout or "command failed")
    if completed.stdout.strip():
        print(completed.stdout.strip(), file=sys.stderr)


def _tag(item: Observation, extra: str = TAG) -> Observation:
    evidence = item.evidence_text or ""
    if extra not in evidence:
        evidence = f"{evidence} {extra}".strip()
    return replace(item, evidence_text=evidence, status=ValueStatus.CONFIRMED)


def accept_exchange_key_candidates(by: dict, methodology) -> dict:
    """Accept exchange key-indicator harvest values without raw-value confirmation."""
    key_codes = {item.code for item in methodology.quantitative if item.key_indicator}
    if not CI_CANDIDATES.is_file():
        return {"accepted": 0, "replaced": 0, "skipped_non_exchange": 0, "rows": []}

    candidates = read_observations(CI_CANDIDATES, methodology)
    best: dict[tuple[str, int, str], Observation] = {}
    skipped_non_exchange = 0
    for raw in candidates:
        if raw.indicator_code not in key_codes or raw.value is None:
            continue
        if not is_exchange_source(raw):
            skipped_non_exchange += 1
            continue
        key = (raw.company_code, raw.report_year, raw.indicator_code)
        current = best.get(key)
        if current is None or float(raw.confidence or 0) > float(current.confidence or 0):
            best[key] = raw

    accepted = replaced = 0
    audit_rows: list[dict[str, object]] = []
    for key, raw in sorted(best.items()):
        item = _tag(raw, KEY_ACCEPT_TAG)
        existing = by.get(key)
        if existing is None:
            by[key] = item
            accepted += 1
            audit_rows.append({
                "company_code": item.company_code,
                "report_year": item.report_year,
                "indicator_code": item.indicator_code,
                "action": "added",
                "value": item.value,
                "source_url": item.source_url,
                "source_file": item.source_file,
            })
            continue
        if existing.value == item.value:
            if disclosure_authority(item) < disclosure_authority(existing):
                by[key] = item
            continue
        if disclosure_authority(item) <= disclosure_authority(existing):
            by[key] = item
            replaced += 1
            audit_rows.append({
                "company_code": item.company_code,
                "report_year": item.report_year,
                "indicator_code": item.indicator_code,
                "action": "replaced",
                "value": item.value,
                "prior_value": existing.value,
                "source_url": item.source_url,
                "source_file": item.source_file,
            })

    KEY_ACCEPT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "company_code", "report_year", "indicator_code", "action",
        "value", "prior_value", "source_url", "source_file",
    ]
    with KEY_ACCEPT_AUDIT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(audit_rows)

    return {
        "accepted": accepted,
        "replaced": replaced,
        "skipped_non_exchange": skipped_non_exchange,
        "candidate_pairs": len(best),
        "audit": str(KEY_ACCEPT_AUDIT.relative_to(ROOT)),
        "rows": audit_rows,
    }


def overlay() -> dict:
    methodology = load_methodology(METHODOLOGY)
    base = read_observations(BASE_OBS, methodology)
    ci = read_observations(CI_CONFIRMED, methodology) if CI_CONFIRMED.is_file() else []
    by = {(item.company_code, item.report_year, item.indicator_code): item for item in base}
    added = same = replaced = kept_base = 0
    conflict_rows: list[dict[str, object]] = []

    for raw in ci:
        item = _tag(raw)
        key = (item.company_code, item.report_year, item.indicator_code)
        existing = by.get(key)
        if existing is None:
            by[key] = item
            added += 1
            continue
        if existing.value == item.value:
            if disclosure_authority(item) < disclosure_authority(existing):
                by[key] = item
            same += 1
            continue

        choose_ci = disclosure_authority(item) <= disclosure_authority(existing)
        winner = "ci_exchange" if choose_ci else "base_kept"
        if choose_ci:
            by[key] = item
            replaced += 1
        else:
            kept_base += 1
        conflict_rows.append({
            "company_code": item.company_code,
            "report_year": item.report_year,
            "indicator_code": item.indicator_code,
            "base_value": existing.value,
            "ci_value": item.value,
            "winner": winner,
            "base_authority": "|".join(str(x) for x in disclosure_authority(existing)),
            "ci_authority": "|".join(str(x) for x in disclosure_authority(item)),
            "base_source_url": existing.source_url,
            "ci_source_url": item.source_url,
            "base_source_file": existing.source_file,
            "ci_source_file": item.source_file,
            "base_evidence": (existing.evidence_text or "")[:240],
            "ci_evidence": (item.evidence_text or "")[:240],
            "policy": "prefer_exchange_chinese_direct_then_ci_harvest",
        })

    key_accept = accept_exchange_key_candidates(by, methodology)

    rows = [by[key] for key in sorted(by)]
    MERGED_OBS.parent.mkdir(parents=True, exist_ok=True)
    write_observations(MERGED_OBS, rows)

    CONFLICT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "company_code", "report_year", "indicator_code", "base_value", "ci_value", "winner",
        "base_authority", "ci_authority", "base_source_url", "ci_source_url",
        "base_source_file", "ci_source_file", "base_evidence", "ci_evidence", "policy",
    ]
    with CONFLICT_AUDIT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(conflict_rows)

    summary = {
        "policy_version": "research-exchange-zero-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "conflict_policy": "prefer_exchange_chinese_direct_then_ci_harvest",
        "key_indicator_policy": "exchange_disclosure_accept_without_raw_confirm",
        "missing_strategy": MISSING_STRATEGY,
        "base_observations": len(base),
        "ci_confirmed_input": len(ci),
        "added": added,
        "same_value": same,
        "conflicts_total": len(conflict_rows),
        "conflicts_replaced_with_ci": replaced,
        "conflicts_kept_base": kept_base,
        "exchange_key_accept": {
            "accepted": key_accept["accepted"],
            "replaced": key_accept["replaced"],
            "candidate_pairs": key_accept["candidate_pairs"],
            "skipped_non_exchange": key_accept["skipped_non_exchange"],
            "audit": key_accept["audit"],
        },
        "merged_observations": len(rows),
        "company_count": len({item.company_code for item in rows}),
        "conflict_audit": str(CONFLICT_AUDIT.relative_to(ROOT)),
        "output": str(MERGED_OBS.relative_to(ROOT)),
        "scoring_authorized_formal": False,
        "research_ranking_authorized": True,
        "notice": (
            "关键指标以交易所披露直接采信（不另确认原始值）；未披露计0分；"
            "冲突以交易所中文官方披露优先。非正式榜单。"
        ),
    }
    OVERLAY_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    if not BASE_OBS.is_file():
        raise SystemExit(f"missing baseline observations: {BASE_OBS}")
    if not CI_CANDIDATES.is_file():
        raise SystemExit(f"missing CI candidates: {CI_CANDIDATES}")

    _run([
        sys.executable, "-m", "aegis_esg.cli",
        "--methodology", str(METHODOLOGY),
        "resolve-pending", str(CI_CANDIDATES),
        "--confirmed", str(CI_CONFIRMED),
        "--unresolved", str(CI_UNRESOLVED),
        "--decisions", str(CI_DECISIONS),
    ])
    overlay_summary = overlay()
    _run([
        sys.executable, "-m", "aegis_esg.cli",
        "--methodology", str(METHODOLOGY),
        "score", str(MERGED_OBS),
        "--mode", "research",
        "--missing-strategy", MISSING_STRATEGY,
        "--output-dir", str(RANK_DIR),
        "--title", "能源ESG研究预排名v21-交易所披露零缺失",
        "--limit", "0",
    ])
    demo_dir = ROOT / "output/demo/real_data_demo_2025"
    if demo_dir.is_dir() and RANK_DIR.is_dir():
        for name in (
            "ranking.html", "ranking.json", "ranking.csv",
            "ranking_metadata.json", "ranking_sensitivity.json",
        ):
            src = RANK_DIR / name
            if src.is_file():
                (demo_dir / name).write_bytes(src.read_bytes())
    result = {
        "policy_version": "research-ranking-refresh-v3-exchange-zero",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ranking_dir": str(RANK_DIR.relative_to(ROOT)),
        "ranking_html": str((RANK_DIR / "ranking.html").relative_to(ROOT)),
        "observations": str(MERGED_OBS.relative_to(ROOT)),
        "missing_strategy": MISSING_STRATEGY,
        "overlay": overlay_summary,
        "official_release": False,
        "scoring_authorized_formal": False,
        "notice": (
            "研究预排名：关键指标以交易所披露为准且不另确认原始值；未披露计0；"
            "不得作为正式榜单。"
        ),
    }
    RUN_SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
