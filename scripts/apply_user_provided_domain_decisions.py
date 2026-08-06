#!/usr/bin/env python3
"""Apply human-provided domain/URL decisions into signed review CSVs.

Policy:
- Caller MUST supply reviewer identity and per-row decisions.
- System only stamps reviewed_at and writes fields; it never invents verify/accept.
- Default notes may fill empty notes (>=8 chars) only when decision is explicit.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.domain_verification import (  # noqa: E402
    DECISIONS as DOMAIN_DECISIONS,
    REJECT as DOMAIN_REJECT,
    VERIFY as DOMAIN_VERIFY,
    apply_official_domain_review,
)
from aegis_esg.official_report_discovery import (  # noqa: E402
    ACCEPT,
    DECISIONS as URL_DECISIONS,
    DEFER as URL_DEFER,
    REJECT as URL_REJECT,
    apply_official_report_discovery,
    default_https_fetcher,
    prepare_official_report_discovery_packet,
)

TZ = ZoneInfo("Asia/Shanghai")
DOMAIN_REVIEW = ROOT / "data/review/official_domain_review_batch01_2025.csv"
QUEUE = ROOT / "output/audit/official_website_source_queue_v1_2025.csv"
DOMAIN_APP = ROOT / "output/audit/official_domain_review_application_v1_2025.json"
DISC_CSV = ROOT / "output/audit/official_report_discovery_packet_v1_2025.csv"
DISC_HTML = ROOT / "output/audit/official_report_discovery_packet_v1_2025.html"
DISC_SUM = ROOT / "output/audit/official_report_discovery_packet_v1_2025.json"
DISC_APP = ROOT / "output/audit/official_report_discovery_application_v1_2025.json"
INTAKE_TEMPLATE = ROOT / "data/review/official_domain_decision_intake_v1_2025.csv"
AUDIT = ROOT / "output/audit/user_provided_domain_decisions_application_v1.json"

DEFAULT_DOMAIN_NOTES = {
    "verify": "与年报/ESG自披露官网一致，确认归属发行人",
    "reject": "域名归属存疑或非发行人官网，拒绝核验",
    "defer": "证据不足，暂缓核验待补充材料",
}
DEFAULT_URL_NOTES = {
    "accept": "同域HTTPS报告链接已人工确认可入队",
    "reject": "链接非目标年报/ESG或同域不合规，拒绝",
    "defer": "链接待复核，暂缓接受",
}


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _norm_domain_decision(raw: str) -> str:
    value = (raw or "").strip().lower()
    mapping = {
        "v": "verify", "y": "verify", "通过": "verify", "确认": "verify", "核验": "verify",
        "r": "reject", "n": "reject", "拒绝": "reject",
        "d": "defer", "暂缓": "defer",
    }
    value = mapping.get(value, value)
    if value in DOMAIN_VERIFY:
        return "verify"
    if value in DOMAIN_REJECT:
        return "reject"
    if value in {"defer", "deferred", "暂缓"}:
        return "defer"
    if value in DOMAIN_DECISIONS:
        return value
    raise ValueError(f"非法域名决定: {raw!r}（允许 verify/reject/defer）")


def _norm_url_decision(raw: str) -> str:
    value = (raw or "").strip().lower()
    mapping = {
        "a": "accept", "y": "accept", "通过": "accept", "确认": "accept",
        "r": "reject", "n": "reject", "拒绝": "reject",
        "d": "defer", "暂缓": "defer",
    }
    value = mapping.get(value, value)
    if value in ACCEPT:
        return "accept"
    if value in URL_REJECT:
        return "reject"
    if value in URL_DEFER or value in {"defer", "deferred"}:
        return "defer"
    if value in URL_DECISIONS:
        return value
    raise ValueError(f"非法URL决定: {raw!r}（允许 accept/reject/defer）")


def export_intake_template(path: Path = INTAKE_TEMPLATE) -> dict:
    rows = _read_csv(DOMAIN_REVIEW)
    out = []
    for row in rows:
        if (row.get("verification_decision") or "").strip():
            continue
        out.append({
            "company_code": row.get("company_code", ""),
            "company_name": row.get("company_name", ""),
            "official_domain": row.get("official_domain", ""),
            "candidate_url": row.get("candidate_url", ""),
            "missing_independent_esg": row.get("missing_independent_esg", ""),
            "verification_decision": "",
            "review_note": "",
        })
    fields = [
        "company_code", "company_name", "official_domain", "candidate_url",
        "missing_independent_esg", "verification_decision", "review_note",
    ]
    _write_csv(path, out, fields)
    return {"path": str(path), "pending_rows": len(out)}


def apply_domain_decisions(
    decisions_path: Path,
    *,
    reviewer: str,
    default_note: bool,
) -> dict:
    reviewer = reviewer.strip()
    if len(reviewer) < 2:
        raise SystemExit("必须提供真实审核人姓名（--reviewer），系统不会代签。")
    decisions = _read_csv(decisions_path)
    by_code: dict[str, dict[str, str]] = {}
    for row in decisions:
        code = (row.get("company_code") or "").strip()
        raw = (row.get("verification_decision") or "").strip()
        if not code or not raw:
            continue
        by_code[code] = row
    if not by_code:
        raise SystemExit(f"决定文件无有效行（需 company_code + verification_decision）: {decisions_path}")

    rows = _read_csv(DOMAIN_REVIEW)
    fields = list(rows[0].keys())
    stamped_at = _now()
    applied = []
    missing = []
    for code, decision_row in by_code.items():
        targets = [row for row in rows if (row.get("company_code") or "").strip() == code]
        if not targets:
            missing.append(code)
            continue
        decision = _norm_domain_decision(decision_row["verification_decision"])
        note = (decision_row.get("review_note") or "").strip()
        if len(note) < 8:
            if not default_note:
                raise SystemExit(f"{code} 缺少≥8字备注；或加 --allow-default-note")
            note = DEFAULT_DOMAIN_NOTES[decision]
        for row in targets:
            row["verification_decision"] = decision
            row["reviewer"] = reviewer
            row["reviewed_at"] = stamped_at
            row["review_note"] = note
        applied.append({"company_code": code, "decision": decision, "note": note})
    _write_csv(DOMAIN_REVIEW, rows, fields)
    report = apply_official_domain_review(
        DOMAIN_REVIEW, QUEUE, application_path=DOMAIN_APP, allow_partial=True,
    )
    return {
        "reviewer": reviewer,
        "stamped_at": stamped_at,
        "decisions_applied": applied,
        "unknown_company_codes": missing,
        "apply_report": report,
    }


def apply_url_decisions(
    decisions_path: Path,
    *,
    reviewer: str,
    default_note: bool,
) -> dict:
    reviewer = reviewer.strip()
    if len(reviewer) < 2:
        raise SystemExit("必须提供真实审核人姓名（--reviewer）。")
    if not DISC_CSV.is_file():
        raise SystemExit(f"缺少发现包: {DISC_CSV}；请先完成域名核验并 live 发现")
    decisions = _read_csv(decisions_path)
    # key: company_code|document_type|source_url (url optional)
    keyed: list[dict[str, str]] = []
    for row in decisions:
        if not (row.get("review_decision") or "").strip():
            continue
        if not (row.get("company_code") or "").strip():
            continue
        keyed.append(row)
    if not keyed:
        raise SystemExit("URL决定文件无有效行")

    rows = _read_csv(DISC_CSV)
    fields = list(rows[0].keys())
    stamped_at = _now()
    applied = []
    for item in keyed:
        code = item["company_code"].strip()
        doc = (item.get("document_type") or "").strip()
        url = (item.get("source_url") or "").strip()
        decision = _norm_url_decision(item["review_decision"])
        note = (item.get("review_note") or "").strip()
        if len(note) < 8:
            if not default_note:
                raise SystemExit(f"{code} URL缺少≥8字备注；或加 --allow-default-note")
            note = DEFAULT_URL_NOTES[decision]
        matched = False
        for row in rows:
            if (row.get("company_code") or "").strip() != code:
                continue
            if doc and (row.get("document_type") or "").strip() != doc:
                continue
            if url and (row.get("source_url") or "").strip() != url:
                continue
            if not (row.get("source_url") or "").strip():
                continue
            row["review_decision"] = decision
            row["reviewer"] = reviewer
            row["reviewed_at"] = stamped_at
            row["review_note"] = note
            matched = True
            applied.append({
                "company_code": code,
                "document_type": row.get("document_type"),
                "source_url": row.get("source_url"),
                "decision": decision,
            })
        if not matched:
            applied.append({"company_code": code, "decision": decision, "error": "no_matching_discovery_row"})
    _write_csv(DISC_CSV, rows, fields)
    report = apply_official_report_discovery(
        DISC_CSV, QUEUE, application_path=DISC_APP, allow_partial=True,
    )
    return {"reviewer": reviewer, "stamped_at": stamped_at, "decisions_applied": applied, "apply_report": report}


def main() -> None:
    parser = argparse.ArgumentParser(description="把你提供的决定写入签名字段并分批应用（不代签）")
    parser.add_argument("--export-template", action="store_true", help="导出待签域名清单模板")
    parser.add_argument("--decisions", help="你填好的决定CSV（域名或URL）")
    parser.add_argument("--reviewer", default="", help="真实审核人姓名（落签必填）")
    parser.add_argument("--kind", choices=("domain", "url"), default="domain")
    parser.add_argument("--allow-default-note", action="store_true", help="备注为空时用标准备注模板")
    parser.add_argument("--continue-pipeline", action="store_true", help="域名应用后live发现并准备下载清单/研究补采")
    parser.add_argument("--research-limit", type=int, default=60)
    args = parser.parse_args()

    if args.export_template:
        summary = export_intake_template()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if not args.decisions:
        raise SystemExit("请提供 --decisions 文件，或先 --export-template")

    decisions_path = Path(args.decisions)
    if args.kind == "domain":
        result = apply_domain_decisions(
            decisions_path, reviewer=args.reviewer, default_note=args.allow_default_note,
        )
        if args.continue_pipeline and result["apply_report"].get("status") == "ready_to_register_verified_domains":
            discover = prepare_official_report_discovery_packet(
                QUEUE, csv_path=DISC_CSV, html_path=DISC_HTML, summary_path=DISC_SUM,
                fetcher=default_https_fetcher,
            )
            result["live_discover"] = {
                "status": discover.get("status"),
                "verified_company_count": discover.get("verified_company_count"),
                "candidate_rows": discover.get("candidate_rows"),
            }
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_issuer_website_research_harvest.py"),
                    "--limit", str(args.research_limit),
                    "--download",
                ],
                cwd=ROOT,
                check=False,
            )
            result["research_harvest_started"] = True
    else:
        result = apply_url_decisions(
            decisions_path, reviewer=args.reviewer, default_note=args.allow_default_note,
        )
        if args.continue_pipeline and result["apply_report"].get("status") == "ready_to_register_report_urls":
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/prepare_official_download_manifest.py")],
                cwd=ROOT,
                check=False,
            )
            result["download_manifest_prepared"] = True

    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
