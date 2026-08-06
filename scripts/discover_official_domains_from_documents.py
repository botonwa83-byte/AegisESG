#!/usr/bin/env python3
"""Extract issuer-website candidates declared inside already collected reports."""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.domain_hygiene import extract_urls, host_from_url, is_plausible_issuer_domain, normalize_host

INDEXES = (
    ROOT / "data/raw/all_markets_document_index.csv",
    ROOT / "output/sync/official_document_index.csv",
)
OUTPUT = ROOT / "output/audit/official_domain_candidates_from_documents_v1_2025.csv"


def _resolve_text(local_path: str) -> Path | None:
    source = ROOT / local_path
    text = source.with_suffix(".txt")
    if text.is_file():
        return text
    alt = ROOT / str(local_path).replace("data/raw/", "data/text/").replace(".pdf", ".txt")
    if alt.is_file():
        return alt
    # CI harvest often nests under data/text/ci_collection/<code>/<year>/...
    if "ci_collection" in local_path:
        nested = ROOT / str(local_path).replace("data/raw/ci_collection/", "data/text/ci_collection/").replace(".pdf", ".txt")
        if nested.is_file():
            return nested
    return None


def main() -> None:
    rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for index in INDEXES:
        if not index.is_file():
            continue
        with index.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                key = (
                    row.get("company_code", ""),
                    row.get("report_year", ""),
                    row.get("document_type", ""),
                    row.get("source_url") or row.get("local_path", ""),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                rows.append(row)
    candidates = defaultdict(list)
    rejected = 0
    for row in rows:
        if row.get("document_type") not in {"annual_report", "esg_report"}:
            continue
        text = _resolve_text(row.get("local_path", ""))
        if text is None:
            continue
        content = text.read_text(encoding="utf-8", errors="ignore")
        for url in extract_urls(content):
            host = host_from_url(url)
            if not is_plausible_issuer_domain(host):
                rejected += 1
                continue
            key = (row.get("company_code", ""), host)
            candidates[key].append((
                row.get("company_name", ""),
                row.get("report_year", ""),
                row.get("document_type", ""),
                url,
                str(text.relative_to(ROOT)),
            ))
    output = []
    for (code, host), evidence in sorted(candidates.items()):
        first = evidence[0]
        output.append({
            "company_code": code,
            "company_name": first[0],
            "official_domain": normalize_host(host),
            "candidate_url": first[3],
            "evidence_file": first[4],
            "evidence_count": len(evidence),
            "verification_status": "candidate_declared_in_issuer_report",
            "next_action": "核验域名归属并发现同域ESG/年报PDF",
        })
    fields = (
        "company_code", "company_name", "official_domain", "candidate_url",
        "evidence_file", "evidence_count", "verification_status", "next_action",
    )
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output)
    print(
        f"{OUTPUT} candidates={len(output)} companies={len({row['company_code'] for row in output})} "
        f"rejected_non_issuer_or_truncated={rejected} indexes_scanned={sum(1 for p in INDEXES if p.is_file())}"
    )


if __name__ == "__main__":
    main()
