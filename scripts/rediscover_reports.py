"""对已识别误登记/次优版本的公司重新运行官方发现适配器。

输出仅包含与当前索引登记不同的新文档（或此前缺失的文档），
不修改任何现有清单，供后续 supersede + collect 流程使用。
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from aegis_esg.sources.sse import discover_reports as discover_sse
from aegis_esg.sources.szse import discover_reports as discover_szse

SZSE_CODES = [
    "000819.SZ", "001283.SZ", "002028.SZ", "002441.SZ", "002459.SZ",
    "002576.SZ", "002629.SZ", "002812.SZ", "002851.SZ", "003816.SZ",
    "300274.SZ", "300360.SZ", "300776.SZ", "300870.SZ", "301386.SZ",
    "000922.SZ", "002506.SZ", "002531.SZ", "002706.SZ", "300001.SZ",
    "300207.SZ", "300850.SZ", "300880.SZ", "301325.SZ",
]
SSE_CODES = [
    "600011.SH", "600346.SH", "600438.SH", "601808.SH", "605368.SH",
    "688005.SH", "600167.SH", "600207.SH", "605117.SH", "688032.SH",
    "688339.SH", "688390.SH",
]

REPORT_YEAR = 2025


def load_current_urls() -> dict[tuple[str, str], str]:
    current: dict[tuple[str, str], str] = {}
    with open("data/raw/all_markets_document_index.csv", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if int(row["report_year"]) == REPORT_YEAR:
                current[(row["company_code"], row["document_type"])] = row["source_url"]
    return current


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for path in ("data/manifests/szse_candidates_2025.csv", "data/manifests/sse_all_2025.csv"):
        with open(path, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                names.setdefault(row["company_code"], row["company_name"])
    return names


def main() -> int:
    current = load_current_urls()
    names = load_names()
    out_path = Path("data/manifests/rediscovery_2025.csv")
    log_path = Path("output/audit/rediscovery_2025_log.json")
    rows: list[dict] = []
    log: list[dict] = []
    failures: list[dict] = []
    targets = [(code, "SZSE") for code in SZSE_CODES] + [(code, "SSE") for code in SSE_CODES]
    for index, (code, market) in enumerate(targets):
        try:
            found = discover_szse(code, REPORT_YEAR) if market == "SZSE" else discover_sse(code, REPORT_YEAR)
        except Exception as error:  # noqa: BLE001 - log and continue per company
            failures.append({"company_code": code, "error": str(error)})
            print(f"FAIL {code}: {error}")
            continue
        entry = {"company_code": code, "found": []}
        for item in found:
            key = (code, item.document_type)
            changed = current.get(key) != item.source_url
            entry["found"].append({
                "document_type": item.document_type,
                "title": item.title,
                "published_date": item.published_date,
                "changed": changed,
            })
            if changed:
                rows.append({
                    "company_code": code,
                    "company_name": names.get(code, item.company_name),
                    "report_year": REPORT_YEAR,
                    "document_type": item.document_type,
                    "source_url": item.source_url,
                    "published_date": item.published_date,
                    "title": item.title,
                })
        log.append(entry)
        print(f"ok {code}: " + "; ".join(
            f"{f['document_type']}={'CHANGED' if f['changed'] else 'same'} {f['title'][:40]}"
            for f in entry["found"]
        ))
        if index + 1 < len(targets):
            time.sleep(0.6)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=("company_code", "company_name", "report_year", "document_type", "source_url", "published_date", "title"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps({"companies": log, "failures": failures, "changed_rows": len(rows)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"changed documents: {len(rows)}; failures: {len(failures)}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
