#!/usr/bin/env python3
"""Targeted research fill for water/solid-waste intensity recall (v18 → v41).

Only re-extracts companies that:
1. are missing water or solid intensity (or hold a known page-number FP), AND
2. have text-export clue hits for the new million-revenue / bilingual patterns.

Research-only; does not authorize formal release.
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

METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025_research_sasac.json"
BASE_OBS = ROOT / "output/research/2025/full_auto_observations_v40_enriched.csv"
DOCUMENT_INDEX = ROOT / "data/raw/all_markets_document_index.csv"
CI_INDEX = ROOT / "output/sync/official_document_index.csv"
TEXT_ROOT = ROOT / "data/text"
OUT_OBS = ROOT / "output/research/2025/full_auto_observations_v41_enriched.csv"
AUDIT_JSON = ROOT / "output/audit/authority_gap_fill_v18_2025.json"
AUDIT_CSV = ROOT / "output/audit/authority_gap_fill_v18_2025.csv"
TAG = "[research-only:authority-gap-fill-v18;not-formal]"
TARGET = {"Q_E_WATER_INTENSITY", "Q_E_SOLID_WASTE_INTENSITY"}

# High-signal patterns for the new recall rules (avoid full-universe re-extract).
CLUE = re.compile(
    r"(?:"
    r"用水强度\s*吨\s*[／/╱]\s*百万营收|"
    r"一般废弃物产生强度\s*吨\s*[／/╱]\s*百万营收|"
    r"一般固(?:体)?废(?:物)?(?:产生|排放)?强度\s*吨\s*[／/╱]\s*百万营收|"
    r"吨\s*/\s*百万营收|"
    r"Water\s+consumption\s+intensity|"
    r"耗水密度|"
    r"Non-hazardous\s+waste\s+emission|"
    r"無害廢棄物排放密度|"
    r"tonnes?\s*/\s*RMB\s*10[,，]?000|"
    r"噸\s*[╱/]\s*萬元營收"
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
    return [item for item in candidates if item.indicator_code in TARGET and item.value is not None]


def _best(items: list[Observation]) -> Observation:
    ranked = sorted(
        items,
        key=lambda item: (
            0 if "Chinese current-last environmental table row" in (item.evidence_text or "") else 1,
            0 if "English revenue intensity" in (item.evidence_text or "") else 1,
            -float(item.confidence or 0),
        ),
    )
    winner = ranked[0]
    for item in ranked[1:]:
        winner = prefer(winner, item)
    return winner


def _tag(item: Observation) -> Observation:
    evidence = item.evidence_text or ""
    if TAG not in evidence:
        evidence = f"{evidence} {TAG}".strip()
    return replace(item, evidence_text=evidence, status=ValueStatus.CONFIRMED)


def _quality(item: Observation) -> tuple[int, float]:
    evidence = item.evidence_text or ""
    rank = 3
    if "Chinese current-last environmental table row" in evidence:
        rank = 0
    elif "English revenue intensity" in evidence:
        rank = 0
    elif "Chinese highlight intensity" in evidence:
        rank = 1
    elif "中文跨表派生" in evidence or "English current-year" in evidence:
        rank = 2
    elif re.search(r"(?:吨|立方米)\s*[／/]\s*万?元", evidence) and re.search(
        r"\d+\.\d+", evidence
    ):
        rank = 1
    # Huge DirectRule windows that end near page footers are low quality.
    if len(evidence) > 180 and re.search(r"(?:走进|公司概况|ENVIRONMENTAL)", evidence, re.I):
        rank = 9
    return rank, -float(item.confidence or 0)


def _should_replace(existing: Observation, candidate: Observation) -> bool:
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
                indicator == "Q_E_WATER_INTENSITY"
                and existing.value == 90
                and "用水强度" in evidence
                and "Chinese current-last" not in evidence
            ):
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
            best = _tag(_best(items))
            key = (code, 2025, indicator)
            existing = by_key.get(key)
            if existing is None or existing.value is None:
                by_key[key] = best
                added += 1
                action = "filled_missing"
            elif existing.value is not None and abs(float(best.value) - float(existing.value)) <= max(
                1e-9, abs(float(existing.value)) * 1e-9
            ):
                continue
            elif _should_replace(existing, best):
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
        "policy_version": "authority-gap-fill-v18-targeted-water-solid",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "gap_companies": len(gap_codes),
        "clue_or_force_companies": len(target_codes),
        "target_companies": target_codes,
        "filled_missing": added,
        "replaced": replaced,
        "fills": len(fills),
        "output_observations": str(OUT_OBS.relative_to(ROOT)),
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "仅对有新规则文本线索的用水/固废缺数公司定点召回；非正式。",
    }
    AUDIT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "target_companies"}, ensure_ascii=False))
    print("targets:", ",".join(target_codes))


if __name__ == "__main__":
    main()
