#!/usr/bin/env python3
"""Fill missing research observations from authoritative public sources.

Policy:
1. Do not leave gaps as a permanent “score 0” without attempting recovery.
2. Source authority: exchange filings > issuer official website > other.
3. On conflicts, keep the higher-authority value.
4. Never forges signatures; research-only; does not authorize formal release.

Current pass recovers from already-downloaded exchange document text exports
(and CI harvest of the same filings). Issuer-website downloads remain gated on
verified domains and are queued when verification is missing.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.extraction import (  # noqa: E402
    extract_indicator_candidates,
    read_page_text_export,
    resolve_text_export_path,
)
from aegis_esg.env_intensity import (  # noqa: E402
    CompanyDocument,
    derive_env_intensity_candidates,
    derive_ghg_reduction_candidates,
)
from aegis_esg.io import read_observations, write_observations  # noqa: E402
from aegis_esg.methodology import load_methodology  # noqa: E402
from aegis_esg.models import Observation, ValueStatus  # noqa: E402
from aegis_esg.social_invest import derive_social_invest_candidates  # noqa: E402
from aegis_esg.source_authority import (  # noqa: E402
    AUTHORITY_POLICY_VERSION,
    SourceTier,
    disclosure_authority,
    prefer,
    source_tier,
)

METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025_research_sasac.json"
BASE_OBS = ROOT / "output/research/2025/full_auto_observations_v33_enriched.csv"
DOCUMENT_INDEX = ROOT / "data/raw/all_markets_document_index.csv"
CI_INDEX = ROOT / "output/sync/official_document_index.csv"
TEXT_ROOT = ROOT / "data/text"
CLIENT_TOP200 = ROOT / "data/reference/2025_top200_securities_ocr.csv"
DOMAIN_REVIEW = ROOT / "data/review/official_domain_review_batch01_2025.csv"
OUT_OBS = ROOT / "output/research/2025/full_auto_observations_v34_enriched.csv"
AUDIT_JSON = ROOT / "output/audit/authority_gap_fill_v11_2025.json"
AUDIT_CSV = ROOT / "output/audit/authority_gap_fill_v11_2025.csv"
ISSUER_QUEUE = ROOT / "output/audit/issuer_website_gap_queue_v11_2025.csv"
TAG = "[research-only:authority-gap-fill-v11;not-formal]"
FALSE_ZERO_MARKER = "No qualifying public evidence in current collection"


def _load_priority_companies() -> set[str]:
    """Default: all companies already in the research observation pool.

    Client Top200 / Changjiang are always included; the pass is not limited to
    them because undisclosed items must be recovered universe-wide.
    """
    codes: set[str] = set()
    if BASE_OBS.is_file():
        for row in csv.DictReader(BASE_OBS.open(encoding="utf-8-sig")):
            code = (row.get("company_code") or "").strip()
            if code:
                codes.add(code)
    if CLIENT_TOP200.is_file():
        for row in csv.DictReader(CLIENT_TOP200.open(encoding="utf-8-sig")):
            code = (row.get("current_stock_code") or row.get("stock_code") or "").strip()
            if code:
                codes.add(code)
    codes.add("600900.SH")
    return codes


def _strip_false_qualitative_zeros(rows: list[Observation]) -> tuple[list[Observation], int]:
    kept: list[Observation] = []
    removed = 0
    for item in rows:
        evidence = item.evidence_text or ""
        if (
            item.indicator_code.startswith("X_")
            and item.value == 0
            and FALSE_ZERO_MARKER in evidence
        ):
            removed += 1
            continue
        kept.append(item)
    return kept, removed


def _strip_non_revenue_intensities(rows: list[Observation]) -> tuple[list[Observation], int]:
    """Drop intensity rows whose evidence is output/production-value denominators."""
    kept: list[Observation] = []
    removed = 0
    bad = ("产值", "产量", "发电量", "单位产品", "万元产值")
    intensity = {
        "Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY",
        "Q_E_NOX_INTENSITY", "Q_E_SO2_INTENSITY", "Q_E_SOLID_WASTE_INTENSITY",
    }
    for item in rows:
        evidence = item.evidence_text or ""
        if item.indicator_code in intensity and any(token in evidence for token in bad):
            removed += 1
            continue
        kept.append(item)
    return kept, removed


def _iter_index_rows(company_codes: set[str], report_year: int) -> list[dict]:
    rows: list[dict] = []
    seen_paths: set[str] = set()
    for path in (DOCUMENT_INDEX, CI_INDEX):
        if not path.is_file():
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("company_code") not in company_codes:
                    continue
                if int(row.get("report_year") or 0) != report_year:
                    continue
                local = (row.get("local_path") or row.get("source_file") or "").strip()
                key = f"{row.get('company_code')}|{row.get('document_type')}|{local}"
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                rows.append(row)
    return rows


def _extract_for_companies(
    company_codes: set[str],
    report_year: int,
) -> list[Observation]:
    index_rows = _iter_index_rows(company_codes, report_year)
    if not index_rows:
        return []
    by_company: dict[str, list[tuple[dict, list]]] = defaultdict(list)
    for row in index_rows:
        text_path = resolve_text_export_path(TEXT_ROOT, row)
        if text_path is None:
            continue
        pages = read_page_text_export(text_path)
        by_company[row["company_code"]].append((row, pages))

    candidates: list[Observation] = []
    for code, documents in sorted(by_company.items()):
        company_candidates: list[Observation] = []
        company_documents: list[CompanyDocument] = []
        name = documents[0][0].get("company_name") or code
        for row, pages in documents:
            items = extract_indicator_candidates(
                pages, code, name, report_year, row.get("source_url") or "", row.get("local_path") or "",
            )
            company_candidates.extend(items)
            company_documents.append(CompanyDocument(
                row.get("document_type") or "annual_report",
                pages,
                row.get("source_url") or "",
                row.get("local_path") or "",
            ))
        have = frozenset(item.indicator_code for item in company_candidates)
        company_candidates.extend(
            derive_env_intensity_candidates(code, name, report_year, company_documents, have)
        )
        have = frozenset(item.indicator_code for item in company_candidates)
        company_candidates.extend(
            derive_social_invest_candidates(code, name, report_year, company_documents, have)
        )
        have = frozenset(item.indicator_code for item in company_candidates)
        company_candidates.extend(
            derive_ghg_reduction_candidates(code, name, report_year, company_documents, have)
        )
        candidates.extend(company_candidates)
    return candidates


def _best_candidate(items: list[Observation]) -> Observation:
    winner = items[0]
    for item in items[1:]:
        winner = prefer(winner, item)
    return winner


def _tag(item: Observation) -> Observation:
    evidence = item.evidence_text or ""
    if TAG not in evidence:
        evidence = f"{evidence} {TAG}".strip()
    return replace(item, evidence_text=evidence, status=ValueStatus.CONFIRMED)


def _issuer_queue(missing_pairs: list[tuple[str, str]], company_names: dict[str, str]) -> list[dict]:
    verified: dict[str, str] = {}
    if DOMAIN_REVIEW.is_file():
        for row in csv.DictReader(DOMAIN_REVIEW.open(encoding="utf-8-sig")):
            status = (row.get("verification_status") or row.get("domain_verification") or "").lower()
            domain = (row.get("official_domain") or "").strip()
            code = (row.get("company_code") or "").strip()
            if code and domain and status in {"verified", "approved"}:
                verified[code] = domain
    rows = []
    for code, indicator in sorted(set(missing_pairs)):
        rows.append({
            "company_code": code,
            "company_name": company_names.get(code, ""),
            "indicator_code": indicator,
            "official_domain": verified.get(code, ""),
            "domain_status": "verified" if code in verified else "pending_verification",
            "next_action": (
                "discover_same_domain_pdf_then_download"
                if code in verified else
                "verify_issuer_domain_then_discover_reports"
            ),
            "authority_policy": AUTHORITY_POLICY_VERSION,
        })
    return rows


def main() -> None:
    methodology = load_methodology(METHODOLOGY if METHODOLOGY.is_file() else ROOT / "data/methodologies/energy_esg_2025.json")
    base = read_observations(BASE_OBS, methodology)
    base, removed_false_zeros = _strip_false_qualitative_zeros(base)
    base, removed_non_revenue = _strip_non_revenue_intensities(base)
    priority = _load_priority_companies()
    report_year = 2025

    by_key = {(o.company_code, o.report_year, o.indicator_code): o for o in base}
    company_names = {o.company_code: o.company_name for o in base}
    present = {
        (o.company_code, o.indicator_code)
        for o in base
        if o.report_year == report_year and o.value is not None and o.status == ValueStatus.CONFIRMED
    }

    quant_codes = [i.code for i in methodology.quantitative]
    missing_pairs: list[tuple[str, str]] = []
    for code in sorted(priority):
        for indicator in quant_codes:
            if (code, indicator) not in present:
                missing_pairs.append((code, indicator))

    # Re-extract all priority companies so wrong-year English intensities can be
    # upgraded by Chinese year-column / unit-revenue table rows, not only gaps.
    extract_codes = set(priority)
    raw_candidates = _extract_for_companies(extract_codes, report_year)

    # Keep only candidates that fill a current gap or beat existing on authority.
    grouped: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    for item in raw_candidates:
        if item.value is None:
            continue
        grouped[(item.company_code, item.report_year, item.indicator_code)].append(item)

    fills: list[dict] = []
    added = replaced = skipped_weaker = 0
    for key, items in sorted(grouped.items()):
        best = _tag(_best_candidate(items))
        code, year, indicator = key
        if (code, indicator) not in {(c, i) for c, i in missing_pairs} and key in by_key:
            # Only overwrite existing when new source is strictly more authoritative.
            existing = by_key[key]
            if disclosure_authority(best) < disclosure_authority(existing) and best.value != existing.value:
                by_key[key] = best
                replaced += 1
                fills.append({
                    "company_code": code,
                    "indicator_code": indicator,
                    "action": "replaced_higher_authority",
                    "value": best.value,
                    "prior_value": existing.value,
                    "tier": source_tier(best).name,
                    "source_url": best.source_url,
                    "source_file": best.source_file,
                })
            else:
                skipped_weaker += 1
            continue
        if (code, indicator) not in {(c, i) for c, i in missing_pairs}:
            continue
        existing = by_key.get(key)
        if existing is None or existing.value is None:
            by_key[key] = best
            added += 1
            fills.append({
                "company_code": code,
                "indicator_code": indicator,
                "action": "filled_missing",
                "value": best.value,
                "prior_value": "",
                "tier": source_tier(best).name,
                "source_url": best.source_url,
                "source_file": best.source_file,
            })
        elif best.value != existing.value and disclosure_authority(best) <= disclosure_authority(existing):
            by_key[key] = best
            replaced += 1
            fills.append({
                "company_code": code,
                "indicator_code": indicator,
                "action": "replaced_conflict",
                "value": best.value,
                "prior_value": existing.value,
                "tier": source_tier(best).name,
                "source_url": best.source_url,
                "source_file": best.source_file,
            })

    # Prefer revenue-denominator derived intensities over bare “*/万元” extracts that
    # often come from output-value tables without an explicit 营收 anchor.
    for key, items in grouped.items():
        code, year, indicator = key
        if indicator not in {
            "Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY",
            "Q_E_NOX_INTENSITY", "Q_E_SO2_INTENSITY", "Q_E_SOLID_WASTE_INTENSITY",
        }:
            continue
        existing = by_key.get(key)
        if existing is None or existing.value is None:
            continue
        derived = [
            item for item in items
            if "跨表派生" in (item.evidence_text or "")
            or "cross-document derived" in (item.evidence_text or "")
        ]
        if not derived:
            continue
        existing_ev = existing.evidence_text or ""
        if "营业收入" in existing_ev or "营收" in existing_ev or "Revenue" in existing_ev:
            continue
        if "跨表派生" in existing_ev or "cross-document derived" in existing_ev:
            continue
        best = _tag(_best_candidate(derived))
        if best.value == existing.value:
            continue
        by_key[key] = best
        replaced += 1
        fills.append({
            "company_code": code,
            "indicator_code": indicator,
            "action": "replaced_derived_over_bare_intensity",
            "value": best.value,
            "prior_value": existing.value,
            "tier": source_tier(best).name,
            "source_url": best.source_url,
            "source_file": best.source_file,
        })

    rows = [by_key[k] for k in sorted(by_key)]
    OUT_OBS.parent.mkdir(parents=True, exist_ok=True)
    write_observations(OUT_OBS, rows)

    # Still-missing after fill → issuer website queue (not scored as permanent zero).
    present_after = {
        (o.company_code, o.indicator_code)
        for o in rows
        if o.report_year == report_year and o.value is not None and o.status == ValueStatus.CONFIRMED
    }
    still_missing = [(c, i) for c, i in missing_pairs if (c, i) not in present_after]
    issuer_rows = _issuer_queue(still_missing, company_names)
    ISSUER_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with ISSUER_QUEUE.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = [
            "company_code", "company_name", "indicator_code", "official_domain",
            "domain_status", "next_action", "authority_policy",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(issuer_rows)

    with AUDIT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = [
            "company_code", "indicator_code", "action", "value", "prior_value",
            "tier", "source_url", "source_file",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(fills)

    summary = {
        "policy_version": AUTHORITY_POLICY_VERSION,
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "authority_order": [tier.name for tier in SourceTier],
        "base_observations": str(BASE_OBS.relative_to(ROOT)),
        "output_observations": str(OUT_OBS.relative_to(ROOT)),
        "priority_companies": len(priority),
        "priority_missing_quant_pairs_before": len(missing_pairs),
        "removed_false_qualitative_zeros": removed_false_zeros,
        "removed_non_revenue_intensities": removed_non_revenue,
        "reextracted_candidate_rows": len(raw_candidates),
        "filled_missing": added,
        "replaced_by_higher_authority": replaced,
        "skipped_weaker_or_equal": skipped_weaker,
        "still_missing_after_exchange_pass": len(still_missing),
        "issuer_website_queue": str(ISSUER_QUEUE.relative_to(ROOT)),
        "fill_audit_csv": str(AUDIT_CSV.relative_to(ROOT)),
        "changjiang_fills": [row for row in fills if row["company_code"] == "600900.SH"],
        "scoring_authorized_formal": False,
        "notice": (
            "未披露项先从交易所已下载披露补齐；冲突按交易所>官网>其他。"
            "仍缺项进入官网域名核验/发现队列，不再用“无证据假0”占位。"
        ),
    }
    AUDIT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": summary["output_observations"],
        "filled_missing": added,
        "replaced": replaced,
        "removed_false_qual_zeros": removed_false_zeros,
        "still_missing": len(still_missing),
        "changjiang_fills": len(summary["changjiang_fills"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
