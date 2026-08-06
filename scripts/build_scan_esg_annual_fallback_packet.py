#!/usr/bin/env python3
"""Document annual-fallback evidence for scan-like ESG reports (research-only)."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THIN = ROOT / "output/audit/ci_thin_text_exports_v1_2025.csv"
CANDIDATES = ROOT / "output/audit/ci_incremental_candidates_v1_2025.csv"
OUT_CSV = ROOT / "output/audit/scan_esg_annual_fallback_v1_2025.csv"
OUT_JSON = ROOT / "output/audit/scan_esg_annual_fallback_v1_2025.json"
OUT_HTML = ROOT / "output/audit/scan_esg_annual_fallback_v1_2025.html"


def main() -> None:
    thin_rows = []
    if THIN.is_file():
        with THIN.open(encoding="utf-8-sig", newline="") as stream:
            thin_rows = [
                row for row in csv.DictReader(stream)
                if row.get("document_type") == "esg_report"
                and row.get("class") in {"critical_thin", "large_pdf_low_text"}
            ]

    by_company: dict[str, list[dict[str, str]]] = defaultdict(list)
    if CANDIDATES.is_file():
        codes = {row["company_code"] for row in thin_rows}
        with CANDIDATES.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("company_code") in codes:
                    by_company[row["company_code"]].append(row)

    out_rows = []
    for row in thin_rows:
        code = row["company_code"]
        items = by_company.get(code, [])
        source_files = Counter()
        for item in items:
            source = (item.get("source_file") or "").replace("\\", "/")
            if source.endswith("esg_report.pdf") or "/esg_report." in source:
                source_files["esg_report"] += 1
            elif source.endswith("annual_report.pdf") or "/annual_report." in source:
                source_files["annual_report"] += 1
            else:
                source_files["other"] += 1
        indicators = sorted({item.get("indicator_code") or "" for item in items if item.get("indicator_code")})
        out_rows.append({
            "company_code": code,
            "company_name": row.get("company_name", ""),
            "esg_non_ws_chars": row.get("non_ws_chars", ""),
            "annual_text_non_ws": row.get("annual_text_non_ws", ""),
            "annual_fallback_usable": row.get("annual_fallback_usable", ""),
            "ci_candidate_count": str(len(items)),
            "candidates_from_annual": str(source_files.get("annual_report", 0)),
            "candidates_from_esg": str(source_files.get("esg_report", 0)),
            "indicator_count": str(len(indicators)),
            "indicator_codes": "|".join(indicators[:20]),
            "next_action": row.get("next_action", ""),
            "ocr_needed_if_annual_insufficient": (
                "false" if source_files.get("annual_report", 0) > 0 or row.get("annual_fallback_usable") == "true"
                else "true"
            ),
        })

    fields = list(out_rows[0].keys()) if out_rows else [
        "company_code", "company_name", "esg_non_ws_chars", "annual_text_non_ws",
        "annual_fallback_usable", "ci_candidate_count", "candidates_from_annual",
        "candidates_from_esg", "indicator_count", "indicator_codes", "next_action",
        "ocr_needed_if_annual_insufficient",
    ]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)

    with_annual = sum(1 for row in out_rows if int(row["candidates_from_annual"] or 0) > 0)
    summary = {
        "policy_version": "scan-esg-annual-fallback-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scan_esg_rows": len(out_rows),
        "companies_with_annual_candidates": with_annual,
        "companies_without_annual_candidates": len(out_rows) - with_annual,
        "examples": out_rows[:12],
        "output_csv": str(OUT_CSV.relative_to(ROOT)),
        "output_html": str(OUT_HTML.relative_to(ROOT)),
        "scoring_authorized": False,
        "formal_publishable": False,
        "ocr_authorized": False,
        "notice": "扫描件ESG的年报回退观测；有年报候选不等于正式确认；OCR未授权。",
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    body = "\n".join(
        "<tr>"
        f"<td>{r['company_code']}</td><td>{r['company_name']}</td>"
        f"<td>{r['esg_non_ws_chars']}</td><td>{r['annual_text_non_ws']}</td>"
        f"<td>{r['ci_candidate_count']}</td><td>{r['candidates_from_annual']}</td>"
        f"<td>{r['candidates_from_esg']}</td><td>{r['indicator_count']}</td>"
        f"<td>{r['next_action']}</td>"
        "</tr>"
        for r in out_rows
    )
    OUT_HTML.write_text(
        f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>扫描ESG年报回退观测</title>
<style>body{{font:14px/1.5 sans-serif;margin:24px;color:#24324a}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #e8edf5;padding:6px 8px;text-align:left}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;background:#fff3e0;color:#a15c00}}</style></head>
<body>
<h1>扫描ESG · 年报回退观测</h1>
<p class="badge">scoring_authorized=false · ocr_authorized=false</p>
<p>扫描ESG {summary['scan_esg_rows']} 家 · 已有年报候选 {summary['companies_with_annual_candidates']} ·
无年报候选 {summary['companies_without_annual_candidates']}</p>
<p>{summary['notice']}</p>
<table><thead><tr><th>代码</th><th>企业</th><th>ESG字符</th><th>年报字符</th>
<th>候选总数</th><th>来自年报</th><th>来自ESG</th><th>指标数</th><th>建议</th></tr></thead>
<tbody>{body}</tbody></table>
</body></html>
""",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
