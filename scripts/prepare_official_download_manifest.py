#!/usr/bin/env python3
"""Prepare only domain-validated issuer-website URLs for the PDF collector."""
from __future__ import annotations

import csv
import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/official_website_source_queue_v1_2025.csv"
OUTPUT = ROOT / "output/audit/official_download_manifest_v1_2025.csv"
SUMMARY = ROOT / "output/audit/official_download_manifest_v1_2025_summary.json"
EXCHANGE_HOSTS = ("sse.com.cn", "szse.cn", "hkex.com.hk", "bse.cn")
FIELDS = ("company_code", "company_name", "report_year", "document_type", "source_url", "source_channel")


def is_valid(row: dict[str, str]) -> bool:
    domain = (row.get("official_domain") or "").strip().lower()
    url = (row.get("candidate_url") or "").strip()
    if not domain or not url or row.get("domain_verification") != "verified":
        return False
    domain_url = urllib.parse.urlparse("https://" + domain if "://" not in domain else domain)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not domain_url.hostname or not parsed.hostname:
        return False
    if any(parsed.hostname == host or parsed.hostname.endswith("." + host) for host in EXCHANGE_HOSTS):
        return False
    return parsed.hostname == domain_url.hostname or parsed.hostname.endswith("." + domain_url.hostname)


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ready = [{"company_code": row.get("company_code", ""), "company_name": row.get("company_name", ""),
              "report_year": row.get("report_year", ""), "document_type": row.get("document_type", ""),
              "source_url": row.get("candidate_url", ""), "source_channel": "issuer_official_website"}
             for row in rows if is_valid(row)]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(ready)
    summary = {"policy_version": "official-download-manifest-v1", "input_rows": len(rows), "ready_rows": len(ready),
               "download_started": False, "download_authorized": bool(ready), "scoring_authorized": False,
               "decision": "no_verified_official_urls" if not ready else "ready_for_collector_with_review"}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
