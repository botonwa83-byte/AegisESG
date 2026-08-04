#!/usr/bin/env python3
"""Extract issuer-website candidates declared inside already collected reports."""
from __future__ import annotations

import csv
import ipaddress
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/raw/all_markets_document_index.csv"
OUTPUT = ROOT / "output/audit/official_domain_candidates_from_documents_v1_2025.csv"
EXCLUDED = {"sse.com.cn", "szse.cn", "hkex.com.hk", "bse.cn", "cninfo.com.cn", "hkexnews.hkex.com.hk"}
URL_RE = re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9.-]+(?:/[A-Za-z0-9_./?%=&+#:@~,-]*)?", re.I)


def main() -> None:
    with INDEX.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    candidates = defaultdict(list)
    for row in rows:
        if row.get("document_type") not in {"annual_report", "esg_report"}:
            continue
        source = ROOT / row.get("local_path", "")
        text = source.with_suffix(".txt")
        if not text.is_file():
            text = ROOT / str(row.get("local_path", "")).replace("data/raw/", "data/text/").replace(".pdf", ".txt")
        if not text.is_file():
            continue
        content = text.read_text(encoding="utf-8", errors="ignore")
        for url in URL_RE.findall(content):
            parsed = urlparse(url.rstrip(".,);]"))
            host = (parsed.hostname or "").lower().removeprefix("www.")
            if not host or host in EXCLUDED or any(host == item or host.endswith("." + item) for item in EXCLUDED):
                continue
            try:
                ipaddress.ip_address(host)
                continue
            except ValueError:
                pass
            if "." not in host or host.endswith((".gov.cn", ".edu.cn")):
                continue
            key = (row.get("company_code", ""), host)
            candidates[key].append((row.get("company_name", ""), row.get("report_year", ""), row.get("document_type", ""), url, str(text.relative_to(ROOT))))
    output = []
    for (code, host), evidence in sorted(candidates.items()):
        first = evidence[0]
        output.append({"company_code": code, "company_name": first[0], "official_domain": host,
                       "candidate_url": first[3], "evidence_file": first[4], "evidence_count": len(evidence),
                       "verification_status": "candidate_declared_in_issuer_report",
                       "next_action": "核验域名归属并发现同域ESG/年报PDF"})
    fields = tuple(output[0]) if output else ("company_code", "company_name", "official_domain", "candidate_url", "evidence_file", "evidence_count", "verification_status", "next_action")
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(output)
    print(f"{OUTPUT} candidates={len(output)} companies={len({row['company_code'] for row in output})}")


if __name__ == "__main__":
    main()
