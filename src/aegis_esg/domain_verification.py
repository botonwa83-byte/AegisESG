"""Official-domain verification packet and safe apply gate for issuer websites.

Candidates declared inside issuer reports are not trusted until a human verifies
domain ownership. Verification alone never authorizes PDF download or scoring;
report HTTPS URLs still require a separate discovery step.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .domain_hygiene import is_plausible_issuer_domain, normalize_host

PACKET_VERSION = "official-domain-review-packet-v1"
APPLICATION_VERSION = "official-domain-review-application-v1"

REVIEW_FIELDS = (
    "priority",
    "company_code",
    "company_name",
    "official_domain",
    "candidate_url",
    "https_ready",
    "evidence_count",
    "evidence_file",
    "missing_independent_esg",
    "alt_domain_count",
    "verification_decision",
    "reviewer",
    "reviewed_at",
    "review_note",
)

VERIFY = {"verify", "verified", "确认", "通过"}
REJECT = {"reject", "rejected", "拒绝"}
DEFER = {"defer", "deferred", "暂缓"}
DECISIONS = VERIFY | REJECT | DEFER
REQUIRED_ON_DECIDE = ("verification_decision", "reviewer", "reviewed_at", "review_note")


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: str | Path, rows: list[dict[str, str]], fields: tuple[str, ...]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _https_ready(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = normalize_host(parsed.hostname or "")
    return parsed.scheme == "https" and bool(host) and is_plausible_issuer_domain(host)


def companies_missing_independent_esg(document_index_path: str | Path) -> set[str]:
    by_company: dict[str, set[str]] = defaultdict(set)
    for row in _read_csv(document_index_path):
        code = (row.get("company_code") or "").strip()
        kind = (row.get("document_type") or "").strip()
        if code and kind:
            by_company[code].add(kind)
    return {code for code, kinds in by_company.items() if "esg_report" not in kinds}


def prioritize_domain_candidates(
    candidates: list[dict[str, str]],
    *,
    missing_esg: set[str],
    limit: int | None = 50,
) -> list[dict[str, str]]:
    """Pick one best domain per company, prioritizing ESG gaps and evidence strength."""
    by_company: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        code = (row.get("company_code") or "").strip()
        domain = normalize_host(row.get("official_domain") or "")
        if not code or not is_plausible_issuer_domain(domain):
            continue
        by_company[code].append(row)

    ranked: list[dict[str, str]] = []
    for code, rows in by_company.items():
        scored = sorted(
            rows,
            key=lambda item: (
                1 if _https_ready(item.get("candidate_url", "")) else 0,
                int(item.get("evidence_count") or 0),
                -len(item.get("official_domain") or ""),
            ),
            reverse=True,
        )
        best = scored[0]
        domain = normalize_host(best.get("official_domain") or "")
        missing = code in missing_esg
        ranked.append({
            "company_code": code,
            "company_name": best.get("company_name", ""),
            "official_domain": domain,
            "candidate_url": best.get("candidate_url", ""),
            "https_ready": "true" if _https_ready(best.get("candidate_url", "")) else "false",
            "evidence_count": str(best.get("evidence_count") or 0),
            "evidence_file": best.get("evidence_file", ""),
            "missing_independent_esg": "true" if missing else "false",
            "alt_domain_count": str(max(0, len(scored) - 1)),
            "verification_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "review_note": "",
            "_sort_missing": 1 if missing else 0,
            "_sort_https": 1 if _https_ready(best.get("candidate_url", "")) else 0,
            "_sort_evidence": int(best.get("evidence_count") or 0),
        })

    ranked.sort(
        key=lambda row: (
            row["_sort_missing"],
            row["_sort_https"],
            row["_sort_evidence"],
            row["company_code"],
        ),
        reverse=True,
    )
    if limit is not None:
        ranked = ranked[: max(0, int(limit))]
    for index, row in enumerate(ranked, start=1):
        row["priority"] = str(index)
        for key in ("_sort_missing", "_sort_https", "_sort_evidence"):
            row.pop(key, None)
    return ranked


def write_domain_review_html(path: str | Path, rows: list[dict[str, str]], summary: dict[str, Any]) -> None:
    body = "".join(
        "<tr>"
        f"<td>{html.escape(row['priority'])}</td>"
        f"<td><code>{html.escape(row['company_code'])}</code></td>"
        f"<td>{html.escape(row['company_name'])}</td>"
        f"<td><code>{html.escape(row['official_domain'])}</code></td>"
        f"<td class='note-cell'>{html.escape(row['candidate_url'])}</td>"
        f"<td>{'是' if row['https_ready'] == 'true' else '否'}</td>"
        f"<td>{html.escape(row['evidence_count'])}</td>"
        f"<td>{'缺独立ESG' if row['missing_independent_esg'] == 'true' else '已有ESG'}</td>"
        f"<td>{html.escape(row['alt_domain_count'])}</td>"
        f"<td class='note-cell'>{html.escape(row['evidence_file'])}</td>"
        "</tr>"
        for row in rows
    )
    doc = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>官网域名核验工作包</title>
<style>
body{{font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#f7f9fc;color:#24324a;margin:0}}
main{{max-width:1280px;margin:auto;padding:28px 22px}}
.note{{background:#fff4d8;border:1px solid #efd28d;border-radius:10px;padding:14px;margin:16px 0}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f1}}
th,td{{padding:10px;border-bottom:1px solid #edf0f5;text-align:left;vertical-align:top;white-space:normal;word-break:break-word}}
th{{background:#eef3fa;white-space:nowrap}}
td.note-cell{{min-width:180px;color:#53657b}}
code{{color:#4e79ff}}
</style>
<main>
<h1>公司官网域名核验工作包（P0）</h1>
<p>版本：{html.escape(str(summary.get("packet_version", "")))}　批次条数：{summary.get("row_count", 0)}　
缺独立ESG优先：{summary.get("missing_esg_priority_count", 0)}</p>
<div class="note"><b>使用规则：</b>只核验报告中自披露、且可确认归属发行方的域名。禁止把交易所、巨潮、路演平台、
搜索镜像登记为官网。CSV 中填写 <code>verify / reject / defer</code>、审核人、带时区时间和理由后，再执行
<code>apply-official-domain-review</code>。核验通过只登记域名，不授权 PDF 下载或评分；同域 HTTPS 报告链接仍需另发现。</div>
<table><thead><tr>
<th>优先级</th><th>代码</th><th>企业</th><th>候选域名</th><th>候选URL</th><th>HTTPS</th>
<th>证据数</th><th>ESG缺口</th><th>备选域名</th><th>证据文件</th>
</tr></thead><tbody>{body}</tbody></table>
</main></html>
"""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(doc, encoding="utf-8")


def prepare_official_domain_review_packet(
    candidates_path: str | Path,
    document_index_path: str | Path,
    *,
    csv_path: str | Path,
    html_path: str | Path,
    summary_path: str | Path,
    limit: int = 50,
) -> dict[str, Any]:
    candidates = _read_csv(candidates_path)
    missing_esg = companies_missing_independent_esg(document_index_path)
    rows = prioritize_domain_candidates(candidates, missing_esg=missing_esg, limit=limit)
    _write_csv(csv_path, [{field: row.get(field, "") for field in REVIEW_FIELDS} for row in rows], REVIEW_FIELDS)
    summary = {
        "packet_version": PACKET_VERSION,
        "candidate_rows": len(candidates),
        "candidate_companies": len({row.get("company_code") for row in candidates}),
        "plausible_candidate_companies": len({
            row.get("company_code") for row in candidates
            if is_plausible_issuer_domain(row.get("official_domain") or "")
        }),
        "row_count": len(rows),
        "missing_esg_priority_count": sum(1 for row in rows if row.get("missing_independent_esg") == "true"),
        "https_ready_count": sum(1 for row in rows if row.get("https_ready") == "true"),
        "signed_count": 0,
        "download_authorized": False,
        "scoring_authorized": False,
        "status": "blocked_external_review",
        "csv_path": str(csv_path),
        "html_path": str(html_path),
        "candidates_sha256": _sha256_file(Path(candidates_path)) if Path(candidates_path).is_file() else "",
        "notice": "本工作包只辅助人工核验域名归属；已过滤巨潮/路演/截断域名；不授权官网下载或评分。",
    }
    write_domain_review_html(html_path, rows, summary)
    Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def evaluate_official_domain_review(
    rows: list[dict[str, str]],
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Validate human domain-review signatures.

    When ``allow_partial`` is True, unsigned rows are ignored so a session can
    apply only the decisions already signed. Signed rows still require full
    reviewer / timestamp / note fields; nothing is auto-approved.
    """
    incomplete: list[dict[str, str]] = []
    unsigned: list[str] = []
    invalid: list[dict[str, str]] = []
    verified: list[str] = []
    rejected: list[str] = []
    deferred: list[str] = []
    for row in rows:
        code = row.get("company_code", "")
        decision = (row.get("verification_decision") or "").strip().lower()
        if not decision:
            unsigned.append(code)
            if not allow_partial:
                incomplete.append({"company_code": code, "fields": list(REQUIRED_ON_DECIDE)})
            continue
        if decision not in DECISIONS:
            invalid.append({"company_code": code, "decision": decision})
            continue
        missing_fields = [field for field in REQUIRED_ON_DECIDE if not (row.get(field) or "").strip()]
        if missing_fields:
            incomplete.append({"company_code": code, "fields": missing_fields})
            continue
        note = (row.get("review_note") or "").strip()
        if len(note) < 8:
            incomplete.append({"company_code": code, "fields": ["review_note"]})
            continue
        domain = normalize_host(row.get("official_domain") or "")
        if decision in VERIFY and not is_plausible_issuer_domain(domain):
            invalid.append({"company_code": code, "decision": "verify_requires_issuer_domain"})
            continue
        if decision in VERIFY:
            verified.append(code)
        elif decision in REJECT:
            rejected.append(code)
        else:
            deferred.append(code)

    signed_count = len(verified) + len(rejected) + len(deferred)
    ready = bool(verified) and not invalid and not incomplete and (allow_partial or not unsigned)
    if invalid:
        status = "reject_template"
    elif incomplete:
        status = "blocked_external_review"
    elif not rows or (not signed_count and (unsigned or not allow_partial)):
        status = "blocked_external_review"
    elif verified:
        status = "ready_to_register_verified_domains"
    else:
        status = "no_domains_verified"
    return {
        "policy_version": APPLICATION_VERSION,
        "row_count": len(rows),
        "incomplete_rows": len(incomplete),
        "unsigned_rows": len(unsigned),
        "signed_rows": signed_count,
        "invalid_rows": len(invalid),
        "verified_rows": len(verified),
        "rejected_rows": len(rejected),
        "deferred_rows": len(deferred),
        "incomplete_examples": incomplete[:20],
        "invalid_examples": invalid[:20],
        "verified_company_codes": verified,
        "allow_partial": allow_partial,
        "status": status,
        "queue_updated": False,
        "download_authorized": False,
        "scoring_authorized": False,
        "decision": (
            "apply_verified_domains_to_source_queue"
            if ready
            else ("use_allowed_verification_decision" if invalid else "complete_all_required_review_fields")
        ),
    }


def apply_official_domain_review(
    review_csv_path: str | Path,
    queue_path: str | Path,
    *,
    output_queue_path: str | Path | None = None,
    application_path: str | Path | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Register verified domains onto the official website queue without authorizing downloads."""
    rows = _read_csv(review_csv_path)
    report = evaluate_official_domain_review(rows, allow_partial=allow_partial)
    if report["status"] != "ready_to_register_verified_domains":
        if application_path:
            Path(application_path).parent.mkdir(parents=True, exist_ok=True)
            Path(application_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    verified_domains = {
        (row.get("company_code") or "").strip(): normalize_host(row.get("official_domain") or "")
        for row in rows
        if (row.get("verification_decision") or "").strip().lower() in VERIFY
        and (row.get("reviewer") or "").strip()
        and (row.get("reviewed_at") or "").strip()
        and len((row.get("review_note") or "").strip()) >= 8
        and is_plausible_issuer_domain(row.get("official_domain") or "")
    }
    queue = _read_csv(queue_path)
    if not queue:
        raise ValueError("官网来源队列为空，无法登记已核验域名")
    fields = tuple(queue[0].keys())
    updated = 0
    for row in queue:
        code = (row.get("company_code") or "").strip()
        domain = verified_domains.get(code)
        if not domain:
            continue
        row["official_domain"] = domain
        row["domain_verification"] = "verified"
        row["candidate_url"] = ""
        row["download_status"] = "pending_report_discovery"
        row["next_action"] = "在已核验官网域名下发现HTTPS年报/ESG报告PDF链接"
        row["scoring_authorized"] = "False"
        updated += 1

    target = Path(output_queue_path or queue_path)
    _write_csv(target, queue, fields)
    report["queue_updated"] = True
    report["queue_rows_updated"] = updated
    report["output_queue_path"] = str(target)
    report["download_authorized"] = False
    report["scoring_authorized"] = False
    report["notice"] = "已登记核验域名；仍需同域HTTPS报告链接后才能进入下载清单。"
    if application_path:
        Path(application_path).parent.mkdir(parents=True, exist_ok=True)
        Path(application_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
