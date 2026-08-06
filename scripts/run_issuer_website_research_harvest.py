#!/usr/bin/env python3
"""Research-only harvest of ESG/annual PDFs from document-declared issuer websites.

Policy:
- Uses domains declared inside already-collected reports (not forged verification).
- Never writes domain_verification=verified.
- Downloads into an isolated research tree; scoring remains unauthorized.
- Prefer companies still missing independent ESG reports.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.collector import collect_batch  # noqa: E402
from aegis_esg.domain_hygiene import is_plausible_issuer_domain, normalize_host  # noqa: E402
from aegis_esg.domain_verification import companies_missing_independent_esg  # noqa: E402
from aegis_esg.official_report_discovery import (  # noqa: E402
    RESEARCH_DISCOVERY_VERSION,
    default_https_fetcher,
    discover_document_declared_domain_reports,
    write_discovery_html,
)

CANDIDATES = ROOT / "output/audit/official_domain_candidates_from_documents_v1_2025.csv"
RESEARCH_INDEX = ROOT / "data/raw/all_markets_document_index.csv"
CI_INDEX = ROOT / "output/sync/official_document_index.csv"
OUT_DISC = ROOT / "output/audit/issuer_website_research_discovery_v1_2025.csv"
OUT_HTML = ROOT / "output/audit/issuer_website_research_discovery_v1_2025.html"
OUT_MANIFEST = ROOT / "output/audit/issuer_website_research_download_manifest_v1_2025.csv"
OUT_SUMMARY = ROOT / "output/audit/issuer_website_research_harvest_v1_2025.json"
OUT_ROOT = ROOT / "data/raw/issuer_website_collection"
OUT_INDEX = ROOT / "output/sync/issuer_website_document_index.csv"
OUT_FAIL = ROOT / "output/sync/issuer_website_collection_failures.csv"


def _codes_with_local_esg() -> set[str]:
    codes: set[str] = set()
    for index in (RESEARCH_INDEX, CI_INDEX, OUT_INDEX):
        if not index.is_file():
            continue
        for row in csv.DictReader(index.open(encoding="utf-8-sig")):
            if (row.get("document_type") or "").strip() == "esg_report":
                codes.add((row.get("company_code") or "").strip())
    # Also treat already-downloaded research ESG PDFs as covered.
    if OUT_ROOT.is_dir():
        for path in OUT_ROOT.glob("*/*/esg_report.pdf"):
            codes.add(path.parts[-3])
    return {code for code in codes if code}


def _load_candidates(
    path: Path,
    *,
    min_evidence: int,
    limit: int,
    offset: int,
    missing_esg: set[str],
    skip_codes: set[str],
) -> list[dict[str, str]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    by_company: dict[str, dict[str, str]] = {}
    for row in rows:
        code = (row.get("company_code") or "").strip()
        domain = normalize_host(row.get("official_domain") or "")
        if not code or not is_plausible_issuer_domain(domain):
            continue
        if code in skip_codes:
            continue
        evidence = int(row.get("evidence_count") or 0)
        if evidence < min_evidence:
            continue
        prior = by_company.get(code)
        if prior and int(prior.get("evidence_count") or 0) >= evidence:
            continue
        by_company[code] = row
    ranked = sorted(
        by_company.values(),
        key=lambda item: (
            1 if item.get("company_code") in missing_esg else 0,
            int(item.get("evidence_count") or 0),
            item.get("company_code") or "",
        ),
        reverse=True,
    )
    if offset > 0:
        ranked = ranked[offset:]
    return ranked[:limit] if limit > 0 else ranked


def _prefer_download_rows(pdf_hits: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep one ESG + one annual URL per company; prefer ESG and report-year-tagged links."""
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in pdf_hits:
        code = row["company_code"]
        doc = row.get("document_type") or ""
        if doc not in {"esg_report", "annual_report"}:
            continue
        url = row["source_url"]
        score = (
            1 if "2025" in url or "2025" in (row.get("anchor_text") or "") else 0,
            1 if doc == "esg_report" else 0,
            len(url),
        )
        key = (code, doc)
        prior = by_key.get(key)
        if prior:
            prior_score = (
                1 if "2025" in prior["source_url"] or "2025" in (prior.get("anchor_text") or "") else 0,
                1 if prior.get("document_type") == "esg_report" else 0,
                len(prior["source_url"]),
            )
            if prior_score >= score:
                continue
        by_key[key] = row
    # ESG first for collector priority.
    ordered = sorted(
        by_key.values(),
        key=lambda item: (0 if item.get("document_type") == "esg_report" else 1, item.get("company_code") or ""),
    )
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-evidence", type=int, default=2)
    parser.add_argument("--limit", type=int, default=40, help="Max companies to scan; 0=all eligible")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N ranked eligible companies")
    parser.add_argument("--download", action="store_true", help="Download discovered HTTPS PDFs into research tree")
    parser.add_argument("--report-year", type=int, default=2025)
    parser.add_argument("--max-minutes", type=float, default=25.0)
    parser.add_argument(
        "--include-already-covered",
        action="store_true",
        help="Do not skip companies that already have an ESG PDF in research/CI indexes",
    )
    parser.add_argument("--esg-only-download", action="store_true", help="Download only discovered ESG PDFs")
    args = parser.parse_args()

    if not CANDIDATES.is_file():
        raise SystemExit(f"missing domain candidates: {CANDIDATES}; run discover_official_domains_from_documents.py first")

    missing_esg = set()
    if RESEARCH_INDEX.is_file():
        missing_esg |= companies_missing_independent_esg(RESEARCH_INDEX)
    if CI_INDEX.is_file():
        missing_esg |= companies_missing_independent_esg(CI_INDEX)

    skip_codes = set() if args.include_already_covered else _codes_with_local_esg()
    selected = _load_candidates(
        CANDIDATES,
        min_evidence=args.min_evidence,
        limit=args.limit,
        offset=args.offset,
        missing_esg=missing_esg,
        skip_codes=skip_codes,
    )
    print(
        json.dumps({
            "phase": "scan_start",
            "selected_companies": len(selected),
            "skipped_already_have_esg": len(skip_codes),
            "offset": args.offset,
            "sample": [row.get("company_code") for row in selected[:8]],
        }, ensure_ascii=False),
        flush=True,
    )

    discoveries = discover_document_declared_domain_reports(
        selected,
        fetcher=default_https_fetcher,
        report_year=args.report_year,
    )
    fields = (
        "company_code", "company_name", "report_year", "document_type", "official_domain",
        "source_url", "page_url", "anchor_text", "discovery_status", "error",
        "review_decision", "reviewer", "reviewed_at", "review_note",
    )
    OUT_DISC.parent.mkdir(parents=True, exist_ok=True)
    with OUT_DISC.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(discoveries)

    pdf_hits = [
        row for row in discoveries
        if row.get("source_url")
        and row.get("discovery_status") == "research_candidate_unverified"
        and str(row.get("source_url", "")).lower().split("?", 1)[0].endswith(".pdf")
    ]
    download_rows = _prefer_download_rows(pdf_hits)
    if args.esg_only_download:
        download_rows = [row for row in download_rows if row.get("document_type") == "esg_report"]

    summary = {
        "policy_version": RESEARCH_DISCOVERY_VERSION,
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "selected_companies": len(selected),
        "missing_independent_esg_priority": sum(1 for row in selected if row.get("company_code") in missing_esg),
        "skipped_already_have_esg": len(skip_codes),
        "offset": args.offset,
        "discovery_rows": len(discoveries),
        "pdf_candidate_rows": len(pdf_hits),
        "download_candidate_rows": len(download_rows),
        "fetch_failed_rows": sum(1 for row in discoveries if row.get("discovery_status") == "fetch_failed"),
        "domain_verification": "not_verified_research_only",
        "download_started": False,
        "downloaded_records": 0,
        "failure_count": 0,
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": (
            "报告自披露域名研究扫描；不是域名核验签名。"
            "下载仅入隔离研究目录，不得冒充已核验官网或正式评分数据。"
        ),
    }
    write_discovery_html(OUT_HTML, discoveries, {
        "discovery_version": RESEARCH_DISCOVERY_VERSION,
        "candidate_rows": len(pdf_hits),
        "verified_company_count": 0,
    })
    print(json.dumps({
        "phase": "scan_done",
        "pdf_candidate_rows": len(pdf_hits),
        "download_candidate_rows": len(download_rows),
        "fetch_failed_rows": summary["fetch_failed_rows"],
        "esg_hits": sum(1 for row in download_rows if row.get("document_type") == "esg_report"),
    }, ensure_ascii=False), flush=True)

    if args.download and download_rows:
        with OUT_MANIFEST.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["company_code", "company_name", "report_year", "document_type", "source_url"],
                lineterminator="\n",
            )
            writer.writeheader()
            for row in download_rows:
                writer.writerow({
                    "company_code": row["company_code"],
                    "company_name": row["company_name"],
                    "report_year": row["report_year"],
                    "document_type": row["document_type"],
                    "source_url": row["source_url"],
                })
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        records, failures = collect_batch(
            OUT_MANIFEST,
            OUT_ROOT,
            OUT_INDEX,
            OUT_FAIL,
            delay_seconds=0.6,
            reuse_existing=True,
            preserve_index=True,
            max_minutes=args.max_minutes,
            document_priority="esg",
        )
        summary["download_started"] = True
        summary["downloaded_records"] = len(records)
        summary["failure_count"] = len(failures)
        summary["manifest"] = str(OUT_MANIFEST.relative_to(ROOT))
        summary["index"] = str(OUT_INDEX.relative_to(ROOT))
        summary["output_root"] = str(OUT_ROOT.relative_to(ROOT))

    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
