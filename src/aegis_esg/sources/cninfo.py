"""巨潮资讯（cninfo）法定披露查询：深交所静态盘反爬时的备用PDF通道。"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from typing import Callable

from .report_titles import classify_report_title, normalize_title

CNINFO_SEARCH = "https://www.cninfo.com.cn/new/information/topSearch/query"
CNINFO_QUERY = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC = "https://static.cninfo.com.cn/"
CNINFO_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "AegisESG/0.2 public-disclosure-collector",
    "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "Origin": "https://www.cninfo.com.cn",
}
_ESG_TERMS = (
    "环境、社会和公司治理报告",
    "环境社会和公司治理报告",
    "可持续发展报告",
    "社会责任报告",
    "ESG报告",
)
_KEYWORDS = {
    "esg_report": (
        "可持续发展",
        "社会责任",
        "ESG",
        "环境、社会和公司治理",
        "环境社会和公司治理",
    ),
    "annual_report": ("年度报告", "年报"),
}


def _post(url: str, data: dict[str, str], fetcher: Callable | None = None) -> object:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers=CNINFO_HEADERS,
        method="POST",
    )
    if fetcher is not None:
        payload = fetcher(request)
        if isinstance(payload, bytes):
            return json.loads(payload.decode("utf-8"))
        return payload
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_org_id(stock_code: str, fetcher: Callable | None = None) -> str | None:
    numeric = stock_code.split(".")[0]
    payload = _post(CNINFO_SEARCH, {"keyWord": numeric, "maxNum": "10"}, fetcher=fetcher)
    if not isinstance(payload, list):
        return None
    for row in payload:
        if str(row.get("code") or "") == numeric and row.get("orgId"):
            return str(row["orgId"])
    return None


def find_disclosure_pdf(
    stock_code: str,
    report_year: int | str,
    document_type: str,
    *,
    fetcher: Callable | None = None,
    pause_seconds: float = 0.2,
) -> tuple[str, str] | None:
    """Return ``(title, static_pdf_url)`` for a classified disclosure, if any."""
    year = str(report_year)
    kind = document_type.strip()
    keywords = _KEYWORDS.get(kind)
    if not keywords:
        return None
    org_id = resolve_org_id(stock_code, fetcher=fetcher)
    if not org_id:
        return None
    numeric = stock_code.split(".")[0]
    publish_year = int(year) + 1
    se_date = f"{publish_year}-01-01~{publish_year}-07-31"
    stock = f"{numeric},{org_id}"
    seen: set[str] = set()
    for keyword in keywords:
        payload = _post(
            CNINFO_QUERY,
            {
                "pageNum": "1",
                "pageSize": "50",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": stock,
                "searchkey": keyword,
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": se_date,
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            },
            fetcher=fetcher,
        )
        announcements = payload.get("announcements") or [] if isinstance(payload, dict) else []
        for item in announcements:
            title = re.sub(r"</?em>", "", str(item.get("announcementTitle") or ""))
            adjunct = str(item.get("adjunctUrl") or "").lstrip("/")
            if not adjunct:
                continue
            classified = classify_report_title(normalize_title(title), year, _ESG_TERMS)
            if classified != kind:
                continue
            url = urllib.parse.urljoin(CNINFO_STATIC, adjunct)
            if url in seen:
                continue
            seen.add(url)
            return title, url
        if pause_seconds:
            time.sleep(pause_seconds)
    return None


def should_try_cninfo_fallback(source_url: str, error: str) -> bool:
    """True when SZSE static download failed in a way cninfo can often recover."""
    host_ok = "disc.static.szse.cn" in (source_url or "") or "szse.cn" in (source_url or "")
    if not host_ok:
        return False
    text = (error or "").lower()
    markers = (
        "不是有效pdf",
        "page verification",
        "antibot",
        "aliyun_waf",
        "<!doctype",
        "html",
        "403",
        "429",
        "timeout",
        "timed out",
        "curl",
    )
    return any(marker in text for marker in markers)
