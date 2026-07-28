from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Callable


SSE_QUERY_URL = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
SSE_DOCUMENT_ORIGIN = "https://www.sse.com.cn"


@dataclass(frozen=True)
class SSEDisclosure:
    stock_code: str
    company_name: str
    published_date: str
    title: str
    document_type: str
    source_url: str
    source: str = "SSE"


def query_disclosures(
    stock_code: str,
    begin_date: str,
    end_date: str,
    fetcher: Callable[[urllib.request.Request], bytes] | None = None,
    attempts: int = 3,
) -> list[SSEDisclosure]:
    """Query the official SSE disclosure endpoint and classify annual/ESG reports."""
    numeric_code = stock_code.split(".")[0]
    parameters = {
        "isPagination": "true",
        "productId": numeric_code,
        "keyWord": "",
        "securityType": "0101,120100,020100,020200,120200",
        "reportType": "ALL",
        "beginDate": begin_date,
        "endDate": end_date,
        "pageHelp.pageSize": "100",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.endPage": "1",
    }
    request = urllib.request.Request(
        SSE_QUERY_URL + "?" + urllib.parse.urlencode(parameters),
        headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "AegisESG/0.2"},
    )
    fetcher = fetcher or _fetch
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return parse_response(fetcher(request))
        except Exception as error:  # transient official-site errors are retried
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"上交所公告查询失败: {stock_code}") from last_error


def discover_reports(
    stock_code: str,
    report_year: int,
    fetcher: Callable[[urllib.request.Request], bytes] | None = None,
) -> list[SSEDisclosure]:
    publish_year = report_year + 1
    disclosures = query_disclosures(
        stock_code,
        f"{publish_year}-01-01",
        min(date.today(), date(publish_year, 7, 31)).isoformat(),
        fetcher=fetcher,
    )
    target = str(report_year)
    result = []
    for item in disclosures:
        title = item.title.replace(" ", "")
        kind = classify_title(title, target)
        if kind:
            result.append(SSEDisclosure(
                stock_code=item.stock_code,
                company_name=item.company_name,
                published_date=item.published_date,
                title=item.title,
                document_type=kind,
                source_url=item.source_url,
            ))
    # Keep the latest official document of each kind; exclude summaries in classifier.
    unique: dict[str, SSEDisclosure] = {}
    for item in sorted(result, key=lambda x: (x.published_date, x.title)):
        unique[item.document_type] = item
    return list(unique.values())


def classify_title(title: str, report_year: str) -> str | None:
    if "摘要" in title or report_year not in title:
        return None
    if f"{report_year}年年度报告" in title or f"{report_year}年度报告" in title:
        return "annual_report"
    esg_terms = ("环境、社会和公司治理报告", "环境社会和公司治理报告", "可持续发展报告", "社会责任报告", "ESG报告")
    if any(term in title for term in esg_terms):
        return "esg_report"
    return None


def parse_response(payload: bytes | str) -> list[SSEDisclosure]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    raw = json.loads(payload)
    data = raw.get("result") or raw.get("pageHelp", {}).get("data") or []
    result = []
    for item in data:
        path = item.get("URL") or ""
        if not path:
            continue
        result.append(SSEDisclosure(
            stock_code=(item.get("SECURITY_CODE") or "") + ".SH",
            company_name=item.get("SECURITY_NAME") or "",
            published_date=item.get("SSEDATE") or "",
            title=item.get("TITLE") or "",
            document_type="unclassified",
            source_url=urllib.parse.urljoin(SSE_DOCUMENT_ORIGIN, path),
        ))
    return result


def _fetch(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()

