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
PRESERVE = ("official_domain", "candidate_url", "domain_verification", "download_status", "next_action")


def _load_previous() -> tuple[dict[tuple[str, str, str], dict[str, str]], dict[str, dict[str, str]]]:
    """Keep verified domains/URLs across queue rebuilds."""
    by_task: dict[tuple[str, str, str], dict[str, str]] = {}
    by_company: dict[str, dict[str, str]] = {}
    if not OUTPUT.is_file():
        return by_task, by_company
    with OUTPUT.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row.get("company_code", ""), row.get("report_year", ""), row.get("document_type", ""))
            by_task[key] = row
            code = row.get("company_code", "")
            if (row.get("domain_verification") or "").strip().lower() == "verified" and row.get("official_domain"):
                by_company[code] = {
                    "official_domain": row.get("official_domain", ""),
                    "domain_verification": "verified",
                }
    return by_task, by_company


def main() -> None:
    with INDEX.open(encoding="utf-8-sig", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    previous_tasks, previous_companies = _load_previous()
    companies = {}
    for row in source_rows:
        if row.get("document_type") in {"annual_report", "esg_report"}:
            companies[(row["company_code"], row["report_year"], row["document_type"])] = row["company_name"]
    rows = []
    for (code, year, kind), name in sorted(companies.items()):
        row = {
            "company_code": code,
            "company_name": name,
            "report_year": year,
            "document_type": kind,
            "source_channel": "issuer_official_website",
            "official_domain": "",
            "candidate_url": "",
            "domain_verification": "not_submitted",
            "download_status": "pending_official_url",
            "next_action": "登记公司官网域名并人工确认域名归属，再发现报告链接",
            "scoring_authorized": "False",
        }
        prior = previous_tasks.get((code, year, kind))
        if prior:
            for field in PRESERVE:
                if (prior.get(field) or "").strip():
                    row[field] = prior[field]
        company_prior = previous_companies.get(code)
        if company_prior and row["domain_verification"] != "verified":
            row["official_domain"] = company_prior["official_domain"]
            row["domain_verification"] = "verified"
            if not row["candidate_url"]:
                row["download_status"] = "pending_report_discovery"
                row["next_action"] = "在已核验官网域名下发现HTTPS年报/ESG报告PDF链接"
        row["scoring_authorized"] = "False"
        rows.append(row)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    verified = sum(1 for row in rows if row["domain_verification"] == "verified")
    ready_url = sum(1 for row in rows if row["domain_verification"] == "verified" and row["candidate_url"])
    summary = {
        "policy_version": "official-website-source-queue-v1",
        "company_document_tasks": len(rows),
        "company_count": len({row["company_code"] for row in rows}),
        "pending_official_url": sum(1 for row in rows if row["domain_verification"] != "verified"),
        "verified_domain_tasks": verified,
        "verified_with_candidate_url": ready_url,
        "downloaded": 0,
        "scoring_authorized": False,
        "rule": "只有经验证的公司官网域名及HTTPS报告链接可进入下载；搜索引擎结果、交易所链接和第三方镜像不计为官网来源；重建队列时保留已核验域名与候选URL",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "company_document_tasks": len(rows),
        "pending_official_url": summary["pending_official_url"],
        "verified_domain_tasks": verified,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
