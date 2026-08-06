#!/usr/bin/env python3
"""Flag CI text exports that are too thin for reliable indicator extraction.

Research-only observability with annual-fallback triage for scan-like ESG PDFs.
Does not enable OCR, relax extractors, or authorize scoring.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "output/sync/official_document_index.csv"
TEXT = ROOT / "data/text/ci_collection"
CANDIDATES = ROOT / "output/audit/ci_incremental_candidates_v1_2025.csv"
OUT_CSV = ROOT / "output/audit/ci_thin_text_exports_v1_2025.csv"
OUT_JSON = ROOT / "output/audit/ci_thin_text_exports_v1_2025.json"
OUT_HTML = ROOT / "output/audit/ci_thin_text_exports_v1_2025.html"
CRITICAL = 500
THIN = 2000
LARGE_LOW = 5000
LARGE_PDF = 5_000_000
ANNUAL_USABLE = 20_000


def classify(non_ws: int, pdf_bytes: int, *, missing: bool, page_markers: int = 0) -> str | None:
    if missing:
        return "missing_text"
    # Large PDF with almost no page markers usually means a truncated/failed export.
    if page_markers <= 2 and pdf_bytes >= 1_000_000 and non_ws < THIN:
        return "truncated_export"
    if non_ws < CRITICAL:
        return "critical_thin"
    if non_ws < THIN:
        return "thin"
    if non_ws < LARGE_LOW and pdf_bytes > LARGE_PDF:
        return "large_pdf_low_text"
    return None


def _text_stats(path: Path) -> tuple[int, int, int]:
    if not path.is_file():
        return 0, 0, 0
    text = path.read_text(encoding="utf-8", errors="replace")
    markers = text.count("=== PAGE ")
    prose = "\n".join(line for line in text.splitlines() if not line.startswith("=== PAGE "))
    non_ws = sum(1 for ch in prose if not ch.isspace())
    return non_ws, markers, path.stat().st_size


def _triage_action(
    *,
    klass: str,
    document_type: str,
    sibling_annual_non_ws: int,
    sibling_esg_non_ws: int,
    candidate_count: int,
) -> str:
    if klass in {"missing_text", "truncated_export"}:
        return "re_extract_text"
    if klass == "thin":
        return "spot_check_extractability"
    if document_type == "esg_report" and sibling_annual_non_ws >= ANNUAL_USABLE:
        if candidate_count > 0:
            return "prefer_annual_embedded_evidence"
        return "extract_from_annual_then_review"
    if document_type == "annual_report" and sibling_esg_non_ws >= ANNUAL_USABLE:
        return "prefer_esg_text_if_available"
    if klass in {"critical_thin", "large_pdf_low_text"}:
        return "await_ocr_authorization"
    return "spot_check_extractability"


def main() -> None:
    if not INDEX.is_file():
        summary = {
            "policy_version": "ci-thin-text-exports-v2",
            "status": "waiting_for_index",
            "flagged_rows": 0,
            "scoring_authorized": False,
            "formal_publishable": False,
            "ocr_authorized": False,
        }
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        return

    candidate_counts: dict[str, int] = defaultdict(int)
    if CANDIDATES.is_file():
        with CANDIDATES.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                code = (row.get("company_code") or "").strip()
                if code:
                    candidate_counts[code] += 1

    flagged: list[dict[str, object]] = []
    for row in csv.DictReader(INDEX.open(encoding="utf-8-sig")):
        year = str(row.get("report_year") or "")
        if year != "2025":
            continue
        code = row["company_code"]
        kind = row["document_type"]
        pdf = Path(row["local_path"])
        if not pdf.is_file():
            pdf = ROOT / pdf
        txt = TEXT / code / year / f"{Path(row['local_path']).stem}.txt"
        pdf_size = pdf.stat().st_size if pdf.is_file() else 0
        annual_non_ws, _, _ = _text_stats(TEXT / code / year / "annual_report.txt")
        esg_non_ws, _, _ = _text_stats(TEXT / code / year / "esg_report.txt")
        cand = candidate_counts.get(code, 0)

        if not txt.is_file():
            klass = "missing_text"
            non_ws = markers = text_bytes = 0
        else:
            non_ws, markers, text_bytes = _text_stats(txt)
            klass = classify(non_ws, pdf_size, missing=False, page_markers=markers)
            if not klass:
                continue

        action = _triage_action(
            klass=klass,
            document_type=kind,
            sibling_annual_non_ws=annual_non_ws,
            sibling_esg_non_ws=esg_non_ws,
            candidate_count=cand,
        )
        flagged.append({
            "company_code": code,
            "company_name": row.get("company_name", ""),
            "report_year": year,
            "document_type": kind,
            "pdf_bytes": pdf_size,
            "text_bytes": text_bytes,
            "page_markers": markers,
            "non_ws_chars": non_ws,
            "bytes_per_page": round((non_ws / markers) if markers else non_ws, 1),
            "class": klass,
            "annual_text_non_ws": annual_non_ws,
            "esg_text_non_ws": esg_non_ws,
            "ci_candidate_count": cand,
            "annual_fallback_usable": "true" if annual_non_ws >= ANNUAL_USABLE else "false",
            "next_action": action,
            "local_pdf": row["local_path"],
            "local_txt": str(txt.relative_to(ROOT)),
            "source_url": row.get("source_url", ""),
        })

    flagged.sort(
        key=lambda r: (
            {
                "missing_text": 0,
                "truncated_export": 1,
                "critical_thin": 2,
                "thin": 3,
                "large_pdf_low_text": 4,
            }.get(str(r["class"]), 9),
            int(r["non_ws_chars"]),
            str(r["company_code"]),
        )
    )
    fields = [
        "company_code", "company_name", "report_year", "document_type",
        "pdf_bytes", "text_bytes", "page_markers", "non_ws_chars", "bytes_per_page",
        "class", "annual_text_non_ws", "esg_text_non_ws", "ci_candidate_count",
        "annual_fallback_usable", "next_action", "local_pdf", "local_txt", "source_url",
    ]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(flagged)

    by_class = dict(Counter(str(r["class"]) for r in flagged))
    by_action = dict(Counter(str(r["next_action"]) for r in flagged))
    scan_with_annual = sum(
        1 for r in flagged
        if r["document_type"] == "esg_report"
        and r["class"] in {"critical_thin", "large_pdf_low_text"}
        and r["annual_fallback_usable"] == "true"
    )
    summary = {
        "policy_version": "ci-thin-text-exports-v2",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_year": 2025,
        "flagged_rows": len(flagged),
        "critical_thin_count": by_class.get("critical_thin", 0),
        "thin_count": by_class.get("thin", 0),
        "missing_text_count": by_class.get("missing_text", 0),
        "truncated_export_count": by_class.get("truncated_export", 0),
        "large_pdf_low_text_count": by_class.get("large_pdf_low_text", 0),
        "scan_esg_with_annual_fallback": scan_with_annual,
        "by_class": by_class,
        "by_next_action": by_action,
        "by_document_type": dict(Counter(str(r["document_type"]) for r in flagged)),
        "thresholds_non_ws_chars": {
            "critical_thin": CRITICAL,
            "thin": THIN,
            "large_pdf_low_text": LARGE_LOW,
            "annual_usable": ANNUAL_USABLE,
        },
        "examples": [
            {
                "company_code": r["company_code"],
                "document_type": r["document_type"],
                "class": r["class"],
                "next_action": r["next_action"],
                "non_ws_chars": r["non_ws_chars"],
                "annual_text_non_ws": r["annual_text_non_ws"],
                "ci_candidate_count": r["ci_candidate_count"],
                "pdf_bytes": r["pdf_bytes"],
            }
            for r in flagged[:12]
        ],
        "output_csv": str(OUT_CSV.relative_to(ROOT)),
        "output_html": str(OUT_HTML.relative_to(ROOT)),
        "scoring_authorized": False,
        "formal_publishable": False,
        "ocr_authorized": False,
        "notice": "薄文本分诊：扫描件ESG可优先看年报嵌入证据；OCR仅规划未授权；不放宽抽取、不授权评分。",
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_HTML.write_text(_html(summary, flagged), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def _html(summary: dict, rows: list[dict[str, object]]) -> str:
    body = "\n".join(
        "<tr>"
        f"<td>{r['company_code']}</td><td>{r['company_name']}</td><td>{r['document_type']}</td>"
        f"<td>{r['class']}</td><td>{r['non_ws_chars']}</td><td>{r['annual_text_non_ws']}</td>"
        f"<td>{r['ci_candidate_count']}</td><td>{r['annual_fallback_usable']}</td>"
        f"<td>{r['next_action']}</td>"
        "</tr>"
        for r in rows
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CI薄文本/扫描件观测包</title>
<style>body{{font:14px/1.5 sans-serif;margin:24px;color:#24324a}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #e8edf5;padding:6px 8px;text-align:left}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;background:#fff3e0;color:#a15c00}}</style></head>
<body>
<h1>CI薄文本/扫描件观测包</h1>
<p class="badge">scoring_authorized=false · ocr_authorized=false · formal_publishable=false</p>
<p>标记 {summary['flagged_rows']} 份 · critical {summary['critical_thin_count']} ·
thin {summary['thin_count']} · truncated {summary['truncated_export_count']} ·
missing {summary['missing_text_count']} · 扫描ESG且年报可回退 {summary['scan_esg_with_annual_fallback']}</p>
<p>{summary['notice']}</p>
<table><thead><tr><th>代码</th><th>企业</th><th>类型</th><th>分级</th>
<th>本文有效字符</th><th>年报有效字符</th><th>CI候选</th><th>年报可回退</th><th>建议动作</th></tr></thead>
<tbody>{body}</tbody></table>
</body></html>
"""


if __name__ == "__main__":
    main()
