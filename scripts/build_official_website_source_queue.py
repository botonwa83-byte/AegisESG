#!/usr/bin/env python3
"""Create a controlled queue for discovering and downloading issuer-official ESG sources."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/raw/all_markets_document_index.csv"
OUTPUT = ROOT / "output/audit/official_website_source_queue_v1_2025.csv"
SUMMARY = ROOT / "output/audit/official_website_source_queue_v1_2025_summary.json"

FIELDS = ("company_code", "company_name", "report_year", "document_type", "source_channel",
          "official_domain", "candidate_url", "domain_verification", "download_status", "next_action",
          "scoring_authorized")


def main() -> None:
    with INDEX.open(encoding="utf-8-sig", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    companies = {}
    for row in source_rows:
        if row.get("document_type") in {"annual_report", "esg_report"}:
            companies[(row["company_code"], row["report_year"], row["document_type"])] = row["company_name"]
    rows = [{"company_code": code, "company_name": name, "report_year": year, "document_type": kind,
             "source_channel": "issuer_official_website", "official_domain": "", "candidate_url": "",
             "domain_verification": "not_submitted", "download_status": "pending_official_url",
             "next_action": "登记公司官网域名并人工确认域名归属，再发现报告链接",
             "scoring_authorized": "False"}
            for (code, year, kind), name in sorted(companies.items())]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    summary = {"policy_version": "official-website-source-queue-v1", "company_document_tasks": len(rows),
               "company_count": len({row["company_code"] for row in rows}), "pending_official_url": len(rows),
               "downloaded": 0, "scoring_authorized": False,
               "rule": "只有经验证的公司官网域名及HTTPS报告链接可进入下载；搜索引擎结果、交易所链接和第三方镜像不计为官网来源"}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "company_document_tasks": len(rows), "pending_official_url": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
