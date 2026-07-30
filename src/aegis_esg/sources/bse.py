from __future__ import annotations

import json
import re
from datetime import date
from dataclasses import dataclass
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from typing import Callable
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ..universe_builder import ExchangeSecurity, normalize_stock_code


BSE_ENDPOINT = "https://www.bse.cn/nqxxController/nqxxCnzq.do"
BSE_LIST_PAGE = "https://www.bse.cn/nq/listedcompany.html"
BSE_DISCLOSURE_ORIGIN = "https://www.bse.cn"
BSE_DISCLOSURE_ENDPOINT = "https://www.bseinfo.net/disclosureInfoController/companyAnnouncement.do"


@dataclass(frozen=True)
class BsePage:
    rows: tuple[dict, ...]
    page_no: int
    page_count: int
    total_count: int


@dataclass(frozen=True)
class BseCodeMapping:
    company_name: str
    listing_date: str
    old_code: str
    new_code: str


@dataclass(frozen=True)
class BseDisclosure:
    stock_code: str
    company_name: str
    published_date: str
    title: str
    document_type: str
    source_url: str


def classify_disclosure_title(title: str, report_year: str) -> str | None:
    compact = re.sub(r"\s+", "", title)
    rejected = ("摘要", "问询函", "回复", "提示性公告", "关于披露", "更正公告", "取消")
    if report_year not in compact or any(term in compact for term in rejected):
        return None
    if f"{report_year}年年度报告" in compact or f"{report_year}年度报告" in compact:
        return "annual_report"
    esg_terms = ("环境、社会和公司治理报告", "环境社会和公司治理报告", "可持续发展报告", "社会责任报告", "ESG报告")
    return "esg_report" if any(term in compact for term in esg_terms) else None


def parse_bse_disclosures(payload: bytes | str, report_year: int) -> tuple[list[BseDisclosure], int, int]:
    """Parse the official initDisclosureList/companyAnnouncement JSON(P) shapes."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8-sig")
    text = payload.strip()
    match = re.fullmatch(r"(?:[\w$.]+|null)?\((.*)\)", text, re.S)
    if match:
        text = match.group(1)
    try:
        root = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("北交所公告接口未返回有效JSON/JSONP") from error
    if isinstance(root, list):
        page = (root[0] if root else {}).get("listInfo", {})
        containers = page.get("content") or []
    else:
        page = (root.get("data") or {}) if isinstance(root, dict) else {}
        containers = page.get("content") or []
    rows = []
    for container in containers:
        disclosures = container.get("disclosures") if isinstance(container, dict) else None
        for item in disclosures or ([] if not isinstance(container, dict) else [container]):
            code = str(item.get("companyCd") or "").strip()
            path = str(item.get("destFilePath") or "").strip()
            title = f"{item.get('disclosureTitle') or ''}{item.get('disclosurePostTitle') or ''}".strip()
            kind = classify_disclosure_title(title, str(report_year))
            if not code or not path or not kind:
                continue
            rows.append(BseDisclosure(
                normalize_stock_code(code, "BSE"), str(item.get("companyName") or "").strip(),
                str(item.get("publishDate") or "")[:10], title, kind,
                path if path.startswith("http") else BSE_DISCLOSURE_ORIGIN + "/" + path.lstrip("/"),
            ))
    try:
        page_no = int(page.get("number", 0))
        page_count = int(page.get("totalPages", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("北交所公告分页元数据无效") from error
    return rows, page_no, page_count


def discover_bse_reports(
    stock_code: str, report_year: int, fetch_page: Callable[[int], bytes | str], max_pages: int = 200,
) -> list[BseDisclosure]:
    """Discover a company's reports from frozen official disclosure pages."""
    normalized = normalize_stock_code(stock_code.split(".")[0], "BSE")
    expected_pages = None
    found: list[BseDisclosure] = []
    for requested_page in range(max_pages):
        rows, page_no, page_count = parse_bse_disclosures(fetch_page(requested_page), report_year)
        if page_no != requested_page:
            raise ValueError(f"北交所公告分页响应错位: 请求{requested_page}，返回{page_no}")
        if expected_pages is None:
            expected_pages = page_count
            if expected_pages < 1 or expected_pages > max_pages:
                raise ValueError(f"北交所公告分页总数异常: {expected_pages}")
        elif page_count != expected_pages:
            raise ValueError("北交所公告分页期间总页数发生变化，请重新冻结快照")
        found.extend(item for item in rows if item.stock_code == normalized)
        if requested_page + 1 >= expected_pages:
            break
    selected = {}
    for item in sorted(found, key=lambda value: (value.published_date, value.title, value.source_url)):
        selected[item.document_type] = item
    return [selected[kind] for kind in ("annual_report", "esg_report") if kind in selected]


def discover_bse_annual_report(
    stock_code: str, report_year: int,
    fetcher: Callable[[Request], bytes] | None = None,
) -> list[BseDisclosure]:
    """Query the official annual-report category with stable category codes."""
    publish_year = report_year + 1
    end_date = min(date.today(), date(publish_year, 7, 31)).isoformat()
    code = stock_code.split(".")[0]

    def fetch_page(page_no: int) -> bytes:
        body = urlencode({
            "disclosureType[]": "9504-0100", "disclosureSubtype[]": "9503-1001",
            "page": page_no, "companyCd": code, "isNewThree": 1,
            "startTime": f"{publish_year}-01-01", "endTime": end_date,
            "keyword": "", "xxfcbj[]": "2", "hyType": "",
            "needFields": "companyCd,companyName,disclosureTitle,disclosurePostTitle,destFilePath,publishDate,xxfcbj,fileExt,xxzrlx",
        }, doseq=True).encode()
        request = Request(BSE_DISCLOSURE_ENDPOINT, data=body, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
            "Referer": "https://www.bseinfo.net/disclosure/announcement.html",
            "X-Requested-With": "XMLHttpRequest",
        })
        if fetcher:
            return fetcher(request)
        with build_opener(HTTPCookieProcessor(CookieJar())).open(request, timeout=30) as response:
            payload = response.read()
        if b"<html" in payload[:500].lower():
            raise ValueError("北交所公告接口返回HTML验证页，已拒绝写入")
        return payload

    return discover_bse_reports(stock_code, report_year, fetch_page)


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "td":
            self.in_cell, self.cell_parts = True, []

    def handle_data(self, data):
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "td" and self.in_cell:
            self.row.append("".join(self.cell_parts).strip())
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def parse_bse_code_mapping(payload: bytes | str) -> list[BseCodeMapping]:
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    parser = _TableParser()
    parser.feed(text)
    mappings = []
    for row in parser.rows:
        if len(row) >= 5 and re.fullmatch(r"\d{6}", row[3]) and re.fullmatch(r"920\d{3}", row[4]):
            mappings.append(BseCodeMapping(row[1], row[2], f"{row[3]}.BJ", f"{row[4]}.BJ"))
    if not mappings:
        raise ValueError("北交所新旧代码对照表中没有可识别记录")
    if len({item.old_code for item in mappings}) != len(mappings):
        raise ValueError("北交所新旧代码对照表包含重复旧代码")
    if len({item.new_code for item in mappings}) != len(mappings):
        raise ValueError("北交所新旧代码对照表包含重复新代码")
    return mappings


def make_bse_fetcher(timeout: int = 30) -> Callable[[int], bytes]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    waf_cookie = ""

    def fetch(page_no: int) -> bytes:
        nonlocal waf_cookie
        body = urlencode({
            "page": str(page_no), "typejb": "T", "xxfcbj[]": "2",
            "xxzqdm": "", "sortfield": "xxzqdm", "sorttype": "asc",
        }).encode()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/110.0.0.0 Safari/537.36",
            "Referer": BSE_LIST_PAGE,
        }
        if waf_cookie:
            headers["Cookie"] = waf_cookie
        request = Request(BSE_ENDPOINT, data=body, headers=headers)
        try:
            response = opener.open(request, timeout=timeout)
            payload = response.read()
        except HTTPError as error:
            if error.code != 307:
                raise
            cookie = error.headers.get("Set-Cookie", "").split(";", 1)[0]
            if cookie:
                waf_cookie = cookie
            payload = error.read()
        # The WAF returns a self-redirect while setting its short-lived cookie.
        if b"307 Temporary Redirect" in payload[:500]:
            retry_headers = {**headers, "Cookie": waf_cookie}
            response = opener.open(Request(BSE_ENDPOINT, data=body, headers=retry_headers), timeout=timeout)
            payload = response.read()
        cookie = response.headers.get("Set-Cookie", "").split(";", 1)[0]
        if cookie:
            waf_cookie = cookie
        if b"<html" in payload[:500].lower():
            raise ValueError("北交所接口返回HTML验证页，已拒绝写入")
        return payload

    return fetch


def parse_bse_page(payload: bytes | str, requested_page: int) -> BsePage:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8-sig")
    text = payload.strip()
    match = re.fullmatch(r"(?:null)?\((.*)\)", text, re.S)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("北交所接口未返回有效JSON/JSONP") from error
    root = data[0] if isinstance(data, list) and len(data) == 1 else data
    if not isinstance(root, dict) or not isinstance(root.get("content"), list):
        raise ValueError("北交所接口缺少证券记录数组")
    page_no = int(root.get("number", -1))
    if page_no != requested_page:
        raise ValueError(f"北交所分页响应错位: 请求{requested_page}，返回{page_no}")
    return BsePage(
        tuple(root["content"]), page_no,
        int(root.get("totalPages", 0)), int(root.get("totalElements", 0)),
    )


def collect_bse_listings(
    fetch_page: Callable[[int], bytes | str], source_url: str = BSE_LIST_PAGE,
    expected_as_of_date: str = "", max_pages: int = 100,
) -> tuple[list[ExchangeSecurity], str, list[bytes]]:
    records: list[ExchangeSecurity] = []
    raw_pages: list[bytes] = []
    expected_total = expected_pages = None
    report_dates: set[str] = set()
    for page_no in range(max_pages):
        payload = fetch_page(page_no)
        raw_pages.append(payload if isinstance(payload, bytes) else payload.encode())
        page = parse_bse_page(payload, page_no)
        if expected_total is None:
            expected_total, expected_pages = page.total_count, page.page_count
            if expected_pages < 1 or expected_pages > max_pages:
                raise ValueError(f"北交所分页总页数异常: {expected_pages}")
        elif (page.total_count, page.page_count) != (expected_total, expected_pages):
            raise ValueError("北交所分页期间总条数发生变化，请重新冻结快照")
        for row in page.rows:
            code = normalize_stock_code(str(row.get("xxzqdm", "")), "BSE")
            name = str(row.get("xxzqjc", "")).strip()
            raw_date = str(row.get("xxjsrq", "")).strip()
            if not name or not re.fullmatch(r"\d{8}", raw_date):
                raise ValueError(f"北交所证券记录缺少简称或报告日期: {code}")
            report_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            report_dates.add(report_date)
            records.append(ExchangeSecurity(
                code, name, "BSE", str(row.get("xxhyzl", "待分类")).strip() or "待分类",
                code, listing_status="上市", source_url=source_url, as_of_date=report_date,
            ))
        if page_no + 1 >= expected_pages:
            break
    if len(records) != expected_total:
        raise ValueError(f"北交所分页不完整: 声明{expected_total}条，实际{len(records)}条")
    if len({item.stock_code for item in records}) != len(records):
        raise ValueError("北交所分页结果包含重复证券代码")
    if len(report_dates) != 1:
        raise ValueError(f"北交所报告日期不一致: {sorted(report_dates)}")
    as_of_date = next(iter(report_dates))
    if expected_as_of_date and expected_as_of_date != as_of_date:
        raise ValueError(f"北交所名单日期不一致: 期望{expected_as_of_date}，接口为{as_of_date}")
    return records, as_of_date, raw_pages
