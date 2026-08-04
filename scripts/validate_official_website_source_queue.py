#!/usr/bin/env python3
"""Validate issuer-official source registrations before any download is attempted."""
from __future__ import annotations

import csv
import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/official_website_source_queue_v1_2025.csv"
OUTPUT = ROOT / "output/audit/official_website_source_queue_validation_v1_2025.json"
EXCHANGE_HOSTS = ("sse.com.cn", "szse.cn", "hkex.com.hk", "bse.cn")


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    errors = []
    ready = 0
    for row in rows:
        domain = (row.get("official_domain") or "").strip().lower()
        url = (row.get("candidate_url") or "").strip()
        if not domain and not url:
            continue
        parsed_domain = urllib.parse.urlparse("https://" + domain if domain and "://" not in domain else domain)
        parsed_url = urllib.parse.urlparse(url)
        if not parsed_domain.hostname or any(parsed_domain.hostname == host or parsed_domain.hostname.endswith("." + host) for host in EXCHANGE_HOSTS):
            errors.append({"company_code": row.get("company_code", ""), "error": "official_domain_not_issuer_domain"})
            continue
        if parsed_url.scheme != "https" or not parsed_url.hostname or any(parsed_url.hostname == host or parsed_url.hostname.endswith("." + host) for host in EXCHANGE_HOSTS):
            errors.append({"company_code": row.get("company_code", ""), "error": "candidate_url_must_be_https_and_non_exchange"})
            continue
        if not (parsed_url.hostname == parsed_domain.hostname or parsed_url.hostname.endswith("." + parsed_domain.hostname)):
            errors.append({"company_code": row.get("company_code", ""), "error": "candidate_url_outside_registered_domain"})
            continue
        ready += 1
    result = {"policy_version": "official-website-source-validation-v1", "row_count": len(rows),
              "ready_for_download": ready, "invalid_rows": len(errors), "invalid_examples": errors[:20],
              "download_authorized": False, "scoring_authorized": False,
              "decision": "await_official_domain_registration" if not ready else "ready_for_manual_download_review"}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
