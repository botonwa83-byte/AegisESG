"""Discover same-domain HTTPS annual/ESG PDF candidates on verified issuer websites.

Discovery never downloads PDFs and never authorizes scoring. Only domains with
`domain_verification=verified` are scanned; resulting URLs stay pending human
review before entering the official download manifest.
"""
from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from .domain_hygiene import is_plausible_issuer_domain, normalize_host, same_registered_domain

DISCOVERY_VERSION = "official-same-domain-report-discovery-v1"
HrefFetcher = Callable[[str], str]

ANNUAL_TERMS = ("年度报告", "年报", "annual report", "annualreport")
ESG_TERMS = (
    "社会责任报告", "可持续发展报告", "环境社会及管治报告", "esg报告", "esg report",
    "sustainability report", "sustainability-report", "social responsibility",
    "环境、社会及管治",
)
HREF_RE = re.compile(
    r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.I | re.S,
)


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


def classify_report_link(url: str, anchor_text: str, report_year: int) -> str | None:
    blob = f"{url} {anchor_text}".lower()
    year = str(report_year)
    if year not in blob and str(report_year - 1) not in blob:
        # Accept links that only say annual/ESG without year when path ends with .pdf.
        if not url.lower().endswith(".pdf"):
            return None
    if any(term in blob for term in ESG_TERMS):
        return "esg_report"
    if any(term in blob for term in ANNUAL_TERMS):
        return "annual_report"
    if url.lower().endswith(".pdf") and year in blob:
        if "esg" in blob or "sustainab" in blob or "责任" in anchor_text or "可持续" in anchor_text:
            return "esg_report"
        if "年报" in anchor_text or "年度报告" in anchor_text or "annual" in blob:
            return "annual_report"
    return None


def extract_same_domain_pdf_candidates(
    page_url: str,
    page_html: str,
    *,
    official_domain: str,
    report_year: int,
) -> list[dict[str, str]]:
    domain = normalize_host(official_domain)
    if not is_plausible_issuer_domain(domain):
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in HREF_RE.finditer(page_html or ""):
        href = match.group(1).strip()
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme != "https":
            continue
        host = normalize_host(parsed.hostname or "")
        if not same_registered_domain(host, domain):
            continue
        anchor = re.sub(r"<[^>]+>", " ", match.group(2) or "")
        anchor = re.sub(r"\s+", " ", anchor).strip()[:120]
        kind = classify_report_link(absolute, anchor, report_year)
        if not kind:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append({
            "source_url": absolute,
            "document_type": kind,
            "anchor_text": anchor,
            "page_url": page_url,
        })
    return found


def discover_verified_domain_reports(
    queue_rows: list[dict[str, str]],
    *,
    fetcher: HrefFetcher,
    seed_paths: tuple[str, ...] = ("/", "/investor/", "/investor/reports/", "/responsibility/", "/esg/"),
) -> list[dict[str, str]]:
    """Scan verified issuer domains for HTTPS report PDF candidates."""
    by_company: dict[str, dict[str, str]] = {}
    for row in queue_rows:
        if (row.get("domain_verification") or "").strip().lower() != "verified":
            continue
        code = (row.get("company_code") or "").strip()
        domain = normalize_host(row.get("official_domain") or "")
        if not code or not is_plausible_issuer_domain(domain):
            continue
        by_company[code] = {
            "company_code": code,
            "company_name": row.get("company_name", ""),
            "report_year": row.get("report_year", ""),
            "official_domain": domain,
        }

    discoveries: list[dict[str, str]] = []
    for company in by_company.values():
        domain = company["official_domain"]
        year = int(company["report_year"] or 0)
        seen_urls: set[str] = set()
        for path in seed_paths:
            page_url = f"https://{domain}{path}"
            try:
                page_html = fetcher(page_url)
            except Exception as error:  # noqa: BLE001 - keep discovery resilient
                discoveries.append({
                    "company_code": company["company_code"],
                    "company_name": company["company_name"],
                    "report_year": company["report_year"],
                    "document_type": "",
                    "official_domain": domain,
                    "source_url": "",
                    "page_url": page_url,
                    "anchor_text": "",
                    "discovery_status": "fetch_failed",
                    "error": str(error)[:200],
                    "review_decision": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "review_note": "",
                })
                continue
            hits = extract_same_domain_pdf_candidates(
                page_url, page_html, official_domain=domain, report_year=year,
            )
            for hit in hits:
                if hit["source_url"] in seen_urls:
                    continue
                seen_urls.add(hit["source_url"])
                discoveries.append({
                    "company_code": company["company_code"],
                    "company_name": company["company_name"],
                    "report_year": company["report_year"],
                    "document_type": hit["document_type"],
                    "official_domain": domain,
                    "source_url": hit["source_url"],
                    "page_url": hit["page_url"],
                    "anchor_text": hit["anchor_text"],
                    "discovery_status": "candidate_pending_review",
                    "error": "",
                    "review_decision": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "review_note": "",
                })
    return discoveries


DISCOVERY_FIELDS = (
    "company_code", "company_name", "report_year", "document_type", "official_domain",
    "source_url", "page_url", "anchor_text", "discovery_status", "error",
    "review_decision", "reviewer", "reviewed_at", "review_note",
)


def write_discovery_html(path: str | Path, rows: list[dict[str, str]], summary: dict[str, Any]) -> None:
    body = "".join(
        "<tr>"
        f"<td><code>{html.escape(row.get('company_code', ''))}</code></td>"
        f"<td>{html.escape(row.get('company_name', ''))}</td>"
        f"<td>{html.escape(row.get('document_type', ''))}</td>"
        f"<td><code>{html.escape(row.get('official_domain', ''))}</code></td>"
        f"<td class='note-cell'>{html.escape(row.get('source_url', ''))}</td>"
        f"<td>{html.escape(row.get('discovery_status', ''))}</td>"
        "</tr>"
        for row in rows[:200]
    )
    doc = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>同域HTTPS报告发现候选</title>
<style>
body{{font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#f7f9fc;color:#24324a;margin:0}}
main{{max-width:1200px;margin:auto;padding:28px 22px}}
.note{{background:#fff4d8;border:1px solid #efd28d;border-radius:10px;padding:14px;margin:16px 0}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f1}}
th,td{{padding:10px;border-bottom:1px solid #edf0f5;text-align:left;vertical-align:top;word-break:break-word}}
th{{background:#eef3fa}}
</style>
<main>
<h1>同域 HTTPS 报告发现候选</h1>
<p>版本：{html.escape(str(summary.get('discovery_version', '')))}　候选 {summary.get('candidate_rows', 0)}　
已核验公司 {summary.get('verified_company_count', 0)}</p>
<div class="note">仅扫描 <code>domain_verification=verified</code> 的官网域名。发现结果需人工审核后才能写入下载清单；
当前 <b>不授权下载/评分</b>。</div>
<table><thead><tr><th>代码</th><th>企业</th><th>类型</th><th>域名</th><th>候选URL</th><th>状态</th></tr></thead>
<tbody>{body or '<tr><td colspan="6">暂无已核验域名可扫描</td></tr>'}</tbody></table>
</main></html>
"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(doc, encoding="utf-8")


def prepare_official_report_discovery_packet(
    queue_path: str | Path,
    *,
    csv_path: str | Path,
    html_path: str | Path,
    summary_path: str | Path,
    fetcher: HrefFetcher | None = None,
) -> dict[str, Any]:
    queue = _read_csv(queue_path)
    verified = [
        row for row in queue
        if (row.get("domain_verification") or "").strip().lower() == "verified"
        and is_plausible_issuer_domain(row.get("official_domain") or "")
    ]
    discoveries: list[dict[str, str]] = []
    if fetcher is not None and verified:
        discoveries = discover_verified_domain_reports(verified, fetcher=fetcher)
    _write_csv(csv_path, discoveries, DISCOVERY_FIELDS)
    summary = {
        "discovery_version": DISCOVERY_VERSION,
        "queue_rows": len(queue),
        "verified_company_count": len({row.get("company_code") for row in verified}),
        "candidate_rows": sum(1 for row in discoveries if row.get("source_url")),
        "fetch_failed_rows": sum(1 for row in discoveries if row.get("discovery_status") == "fetch_failed"),
        "download_authorized": False,
        "scoring_authorized": False,
        "status": (
            "await_verified_domains" if not verified
            else ("await_fetcher_or_live_scan" if fetcher is None else "candidates_pending_review")
        ),
        "csv_path": str(csv_path),
        "html_path": str(html_path),
        "notice": "无已核验域名时只生成空工作包；有核验域名后传入fetcher扫描同域HTTPS PDF。",
    }
    write_discovery_html(html_path, discoveries, summary)
    Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


APPLICATION_VERSION = "official-report-discovery-application-v1"
ACCEPT = {"accept", "accepted", "confirm", "confirmed", "通过", "确认"}
REJECT = {"reject", "rejected", "拒绝"}
DEFER = {"defer", "deferred", "暂缓"}
DECISIONS = ACCEPT | REJECT | DEFER
REQUIRED_ON_DECIDE = ("review_decision", "reviewer", "reviewed_at", "review_note")


def default_https_fetcher(url: str, *, timeout: float = 20.0) -> str:
    """Minimal HTTPS GET for issuer pages; discovery only, never downloads PDFs."""
    import urllib.request

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("only HTTPS page fetches are allowed")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AegisESG/0.2 official-domain-discovery"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - HTTPS only
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="ignore")


def evaluate_official_report_discovery(rows: list[dict[str, str]]) -> dict[str, Any]:
    incomplete: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    accepted: list[dict[str, str]] = []
    rejected = 0
    deferred = 0
    for row in rows:
        if not (row.get("source_url") or "").strip():
            continue
        code = row.get("company_code", "")
        decision = (row.get("review_decision") or "").strip().lower()
        if not decision:
            incomplete.append({"company_code": code, "fields": list(REQUIRED_ON_DECIDE)})
            continue
        if decision not in DECISIONS:
            invalid.append({"company_code": code, "decision": decision})
            continue
        missing = [field for field in REQUIRED_ON_DECIDE if not (row.get(field) or "").strip()]
        if missing:
            incomplete.append({"company_code": code, "fields": missing})
            continue
        if len((row.get("review_note") or "").strip()) < 8:
            incomplete.append({"company_code": code, "fields": ["review_note"]})
            continue
        if decision in ACCEPT:
            url = (row.get("source_url") or "").strip()
            parsed = urlparse(url)
            domain = normalize_host(row.get("official_domain") or "")
            host = normalize_host(parsed.hostname or "")
            if parsed.scheme != "https" or not same_registered_domain(host, domain):
                invalid.append({"company_code": code, "decision": "accept_requires_same_domain_https"})
                continue
            if row.get("document_type") not in {"annual_report", "esg_report"}:
                invalid.append({"company_code": code, "decision": "accept_requires_document_type"})
                continue
            accepted.append(row)
        elif decision in REJECT:
            rejected += 1
        else:
            deferred += 1

    if invalid:
        status = "reject_template"
    elif incomplete or not any((row.get("source_url") or "").strip() for row in rows):
        status = "blocked_external_review"
    elif accepted:
        status = "ready_to_register_report_urls"
    else:
        status = "no_report_urls_accepted"
    return {
        "policy_version": APPLICATION_VERSION,
        "row_count": len(rows),
        "incomplete_rows": len(incomplete),
        "invalid_rows": len(invalid),
        "accepted_rows": len(accepted),
        "rejected_rows": rejected,
        "deferred_rows": deferred,
        "incomplete_examples": incomplete[:20],
        "invalid_examples": invalid[:20],
        "status": status,
        "queue_updated": False,
        "download_authorized": False,
        "scoring_authorized": False,
        "decision": (
            "apply_accepted_urls_to_source_queue"
            if status == "ready_to_register_report_urls"
            else ("use_allowed_review_decision" if invalid else "complete_all_required_review_fields")
        ),
    }


def apply_official_report_discovery(
    discovery_csv_path: str | Path,
    queue_path: str | Path,
    *,
    output_queue_path: str | Path | None = None,
    application_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write accepted same-domain HTTPS report URLs into the queue without downloading."""
    rows = _read_csv(discovery_csv_path)
    report = evaluate_official_report_discovery(rows)
    if report["status"] != "ready_to_register_report_urls":
        if application_path:
            Path(application_path).parent.mkdir(parents=True, exist_ok=True)
            Path(application_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    accepted = {
        (
            (row.get("company_code") or "").strip(),
            (row.get("report_year") or "").strip(),
            (row.get("document_type") or "").strip(),
        ): row
        for row in rows
        if (row.get("review_decision") or "").strip().lower() in ACCEPT
        and (row.get("source_url") or "").strip()
    }
    queue = _read_csv(queue_path)
    if not queue:
        raise ValueError("官网来源队列为空，无法登记报告URL")
    fields = tuple(queue[0].keys())
    updated = 0
    for row in queue:
        key = (
            (row.get("company_code") or "").strip(),
            (row.get("report_year") or "").strip(),
            (row.get("document_type") or "").strip(),
        )
        hit = accepted.get(key)
        if not hit:
            continue
        if (row.get("domain_verification") or "").strip().lower() != "verified":
            continue
        row["candidate_url"] = hit["source_url"]
        row["download_status"] = "pending_official_download"
        row["next_action"] = "候选URL已人工确认，可进入官网下载清单复核"
        row["scoring_authorized"] = "False"
        updated += 1

    target = Path(output_queue_path or queue_path)
    _write_csv(target, queue, fields)
    report["queue_updated"] = True
    report["queue_rows_updated"] = updated
    report["output_queue_path"] = str(target)
    report["download_authorized"] = False
    report["scoring_authorized"] = False
    report["notice"] = "已写入候选报告URL；需 prepare_official_download_manifest 后才进入下载器，评分仍未授权。"
    if application_path:
        Path(application_path).parent.mkdir(parents=True, exist_ok=True)
        Path(application_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
