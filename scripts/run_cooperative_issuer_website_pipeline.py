#!/usr/bin/env python3
"""Cooperative human signing for issuer-website domains + auto supplementation.

You sign decisions interactively (verify / reject / defer / accept). The program
never forges reviewer names, timestamps, or domain_verification=verified.
After each session it can apply only signed rows, live-discover same-domain PDF
links, accept those with you, prepare the formal download manifest, and continue
research-only harvest for remaining gaps.
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
    REVIEW_FIELDS,
    apply_official_domain_review,
    evaluate_official_domain_review,
)
from aegis_esg.official_report_discovery import (  # noqa: E402
    apply_official_report_discovery,
    default_https_fetcher,
    evaluate_official_report_discovery,
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
SESSION_LOG = ROOT / "output/audit/cooperative_issuer_website_session_v1.json"

DEFAULT_NOTES = {
    "verify": "与年报/ESG自披露官网一致，确认归属发行人",
    "reject": "域名归属存疑或非发行人官网，拒绝核验",
    "defer": "证据不足，暂缓核验待补充材料",
    "accept": "同域HTTPS报告链接已人工确认可入队",
    "reject_url": "链接非目标年报/ESG或同域不合规，拒绝",
    "defer_url": "链接待复核，暂缓接受",
}


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str] | tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _prompt(text: str) -> str:
    try:
        return input(text).strip()
    except EOFError:
        return "q"


def _ask_reviewer(default: str) -> str:
    while True:
        name = _prompt(f"审核人姓名 [{default or '必填'}]: ") or default
        if name:
            return name
        print("必须填写真实审核人姓名（系统不会代签）。")


def _ask_note(default: str) -> str:
    note = _prompt(f"审核备注（回车用默认，≥8字）:\n  默认: {default}\n> ")
    note = note or default
    while len(note.strip()) < 8:
        note = _prompt("备注太短，请重新输入（≥8字）: ")
    return note.strip()


def review_domains(*, reviewer: str, limit: int, resume: bool) -> dict[str, int]:
    if not DOMAIN_REVIEW.is_file():
        raise SystemExit(f"缺少域名核验批次: {DOMAIN_REVIEW}")
    rows = _read_csv(DOMAIN_REVIEW)
    fields = list(rows[0].keys()) if rows else list(REVIEW_FIELDS)
    pending = [
        row for row in rows
        if not (row.get("verification_decision") or "").strip()
        or (resume and not (row.get("reviewer") or "").strip())
    ]
    if limit > 0:
        pending = pending[:limit]
    print("\n=== 官网域名协作核验 ===")
    print(f"待签 {len(pending)} / 总行 {len(rows)} | 操作: v=通过 r=拒绝 d=暂缓 s=跳过 q=结束并应用\n")
    stats = {"verify": 0, "reject": 0, "defer": 0, "skip": 0}
    for idx, row in enumerate(pending, 1):
        print("-" * 60)
        print(
            f"[{idx}/{len(pending)}] {row.get('company_code')} {row.get('company_name')}\n"
            f"  域名: {row.get('official_domain')}\n"
            f"  URL : {row.get('candidate_url')}\n"
            f"  HTTPS就绪: {row.get('https_ready')} | 证据数: {row.get('evidence_count')} | "
            f"缺独立ESG: {row.get('missing_independent_esg')}\n"
            f"  证据文件: {row.get('evidence_file')}"
        )
        choice = _prompt("决定 [v/r/d/s/q]: ").lower()
        if choice in {"q", "quit", "exit"}:
            break
        if choice in {"s", "skip", ""}:
            stats["skip"] += 1
            continue
        mapping = {
            "v": "verify", "verify": "verify", "y": "verify", "通过": "verify",
            "r": "reject", "reject": "reject", "n": "reject", "拒绝": "reject",
            "d": "defer", "defer": "defer", "暂缓": "defer",
        }
        decision = mapping.get(choice)
        if not decision:
            print("无效输入，已跳过。")
            stats["skip"] += 1
            continue
        note = _ask_note(DEFAULT_NOTES[decision])
        row["verification_decision"] = decision
        row["reviewer"] = reviewer
        row["reviewed_at"] = _now()
        row["review_note"] = note
        stats[decision] += 1
        _write_csv(DOMAIN_REVIEW, rows, fields)
        print(f"  已写入: {decision} @ {row['reviewed_at']}")
    _write_csv(DOMAIN_REVIEW, rows, fields)
    return stats


def apply_domains() -> dict:
    report = apply_official_domain_review(
        DOMAIN_REVIEW,
        QUEUE,
        application_path=DOMAIN_APP,
        allow_partial=True,
    )
    print("\n=== 域名核验应用结果 ===")
    print(json.dumps({
        "status": report.get("status"),
        "verified_rows": report.get("verified_rows"),
        "unsigned_rows": report.get("unsigned_rows"),
        "queue_rows_updated": report.get("queue_rows_updated"),
        "download_authorized": report.get("download_authorized"),
        "notice": report.get("notice"),
    }, ensure_ascii=False, indent=2))
    return report


def live_discover() -> dict:
    print("\n=== 对已核验域名做同域HTTPS报告发现（不下载PDF）===")
    summary = prepare_official_report_discovery_packet(
        QUEUE,
        csv_path=DISC_CSV,
        html_path=DISC_HTML,
        summary_path=DISC_SUM,
        fetcher=default_https_fetcher,
    )
    print(json.dumps({
        "status": summary.get("status"),
        "verified_company_count": summary.get("verified_company_count"),
        "candidate_rows": summary.get("candidate_rows"),
        "fetch_failed_rows": summary.get("fetch_failed_rows"),
        "csv_path": summary.get("csv_path"),
    }, ensure_ascii=False, indent=2))
    return summary


def review_discovery(*, reviewer: str, limit: int) -> dict[str, int]:
    if not DISC_CSV.is_file():
        print("尚无发现包，跳过URL签署。")
        return {"accept": 0, "reject": 0, "defer": 0, "skip": 0}
    rows = _read_csv(DISC_CSV)
    if not rows:
        print("发现包为空。")
        return {"accept": 0, "reject": 0, "defer": 0, "skip": 0}
    fields = list(rows[0].keys())
    pending = [
        row for row in rows
        if (row.get("source_url") or "").strip()
        and not (row.get("review_decision") or "").strip()
    ]
    if limit > 0:
        pending = pending[:limit]
    print("\n=== 同域报告URL协作确认 ===")
    print(f"待签 {len(pending)} | 操作: a=接受 r=拒绝 d=暂缓 s=跳过 q=结束并应用\n")
    stats = {"accept": 0, "reject": 0, "defer": 0, "skip": 0}
    for idx, row in enumerate(pending, 1):
        print("-" * 60)
        print(
            f"[{idx}/{len(pending)}] {row.get('company_code')} {row.get('company_name')}\n"
            f"  类型: {row.get('document_type')} | 年: {row.get('report_year')}\n"
            f"  域名: {row.get('official_domain')}\n"
            f"  URL : {row.get('source_url')}\n"
            f"  页  : {row.get('page_url')}\n"
            f"  锚文本: {row.get('anchor_text')}"
        )
        choice = _prompt("决定 [a/r/d/s/q]: ").lower()
        if choice in {"q", "quit", "exit"}:
            break
        if choice in {"s", "skip", ""}:
            stats["skip"] += 1
            continue
        mapping = {
            "a": "accept", "accept": "accept", "y": "accept", "通过": "accept", "确认": "accept",
            "r": "reject", "reject": "reject", "n": "reject", "拒绝": "reject",
            "d": "defer", "defer": "defer", "暂缓": "defer",
        }
        decision = mapping.get(choice)
        if not decision:
            print("无效输入，已跳过。")
            stats["skip"] += 1
            continue
        note_key = {"accept": "accept", "reject": "reject_url", "defer": "defer_url"}[decision]
        note = _ask_note(DEFAULT_NOTES[note_key])
        row["review_decision"] = decision
        row["reviewer"] = reviewer
        row["reviewed_at"] = _now()
        row["review_note"] = note
        stats[decision] += 1
        _write_csv(DISC_CSV, rows, fields)
        print(f"  已写入: {decision} @ {row['reviewed_at']}")
    _write_csv(DISC_CSV, rows, fields)
    return stats


def apply_discovery() -> dict:
    report = apply_official_report_discovery(
        DISC_CSV,
        QUEUE,
        application_path=DISC_APP,
        allow_partial=True,
    )
    print("\n=== 报告URL应用结果 ===")
    print(json.dumps({
        "status": report.get("status"),
        "accepted_rows": report.get("accepted_rows"),
        "unsigned_rows": report.get("unsigned_rows"),
        "queue_rows_updated": report.get("queue_rows_updated"),
        "download_authorized": report.get("download_authorized"),
    }, ensure_ascii=False, indent=2))
    return report


def prepare_download_manifest() -> dict:
    script = ROOT / "scripts/prepare_official_download_manifest.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, check=False, capture_output=True, text=True)
    print("\n=== 官网下载清单 ===")
    print(result.stdout.strip() or result.stderr.strip())
    summary_path = ROOT / "output/audit/official_download_manifest_v1_2025_summary.json"
    if summary_path.is_file():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return {"ok": result.returncode == 0, "stderr": result.stderr}


def continue_research_harvest(*, limit: int, download: bool) -> dict:
    script = ROOT / "scripts/run_issuer_website_research_harvest.py"
    cmd = [sys.executable, str(script), "--limit", str(limit)]
    if download:
        cmd.append("--download")
    print("\n=== 研究通道自动补采（不伪造域名核验）===")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    summary_path = ROOT / "output/audit/issuer_website_research_harvest_v1_2025.json"
    if summary_path.is_file():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return {"returncode": result.returncode}


def main() -> None:
    parser = argparse.ArgumentParser(description="协作签署官网域名/报告URL，并自动续补")
    parser.add_argument("--reviewer", default="", help="审核人姓名；也可交互输入")
    parser.add_argument("--limit", type=int, default=0, help="本会话最多签署条数；0=全部待签")
    parser.add_argument("--domains-only", action="store_true", help="只做域名核验")
    parser.add_argument("--discovery-only", action="store_true", help="只做已发现URL确认")
    parser.add_argument("--skip-apply", action="store_true", help="只写CSV不应用")
    parser.add_argument("--skip-discover", action="store_true", help="域名应用后不做live发现")
    parser.add_argument("--skip-research", action="store_true", help="结束后不跑研究补采")
    parser.add_argument("--research-limit", type=int, default=60)
    parser.add_argument("--no-research-download", action="store_true", help="研究扫描但不下载PDF")
    parser.add_argument("--apply-only", action="store_true", help="不交互，仅对已签行分批应用并续补")
    args = parser.parse_args()

    if not sys.stdin.isatty() and not args.apply_only:
        raise SystemExit("需要交互终端。无TTY时请用 --apply-only，或在本机终端运行本脚本。")

    session = {
        "started_at": _now(),
        "reviewer": "",
        "domain_stats": {},
        "discovery_stats": {},
        "domain_apply": {},
        "discovery_apply": {},
        "download_manifest": {},
        "research_harvest": {},
    }

    reviewer = args.reviewer
    if not args.apply_only:
        reviewer = _ask_reviewer(reviewer)
    elif not reviewer:
        # apply-only may reuse reviewer already written into CSV rows
        reviewer = "(from-csv)"
    session["reviewer"] = reviewer

    if args.apply_only:
        if not args.discovery_only:
            session["domain_apply"] = apply_domains()
            audit = evaluate_official_domain_review(_read_csv(DOMAIN_REVIEW), allow_partial=True)
            if audit.get("verified_rows") and not args.skip_discover:
                session["live_discover"] = live_discover()
        if not args.domains_only and DISC_CSV.is_file():
            session["discovery_apply"] = apply_discovery()
            session["download_manifest"] = prepare_download_manifest()
    else:
        if not args.discovery_only:
            session["domain_stats"] = review_domains(reviewer=reviewer, limit=args.limit, resume=True)
            if not args.skip_apply:
                session["domain_apply"] = apply_domains()
                if (
                    session["domain_apply"].get("status") == "ready_to_register_verified_domains"
                    and not args.skip_discover
                    and not args.domains_only
                ):
                    session["live_discover"] = live_discover()
        if not args.domains_only:
            if DISC_CSV.is_file():
                session["discovery_stats"] = review_discovery(reviewer=reviewer, limit=args.limit)
                if not args.skip_apply:
                    session["discovery_apply"] = apply_discovery()
                    if session["discovery_apply"].get("status") == "ready_to_register_report_urls":
                        session["download_manifest"] = prepare_download_manifest()

    if not args.skip_research and not args.domains_only and not args.discovery_only:
        # Research harvest does not require formal domain verification.
        go = "y"
        if not args.apply_only and sys.stdin.isatty():
            go = _prompt("是否继续研究通道自动扫描/下载？[Y/n]: ").lower() or "y"
        if go in {"y", "yes", "是"}:
            session["research_harvest"] = continue_research_harvest(
                limit=args.research_limit,
                download=not args.no_research_download,
            )

    session["finished_at"] = _now()
    SESSION_LOG.parent.mkdir(parents=True, exist_ok=True)
    SESSION_LOG.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n会话记录: {SESSION_LOG}")
    print("提醒: 未签署行仍待你下次继续；系统不会代签或伪造 domain_verification。")


if __name__ == "__main__":
    main()
