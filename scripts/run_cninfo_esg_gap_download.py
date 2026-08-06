#!/usr/bin/env python3
"""Download missing independent ESG PDFs from cninfo for A/B-share gap companies.

Research supplementation only. Does not forge domain verification or authorize scoring.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.sources.cninfo import find_disclosure_pdf  # noqa: E402

RESEARCH = ROOT / "data/raw/all_markets_document_index.csv"
OUT_ROOT = ROOT / "data/raw/cninfo_esg_gap_collection"
OUT_INDEX = ROOT / "output/sync/cninfo_esg_gap_document_index.csv"
SUMMARY = ROOT / "output/audit/cninfo_esg_gap_download_v1_2025.json"
FIELDS = (
    "company_code", "company_name", "report_year", "document_type",
    "source_url", "retrieval_url", "local_path", "sha256", "size",
)


def _existing_esg(year: int) -> set[str]:
    codes = set()
    if RESEARCH.is_file():
        for row in csv.DictReader(RESEARCH.open(encoding="utf-8-sig")):
            if row.get("document_type") == "esg_report" and str(row.get("report_year")) == str(year):
                codes.add(row["company_code"])
    return codes


def _download(url: str, dest: Path) -> tuple[str, int]:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AegisESG/0.2 cninfo-esg-gap"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise ValueError("not a PDF payload")
    dest.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--markets", default="SZ,SH,BJ")
    args = parser.parse_args()
    markets = {item.strip().upper() for item in args.markets.split(",") if item.strip()}

    names = {}
    universe = []
    uni_path = ROOT / "data/universe/energy_historical_candidates_2026.csv"
    if uni_path.is_file():
        for row in csv.DictReader(uni_path.open(encoding="utf-8-sig")):
            if str(row.get("included", "")).lower() not in {"1", "true", "yes"}:
                continue
            code = (row.get("stock_code") or row.get("company_code") or "").strip()
            if code:
                universe.append(code)
                names[code] = row.get("company_name") or ""
    if not universe:
        for row in csv.DictReader((ROOT / "output/audit/official_website_source_queue_v1_2025.csv").open(encoding="utf-8-sig")):
            code = row["company_code"]
            universe.append(code)
            names[code] = row.get("company_name") or ""

    have = _existing_esg(args.year)
    targets = [
        code for code in sorted(set(universe))
        if code not in have and code.split(".")[-1].upper() in markets
    ]
    if args.limit > 0:
        targets = targets[: args.limit]

    print(json.dumps({"phase": "start", "targets": len(targets), "have_esg": len(have)}, ensure_ascii=False), flush=True)
    records = []
    failures = []
    for index, code in enumerate(targets, 1):
        print(f"[cninfo-esg] {index}/{len(targets)} {code}", flush=True)
        try:
            hit = find_disclosure_pdf(code, args.year, "esg_report")
            if not hit:
                failures.append({"company_code": code, "error": "not_found"})
                time.sleep(args.delay)
                continue
            title, url = hit
            dest = OUT_ROOT / code / str(args.year) / "esg_report.pdf"
            sha, size = _download(url, dest)
            row = {
                "company_code": code,
                "company_name": names.get(code, "") or title[:40],
                "report_year": str(args.year),
                "document_type": "esg_report",
                "source_url": url,
                "retrieval_url": url,
                "local_path": str(dest.relative_to(ROOT)),
                "sha256": sha,
                "size": str(size),
            }
            records.append(row)
            # also append into research index immediately
            with RESEARCH.open("a", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
                writer.writerow(row)
            print(json.dumps({"downloaded": code, "bytes": size}, ensure_ascii=False), flush=True)
        except Exception as error:  # noqa: BLE001
            failures.append({"company_code": code, "error": str(error)[:200]})
        time.sleep(args.delay)

    OUT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    with OUT_INDEX.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)

    summary = {
        "policy_version": "cninfo-esg-gap-download-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "targets": len(targets),
        "downloaded": len(records),
        "failures": len(failures),
        "failure_sample": failures[:20],
        "scoring_authorized": False,
        "formal_publishable": False,
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
