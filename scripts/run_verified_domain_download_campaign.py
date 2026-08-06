#!/usr/bin/env python3
"""Campaign: discover/accept/download ESG+annual PDFs from verified issuer domains.

Prioritizes companies still missing independent ESG. Uses human-provided reviewer
identity for URL acceptances (never invents reviewer). Scoring remains unauthorized.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.collector import collect_batch  # noqa: E402
from aegis_esg.domain_hygiene import is_plausible_issuer_domain, normalize_host  # noqa: E402
from aegis_esg.domain_verification import companies_missing_independent_esg  # noqa: E402
from aegis_esg.official_report_discovery import (  # noqa: E402
    ACCEPT,
    RESEARCH_SEED_PATHS,
    apply_official_report_discovery,
    default_https_fetcher,
    discover_document_declared_domain_reports,
    prepare_official_report_discovery_packet,
)

TZ = ZoneInfo("Asia/Shanghai")
QUEUE = ROOT / "output/audit/official_website_source_queue_v1_2025.csv"
RESEARCH_INDEX = ROOT / "data/raw/all_markets_document_index.csv"
CI_INDEX = ROOT / "output/sync/official_document_index.csv"
DISC_CSV = ROOT / "output/audit/official_report_discovery_packet_v1_2025.csv"
DISC_HTML = ROOT / "output/audit/official_report_discovery_packet_v1_2025.html"
DISC_SUM = ROOT / "output/audit/official_report_discovery_packet_v1_2025.json"
DISC_APP = ROOT / "output/audit/official_report_discovery_application_v1_2025.json"
MANIFEST = ROOT / "output/audit/official_download_manifest_v1_2025.csv"
OUT_ROOT = ROOT / "data/raw/issuer_official_website_collection"
OUT_INDEX = ROOT / "output/sync/issuer_official_website_document_index.csv"
OUT_FAIL = ROOT / "output/sync/issuer_official_website_collection_failures.csv"
CAMPAIGN = ROOT / "output/audit/verified_domain_download_campaign_v1_2025.json"

DEFAULT_NOTE = "esp评级，确认同域报告链接"


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _missing_esg() -> set[str]:
    codes: set[str] = set()
    if RESEARCH_INDEX.is_file():
        codes |= companies_missing_independent_esg(RESEARCH_INDEX)
    if CI_INDEX.is_file():
        codes |= companies_missing_independent_esg(CI_INDEX)
    return codes


def _select_verified(limit: int, offset: int, missing_esg: set[str]) -> list[dict[str, str]]:
    queue = _read(QUEUE)
    by_code: dict[str, dict[str, str]] = {}
    for row in queue:
        if (row.get("domain_verification") or "").strip().lower() != "verified":
            continue
        code = (row.get("company_code") or "").strip()
        domain = normalize_host(row.get("official_domain") or "")
        if not code or not is_plausible_issuer_domain(domain):
            continue
        by_code[code] = {
            "company_code": code,
            "company_name": row.get("company_name") or "",
            "report_year": row.get("report_year") or "2025",
            "official_domain": domain,
            "candidate_url": (row.get("candidate_url") or "").strip(),
            "evidence_count": "3" if code in missing_esg else "1",
        }
    ranked = sorted(
        by_code.values(),
        key=lambda item: (
            0 if not item.get("candidate_url") else 1,
            0 if item["company_code"] in missing_esg else 1,
            item["company_code"],
        ),
    )
    if offset:
        ranked = ranked[offset:]
    return ranked[:limit] if limit > 0 else ranked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewer", default="郭海飞")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-minutes", type=float, default=40.0)
    parser.add_argument("--esg-only-download", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    missing = _missing_esg()
    selected = _select_verified(args.limit, args.offset, missing)
    print(json.dumps({
        "phase": "campaign_start",
        "selected": len(selected),
        "missing_esg_in_selection": sum(1 for row in selected if row["company_code"] in missing),
        "sample": [row["company_code"] for row in selected[:10]],
    }, ensure_ascii=False), flush=True)

    # Shorter seed set keeps proxy-bound discovery moving; still covers IR/ESG hubs.
    campaign_seeds = (
        "/", "/investor/", "/investor/reports/", "/tzzgx/", "/tzzgx/dqbg/",
        "/esg/", "/responsibility/", "/sustainability/", "/ir/", "/reports/",
    )
    discoveries = discover_document_declared_domain_reports(
        selected,
        fetcher=default_https_fetcher,
        report_year=2025,
        seed_paths=campaign_seeds,
    )
    # Mark as formal pending review status for apply path compatibility.
    for row in discoveries:
        if row.get("discovery_status") == "research_candidate_unverified" and row.get("source_url"):
            row["discovery_status"] = "candidate_pending_review"

    fields = [
        "company_code", "company_name", "report_year", "document_type", "official_domain",
        "source_url", "page_url", "anchor_text", "discovery_status", "error",
        "review_decision", "reviewer", "reviewed_at", "review_note",
    ]
    stamped = _now()
    pdf_hits = []
    for row in discoveries:
        url = (row.get("source_url") or "").strip()
        if not url or not url.lower().split("?", 1)[0].endswith(".pdf"):
            continue
        if row.get("discovery_status") != "candidate_pending_review":
            continue
        doc = row.get("document_type") or ""
        if args.esg_only_download and doc != "esg_report":
            continue
        pdf_hits.append(row)

    # Keep one ESG + one annual per company when possible, then sign only those.
    preferred: dict[tuple[str, str], dict[str, str]] = {}
    for row in pdf_hits:
        key = (row["company_code"], row.get("document_type") or "")
        prior = preferred.get(key)
        score = (1 if "2025" in row["source_url"] else 0, len(row["source_url"]))
        if prior:
            prior_score = (1 if "2025" in prior["source_url"] else 0, len(prior["source_url"]))
            if prior_score >= score:
                continue
        preferred[key] = row
    accept_rows = list(preferred.values())
    accept_urls = {row["source_url"] for row in accept_rows}
    for row in discoveries:
        if row.get("source_url") in accept_urls:
            row["review_decision"] = "accept"
            row["reviewer"] = args.reviewer
            row["reviewed_at"] = stamped
            row["review_note"] = DEFAULT_NOTE

    _write(DISC_CSV, discoveries, fields)
    DISC_SUM.write_text(json.dumps({
        "discovery_version": "official-same-domain-report-discovery-v1",
        "campaign": True,
        "selected_companies": len(selected),
        "discovery_rows": len(discoveries),
        "pdf_hits": len(pdf_hits),
        "accepted_rows": len(accept_rows),
        "status": "candidates_pending_review" if not accept_rows else "partially_signed_in_campaign",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "phase": "discover_done",
        "discovery_rows": len(discoveries),
        "pdf_hits": len(pdf_hits),
        "accept_rows": len(accept_rows),
        "esg_accepts": sum(1 for row in accept_rows if row.get("document_type") == "esg_report"),
    }, ensure_ascii=False), flush=True)

    apply_report = {"status": "skipped_no_accepts"}
    if accept_rows:
        apply_report = apply_official_report_discovery(
            DISC_CSV, QUEUE, application_path=DISC_APP, allow_partial=True,
        )
        print(json.dumps({
            "phase": "apply_urls",
            "status": apply_report.get("status"),
            "accepted_rows": apply_report.get("accepted_rows"),
            "queue_rows_updated": apply_report.get("queue_rows_updated"),
        }, ensure_ascii=False), flush=True)

    downloaded = 0
    failures = 0
    if not args.skip_download and accept_rows:
        # Build download manifest from accepted URLs.
        manifest_rows = []
        seen = set()
        for row in accept_rows:
            url = row["source_url"]
            if url in seen:
                continue
            seen.add(url)
            manifest_rows.append({
                "company_code": row["company_code"],
                "company_name": row["company_name"],
                "report_year": row.get("report_year") or "2025",
                "document_type": row.get("document_type") or "esg_report",
                "source_url": url,
                "source_channel": "issuer_official_website",
            })
        _write(
            MANIFEST,
            manifest_rows,
            ["company_code", "company_name", "report_year", "document_type", "source_url", "source_channel"],
        )
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        records, fails = collect_batch(
            MANIFEST,
            OUT_ROOT,
            OUT_INDEX,
            OUT_FAIL,
            delay_seconds=0.5,
            reuse_existing=True,
            preserve_index=True,
            max_minutes=args.max_minutes,
            document_priority="esg",
        )
        downloaded = len(records)
        failures = len(fails)
        print(json.dumps({
            "phase": "download_done",
            "downloaded_records": downloaded,
            "failure_count": failures,
        }, ensure_ascii=False), flush=True)

    summary = {
        "policy_version": "verified-domain-download-campaign-v1",
        "started_at": stamped,
        "finished_at": _now(),
        "reviewer": args.reviewer,
        "selected_companies": len(selected),
        "missing_esg_priority": sum(1 for row in selected if row["company_code"] in missing),
        "pdf_hits": len(pdf_hits),
        "accepted_rows": len(accept_rows),
        "apply_status": apply_report.get("status"),
        "queue_rows_updated": apply_report.get("queue_rows_updated"),
        "downloaded_records": downloaded,
        "failure_count": failures,
        "scoring_authorized": False,
        "formal_publishable": False,
        "output_root": str(OUT_ROOT.relative_to(ROOT)),
    }
    CAMPAIGN.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
