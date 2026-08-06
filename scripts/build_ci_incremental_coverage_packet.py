#!/usr/bin/env python3
"""Build a research-only coverage packet from CI incremental indicator candidates.

Never confirms observations and never authorizes scoring/publish.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "output/audit/ci_incremental_candidates_v1_2025.csv"
COVERAGE = ROOT / "output/audit/ci_incremental_candidate_coverage_v1_2025.json"
METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025.json"
OUTPUT_CSV = ROOT / "output/audit/ci_incremental_coverage_packet_v1_2025.csv"
OUTPUT_JSON = ROOT / "output/audit/ci_incremental_coverage_packet_v1_2025.json"
OUTPUT_HTML = ROOT / "output/audit/ci_incremental_coverage_packet_v1_2025.html"
FIELDS = (
    "indicator_code", "candidate_count", "company_count",
    "avg_confidence", "methodology_present", "priority_note",
)


def main() -> None:
    methodology_codes = set()
    if METHODOLOGY.is_file():
        payload = json.loads(METHODOLOGY.read_text(encoding="utf-8"))
        for item in payload.get("indicators", []):
            code = (item.get("code") or "").strip()
            if code:
                methodology_codes.add(code)

    by_indicator: dict[str, list[dict[str, str]]] = defaultdict(list)
    companies = set()
    if CANDIDATES.is_file():
        with CANDIDATES.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                code = (row.get("indicator_code") or "").strip()
                company = (row.get("company_code") or "").strip()
                if not code:
                    continue
                by_indicator[code].append(row)
                if company:
                    companies.add(company)

    coverage_raw = {}
    if COVERAGE.is_file():
        coverage_raw = json.loads(COVERAGE.read_text(encoding="utf-8"))

    rows = []
    for code in sorted(set(by_indicator) | set(coverage_raw) | methodology_codes):
        items = by_indicator.get(code, [])
        confidences = []
        for item in items:
            try:
                confidences.append(float(item.get("confidence") or 0))
            except ValueError:
                pass
        company_count = len({(item.get("company_code") or "").strip() for item in items if item.get("company_code")})
        if not company_count and isinstance(coverage_raw.get(code), dict):
            company_count = int(coverage_raw[code].get("company_count") or 0)
        candidate_count = len(items) or int((coverage_raw.get(code) or {}).get("candidate_count") or 0)
        note = "ok"
        if code in methodology_codes and company_count < 10:
            note = "thin_population"
        if code in methodology_codes and candidate_count == 0:
            note = "no_ci_candidates_yet"
        if code not in methodology_codes:
            note = "not_in_active_methodology"
        rows.append({
            "indicator_code": code,
            "candidate_count": str(candidate_count),
            "company_count": str(company_count),
            "avg_confidence": f"{(sum(confidences) / len(confidences)):.4f}" if confidences else "",
            "methodology_present": "true" if code in methodology_codes else "false",
            "priority_note": note,
        })

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    thin = [row for row in rows if row["priority_note"] == "thin_population"]
    missing = [row for row in rows if row["priority_note"] == "no_ci_candidates_yet"]
    summary = {
        "policy_version": "ci-incremental-coverage-packet-v1",
        "candidate_rows": sum(int(row["candidate_count"]) for row in rows),
        "company_count": len(companies),
        "indicator_with_candidates": sum(1 for row in rows if int(row["candidate_count"]) > 0),
        "methodology_indicator_count": len(methodology_codes),
        "thin_population_count": len(thin),
        "no_ci_candidates_count": len(missing),
        "thin_examples": [row["indicator_code"] for row in thin[:12]],
        "missing_examples": [row["indicator_code"] for row in missing[:12]],
        "scoring_authorized": False,
        "formal_publishable": False,
        "review_required": True,
        "output_csv": str(OUTPUT_CSV.relative_to(ROOT)),
        "output_html": str(OUTPUT_HTML.relative_to(ROOT)),
        "notice": "CI增量候选覆盖包仅用于研究观测；全部pending，不进入正式评分。",
    }
    OUTPUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_HTML.write_text(_html(summary, rows), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def _html(summary: dict, rows: list[dict[str, str]]) -> str:
    body_rows = "\n".join(
        f"<tr><td>{row['indicator_code']}</td><td>{row['candidate_count']}</td>"
        f"<td>{row['company_count']}</td><td>{row['avg_confidence']}</td>"
        f"<td>{row['methodology_present']}</td><td>{row['priority_note']}</td></tr>"
        for row in rows
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CI增量候选覆盖包</title>
<style>body{{font:14px/1.5 sans-serif;margin:24px;color:#24324a}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #e8edf5;padding:6px 8px;text-align:left}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;background:#fff3e0;color:#a15c00}}</style></head>
<body>
<h1>CI增量候选覆盖包</h1>
<p class="badge">scoring_authorized=false · formal_publishable=false · review_required=true</p>
<p>候选 {summary['candidate_rows']} 条 · 覆盖公司 {summary['company_count']} ·
有候选指标 {summary['indicator_with_candidates']} · 薄样本 {summary['thin_population_count']} ·
尚无CI候选 {summary['no_ci_candidates_count']}</p>
<p>{summary['notice']}</p>
<table><thead><tr><th>指标</th><th>候选数</th><th>公司数</th><th>平均置信度</th><th>在方法论</th><th>备注</th></tr></thead>
<tbody>{body_rows}</tbody></table>
</body></html>
"""


if __name__ == "__main__":
    main()
