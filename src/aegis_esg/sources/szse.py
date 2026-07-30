from __future__ import annotations

import json
import csv
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Callable
from pathlib import Path


SZSE_QUERY_URL = "https://www.szse.cn/api/disc/announcement/annList"
SZSE_DOCUMENT_ORIGIN = "https://disc.static.szse.cn/"


@dataclass(frozen=True)
class SZSEDisclosure:
    stock_code: str
    company_name: str
    published_date: str
    title: str
    document_type: str
    source_url: str
    source: str = "SZSE"


def classify_title(title: str, report_year: str) -> str | None:
    compact = title.replace(" ", "")
    if "摘要" in compact or report_year not in compact:
        return None
    if f"{report_year}年年度报告" in compact or f"{report_year}年度报告" in compact:
        return "annual_report"
    terms = ("环境、社会和公司治理报告", "环境社会和公司治理报告", "可持续发展报告", "社会责任报告", "ESG报告")
    return "esg_report" if any(term in compact for term in terms) else None


def parse_response(payload: bytes | str) -> list[SZSEDisclosure]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    raw = json.loads(payload)
    rows = raw.get("data") or raw.get("result") or raw.get("announcements") or []
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    result = []
    for item in rows:
        code_value = item.get("secCode") or item.get("stockCode") or item.get("code") or ""
        name_value = item.get("secName") or item.get("stockName") or ""
        if isinstance(code_value, list):
            code_value = code_value[0] if code_value else ""
        if isinstance(name_value, list):
            name_value = name_value[0] if name_value else ""
        code = str(code_value).strip()
        path = item.get("attachPath") or item.get("attachUrl") or item.get("url") or ""
        if not code or not path:
            continue
        result.append(SZSEDisclosure(
            stock_code=code + ".SZ", company_name=str(name_value),
            published_date=(item.get("publishTime") or item.get("publishDate") or "")[:10],
            title=item.get("title") or item.get("announcementTitle") or "",
            document_type="unclassified", source_url=urllib.parse.urljoin(SZSE_DOCUMENT_ORIGIN, path),
        ))
    return result


def discover_reports(
    stock_code: str, report_year: int,
    fetcher: Callable[[urllib.request.Request], bytes] | None = None,
) -> list[SZSEDisclosure]:
    publish_year = report_year + 1
    body = json.dumps({
        "seDate": [f"{publish_year}-01-01", min(date.today(), date(publish_year, 7, 31)).isoformat()],
        "stock": [stock_code.split(".")[0]], "channelCode": ["listedNotice_disc"],
        "bigCategoryId": ["010301"], "pageSize": 100, "pageNum": 1,
    }).encode()
    request = urllib.request.Request(
        SZSE_QUERY_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Referer": "https://www.szse.cn/disclosure/", "User-Agent": "AegisESG/0.2"},
    )
    rows = parse_response((fetcher or _fetch)(request))
    selected = {}
    for item in rows:
        kind = classify_title(item.title, str(report_year))
        if kind:
            selected[kind] = SZSEDisclosure(**{**vars(item), "document_type": kind})
    return list(selected.values())


def discover_batch(
    companies: list[tuple[str, str]], report_year: int, output_path: str | Path,
    failures_path: str | Path, summary_path: str | Path, delay: float = .5,
    resume: bool = False,
    discoverer: Callable[[str, int], list[SZSEDisclosure]] = discover_reports,
) -> tuple[list[SZSEDisclosure], list[dict], dict]:
    output, failures_output, summary_output = map(Path, (output_path, failures_path, summary_path))
    rows = _read_disclosures(output) if resume and output.exists() else []
    completed = {item.stock_code for item in rows}
    failures = {}
    if resume and failures_output.exists():
        with failures_output.open(encoding="utf-8-sig", newline="") as stream:
            failures = {row["company_code"]: row for row in csv.DictReader(stream)}
    targets = [(code, name) for code, name in companies if code not in completed]
    for index, (code, name) in enumerate(targets):
        try:
            found = discoverer(code, report_year)
            if not any(item.document_type == "annual_report" for item in found):
                raise ValueError("official annual report not found")
            rows.extend(found)
            failures.pop(code, None)
        except Exception as exc:
            failures[code] = {"company_code": code, "company_name": name, "error": str(exc)}
        _write_disclosures(output, rows, report_year)
        _write_failures(failures_output, list(failures.values()))
        if delay and index + 1 < len(targets):
            time.sleep(delay)
    unique = {(item.stock_code, item.document_type, item.source_url): item for item in rows}
    rows = sorted(unique.values(), key=lambda item: (item.stock_code, item.document_type, item.source_url))
    _write_disclosures(output, rows, report_year)
    codes = {code for code, _ in companies}
    annual_codes = {item.stock_code for item in rows if item.document_type == "annual_report"}
    esg_codes = {item.stock_code for item in rows if item.document_type == "esg_report"}
    summary = {
        "company_count": len(codes), "completed_company_count": len(annual_codes),
        "annual_report_count": sum(item.document_type == "annual_report" for item in rows),
        "esg_report_count": sum(item.document_type == "esg_report" for item in rows),
        "esg_company_count": len(esg_codes), "failure_count": len(failures),
        "remaining_company_count": len(codes - annual_codes),
        "complete": annual_codes == codes and not failures, "applicable": False,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rows, list(failures.values()), summary


def _write_disclosures(path: Path, rows: list[SZSEDisclosure], report_year: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ("company_code", "company_name", "report_year", "document_type", "source_url", "published_date", "title")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({
            "company_code": item.stock_code, "company_name": item.company_name,
            "report_year": report_year, "document_type": item.document_type,
            "source_url": item.source_url, "published_date": item.published_date, "title": item.title,
        } for item in rows)


def _read_disclosures(path: Path) -> list[SZSEDisclosure]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [SZSEDisclosure(
            stock_code=row.get("company_code") or row.get("stock_code") or "",
            company_name=row["company_name"],
            published_date=row["published_date"], title=row["title"],
            document_type=row["document_type"], source_url=row["source_url"],
        ) for row in csv.DictReader(stream)]


def _write_failures(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("company_code", "company_name", "error"), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def _fetch(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=30) as response:
        content_type = response.headers.get("Content-Type", "")
        payload = response.read()
    if "json" not in content_type.lower() and not payload.lstrip().startswith((b"{", b"[")):
        raise ValueError("深交所公告接口返回非JSON内容")
    return payload
