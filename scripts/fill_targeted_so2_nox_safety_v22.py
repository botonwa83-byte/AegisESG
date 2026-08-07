#!/usr/bin/env python3
"""Targeted research fill for SO2/NOx/safety recall (v22 → v45).

Clue-filtered re-extract for companies missing key intensities/rates.
Focus: Chinese SO2/NOx joint narrative, traditional KPI headers,
short-label paren rows, target-achievement actual emissions; prior EN clues retained. Research-only.
Does not map 硫氧化物/SOx to SO2. Does not use HKD revenue without FX.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.env_intensity import (  # noqa: E402
    CompanyDocument,
    derive_env_intensity_candidates,
)
from aegis_esg.extraction import (  # noqa: E402
    extract_indicator_candidates,
    read_page_text_export,
    resolve_text_export_path,
)
from aegis_esg.io import read_observations, write_observations  # noqa: E402
from aegis_esg.methodology import load_methodology  # noqa: E402
from aegis_esg.models import Observation, ValueStatus  # noqa: E402
from aegis_esg.source_authority import prefer, source_tier  # noqa: E402
from aegis_esg.social_invest import derive_social_invest_candidates  # noqa: E402

METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025_research_sasac.json"
BASE_OBS = ROOT / "output/research/2025/full_auto_observations_v44_enriched.csv"
DOCUMENT_INDEX = ROOT / "data/raw/all_markets_document_index.csv"
CI_INDEX = ROOT / "output/sync/official_document_index.csv"
TEXT_ROOT = ROOT / "data/text"
OUT_OBS = ROOT / "output/research/2025/full_auto_observations_v45_enriched.csv"
AUDIT_JSON = ROOT / "output/audit/authority_gap_fill_v22_2025.json"
AUDIT_CSV = ROOT / "output/audit/authority_gap_fill_v22_2025.csv"
TAG = "[research-only:authority-gap-fill-v22;not-formal]"
TARGET = {"Q_E_SO2_INTENSITY", "Q_E_NOX_INTENSITY", "Q_S_SAFETY_INVEST_RATE"}

CLUE = re.compile(
    r"(?:"
    r"安全生产投入(?:金额)?\s*(?:万元|亿元)|"
    r"职业健康(?:与)?安全生产(?:总)?投入|"
    r"全年安全生产投入金额达|"
    r"废气中氮氧化物|"
    r"氮氧化物总排放量|"
    r"氮氧化物(?:\s*[（(]\s*NO[xXₓ]\s*[）)])?\s*排放强度\s*\n\s*千克\s*[／/]\s*万元|"
    r"Nitrogen\s+oxides?\s*\(\s*NOx\s*\)\s*kg|"
    r"(?:Total\s+)?(?:sulfur|sulphur)\s+dioxide\s*\(\s*SO2\s*\)|"
    r"Sulphur\s+dioxide\s*\(\s*SO2\s*\)\s*\n\s*Emissions\s*\(\s*tonnes\s*\)|"
    r"Total\s+sulfur\s+dioxide\s*\(\s*SO2\s*\)\s*\n\s*emissions\s+Ton\b|"
    r"Sulphur\s+dioxide\s*\(\s*SO2\s*\)\s+Tonnes\b|"
    r"二氧化硫[、,]\s*氮氧化物[、,]\s*(?:烟尘|颗粒物)年排放量分别为|"
    r"二氧化硫(?:\s*SO2)?\s*排放量\s*吨|"
    r"二氧化硫（SO2）\s*吨|"
    r"二氧化硫\s+年度排放量不超过|"
    r"指標\s*單位\s*20\d{2}"
    r")",
    re.I,
)


def _load_index(codes: set[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for path in (DOCUMENT_INDEX, CI_INDEX):
        if not path.is_file():
            continue
        for row in csv.DictReader(path.open(encoding="utf-8-sig")):
            code = (row.get("company_code") or "").strip()
            if code not in codes or str(row.get("report_year")) != "2025":
                continue
            local = (row.get("local_path") or "").strip()
            key = f"{code}|{row.get('document_type')}|{local}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _has_clue(index_rows: list[dict]) -> bool:
    for row in index_rows:
        text_path = resolve_text_export_path(TEXT_ROOT, row)
        if text_path is None or not text_path.exists():
            continue
        try:
            text = text_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if CLUE.search(text):
            return True
    return False


def _extract(code: str, name: str, index_rows: list[dict]) -> list[Observation]:
    company_docs: list[CompanyDocument] = []
    candidates: list[Observation] = []
    for row in index_rows:
        text_path = resolve_text_export_path(TEXT_ROOT, row)
        if text_path is None or not text_path.exists():
            continue
        try:
            pages = read_page_text_export(text_path)
        except Exception:
            continue
        candidates.extend(
            extract_indicator_candidates(
                pages, code, name, 2025, row.get("source_url") or "", row.get("local_path") or "",
            )
        )
        company_docs.append(
            CompanyDocument(
                row.get("document_type") or "annual_report",
                pages,
                row.get("source_url") or "",
                row.get("local_path") or "",
            )
        )
    have = frozenset(item.indicator_code for item in candidates)
    candidates.extend(derive_env_intensity_candidates(code, name, 2025, company_docs, have))
    have2 = frozenset(item.indicator_code for item in candidates)
    candidates.extend(derive_social_invest_candidates(code, name, 2025, company_docs, have2))
    return [item for item in candidates if item.indicator_code in TARGET and item.value is not None]


def _quality(item: Observation) -> tuple[int, float]:
    evidence = item.evidence_text or ""
    if item.indicator_code == "Q_E_SO2_INTENSITY" and re.search(
        r"硫氧化物|硫化物|SOx", evidence,
    ) and not re.search(r"二氧化硫|SO2|SO₂", evidence):
        return 99, 0.0
    if item.indicator_code == "Q_E_NOX_INTENSITY" and re.search(r"专利|实用新型|发明", evidence):
        return 99, 0.0
    rank = 3
    if "vertical-two-year" in evidence:
        rank = 0
    elif "Chinese" in evidence and "table row" in evidence and "single-unit-value-revenue" in evidence:
        rank = 2
    elif "Chinese" in evidence and "table row" in evidence:
        rank = 0
    elif "中文跨表派生" in evidence or "English year-header" in evidence:
        rank = 0
    elif "中文投入占比派生" in evidence:
        rank = 1
    if len(evidence) > 200 and re.search(r"(?:走进|公司概况|ENVIRONMENTAL)", evidence, re.I):
        rank = 9
    return rank, -float(item.confidence or 0)


def _best(items: list[Observation]) -> Observation | None:
    ranked = sorted(items, key=_quality)
    if not ranked or _quality(ranked[0])[0] >= 90:
        return None
    best_rank = _quality(ranked[0])[0]
    band = [item for item in ranked if _quality(item)[0] == best_rank]
    winner = band[0]
    for item in band[1:]:
        winner = prefer(winner, item)
    return winner


def _tag(item: Observation) -> Observation:
    evidence = item.evidence_text or ""
    if TAG not in evidence:
        evidence = f"{evidence} {TAG}".strip()
    return replace(item, evidence_text=evidence, status=ValueStatus.CONFIRMED)


def _should_replace(existing: Observation, candidate: Observation, force: bool = False) -> bool:
    if existing.value is not None and abs(float(candidate.value) - float(existing.value)) <= max(
        1e-9, abs(float(existing.value)) * 1e-9,
    ):
        return False
    if force and _quality(candidate)[0] < 90:
        return _quality(candidate) <= _quality(existing)
    return _quality(candidate) < _quality(existing)


def main() -> None:
    methodology = load_methodology(
        METHODOLOGY if METHODOLOGY.is_file() else ROOT / "data/methodologies/energy_esg_2025.json"
    )
    base = read_observations(BASE_OBS, methodology)
    by_key = {(o.company_code, o.report_year, o.indicator_code): o for o in base}
    names = {o.company_code: o.company_name for o in base}

    present = {
        (o.company_code, o.indicator_code): o
        for o in base
        if o.report_year == 2025 and o.value is not None and o.indicator_code in TARGET
    }
    gap_codes: set[str] = set()
    force_codes: set[str] = set()
    for code in names:
        for indicator in TARGET:
            existing = present.get((code, indicator))
            if existing is None:
                gap_codes.add(code)
                continue
            evidence = existing.evidence_text or ""
            if (
                indicator == "Q_E_NOX_INTENSITY"
                and "single-unit-value-revenue" in evidence
                and "vertical-two-year" not in evidence
            ):
                force_codes.add(code)
                gap_codes.add(code)
            if indicator == "Q_E_NOX_INTENSITY" and re.search(r"专利|实用新型", evidence):
                force_codes.add(code)
                gap_codes.add(code)

    index_rows = _load_index(gap_codes)
    by_company: dict[str, list[dict]] = defaultdict(list)
    for row in index_rows:
        by_company[row["company_code"]].append(row)

    target_codes = sorted(
        code for code in gap_codes
        if code in force_codes or _has_clue(by_company.get(code, []))
    )

    fills: list[dict] = []
    added = replaced = 0
    for code in target_codes:
        raw = _extract(code, names.get(code, code), by_company.get(code, []))
        grouped: dict[str, list[Observation]] = defaultdict(list)
        for item in raw:
            grouped[item.indicator_code].append(item)
        for indicator, items in grouped.items():
            best = _best(items)
            if best is None:
                continue
            best = _tag(best)
            key = (code, 2025, indicator)
            existing = by_key.get(key)
            if existing is None or existing.value is None:
                by_key[key] = best
                added += 1
                action = "filled_missing"
            elif _should_replace(existing, best, force=(code in force_codes)):
                by_key[key] = best
                replaced += 1
                action = "replaced_reextract_correction"
            else:
                continue
            fills.append({
                "company_code": code,
                "indicator_code": indicator,
                "action": action,
                "value": best.value,
                "prior_value": "" if existing is None else existing.value,
                "tier": source_tier(best).name,
                "source_file": best.source_file,
                "evidence": (best.evidence_text or "")[:180],
            })

    rows = [by_key[k] for k in sorted(by_key)]
    OUT_OBS.parent.mkdir(parents=True, exist_ok=True)
    write_observations(OUT_OBS, rows)
    with AUDIT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["company_code", "indicator_code", "action", "value", "prior_value", "tier", "source_file", "evidence"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(fills)
    summary = {
        "policy_version": "authority-gap-fill-v22-targeted-so2-nox-safety",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "gap_companies": len(gap_codes),
        "clue_or_force_companies": len(target_codes),
        "filled_missing": added,
        "replaced": replaced,
        "fills": len(fills),
        "output_observations": str(OUT_OBS.relative_to(ROOT)),
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "中文SO2/NOx三联叙述/繁体表头/短标签括注/目标达成实际排放；不把硫氧化物等同SO2；N家火电仍拒绝；非正式。",
    }
    AUDIT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
