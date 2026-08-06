#!/usr/bin/env python3
"""Classify scheduled-collection failures into retryable vs blocked buckets.

Does not download, mutate indexes, or authorize scoring.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILURES = ROOT / "output/sync/official_collection_failures.csv"
OUTPUT = ROOT / "output/audit/collection_failure_classification_v1_2025.csv"
SUMMARY = ROOT / "output/audit/collection_failure_classification_v1_2025.json"
FIELDS = (
    "company_code", "company_name", "report_year", "document_type", "source_url",
    "failure_class", "retryable", "next_action", "error_excerpt",
)


def classify_error(error: str) -> tuple[str, bool, str]:
    text = error or ""
    lower = text.lower()
    partial = re.search(r"已保留(\d+)字节分片", text)
    retained = int(partial.group(1)) if partial else 0
    if "curl退出码28" in text or "operation timed out" in lower:
        if retained > 0 or "out of" in lower:
            return "timeout_partial_resume", True, "resume_with_longer_budget"
        return "timeout_empty", True, "retry_later"
    if "非法报告年份" in text:
        return "invalid_report_year", False, "exclude_until_rediscovery"
    if "eof occurred in violation of protocol" in lower or "_ssl.c" in lower:
        return "ssl_eof", True, "retry_later"
    if "connection reset by peer" in lower or "errno 54" in lower:
        return "connection_reset", True, "retry_later"
    if "remote end closed connection" in lower:
        return "connection_closed", True, "retry_later"
    if "arg1=" in text or ("不是有效pdf" in lower and "<html" in lower):
        return "exchange_antibot_html", True, "retry_with_browser_headers"
    if "公开文档不是有效pdf" in lower:
        return "non_pdf_payload", False, "needs_url_rediscovery"
    if "尺寸异常" in text:
        return "pdf_too_small", False, "needs_url_rediscovery"
    return "other_download_error", True, "retry_later"


def main() -> None:
    rows = []
    if FAILURES.is_file():
        with FAILURES.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                failure_class, retryable, next_action = classify_error(row.get("error", ""))
                rows.append({
                    "company_code": row.get("company_code", ""),
                    "company_name": row.get("company_name", ""),
                    "report_year": row.get("report_year", ""),
                    "document_type": row.get("document_type", ""),
                    "source_url": row.get("source_url", ""),
                    "failure_class": failure_class,
                    "retryable": "true" if retryable else "false",
                    "next_action": next_action,
                    "error_excerpt": (row.get("error") or "")[:180].replace("\n", " "),
                })
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    by_class = Counter(row["failure_class"] for row in rows)
    summary = {
        "policy_version": "collection-failure-classification-v1",
        "failure_rows": len(rows),
        "retryable_rows": sum(1 for row in rows if row["retryable"] == "true"),
        "by_class": dict(by_class),
        "timeout_partial_resume": by_class.get("timeout_partial_resume", 0),
        "scoring_authorized": False,
        "formal_publishable": False,
        "output": str(OUTPUT.relative_to(ROOT)),
        "notice": "仅分类失败原因；不下载、不改索引、不授权评分。",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
