from __future__ import annotations

import json
import html
import re
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen

from ..universe_builder import ExchangeSecurity, normalize_stock_code


CODE_KEYS = ("stock_code", "code", "zqdm", "agdm", "a_stock_code", "company_code", "证券代码", "股票代码", "股份代号")
NAME_KEYS = ("company_name", "name", "zqjc", "gsjc", "agjc", "company_abbr", "sec_name_cn", "证券简称", "股票简称", "股份简称")
INDUSTRY_KEYS = ("industry", "hymc", "sshy", "sshymc", "csrc_code_desc", "行业", "所属行业", "行业名称")
ENTITY_KEYS = ("entity_id", "credit_code", "unified_social_credit_code", "统一社会信用代码")
STATUS_KEYS = ("listing_status", "sszt", "status", "上市状态")


@dataclass(frozen=True)
class ListingPage:
    rows: tuple[dict, ...]
    page_no: int
    page_count: int
    total_count: int


def fetch_json(url: str, referer: str = "", timeout: int = 30) -> bytes:
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "User-Agent": "Mozilla/5.0 (compatible; AegisESG/1.0; public-data-audit)",
    }
    if referer:
        headers["Referer"] = referer
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "").lower()
    if b"<html" in payload[:500].lower() or "text/html" in content_type:
        raise ValueError("交易所接口返回HTML验证页，已拒绝写入")
    return payload


def parse_listing_page(payload: bytes | str, requested_page: int = 1) -> ListingPage:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8-sig")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError("交易所接口未返回有效JSON") from error
    root = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else data
    if not isinstance(root, dict):
        raise ValueError("交易所JSON顶层结构无法识别")
    rows = _first_list(root, ("data", "rows", "list", "result", "records"))
    if rows is None and isinstance(root.get("data"), dict):
        nested = root["data"]
        rows = _first_list(nested, ("rows", "list", "result", "records", "data"))
        root = {**root, **nested}
    if rows is None and isinstance(root.get("pageHelp"), dict):
        nested = root["pageHelp"]
        rows = root.get("result") if isinstance(root.get("result"), list) else nested.get("data")
        root = {**root, **nested}
    if rows is None or any(not isinstance(item, dict) for item in rows):
        raise ValueError("交易所JSON中没有可识别的证券记录数组")
    metadata = root.get("metadata") if isinstance(root.get("metadata"), dict) else {}
    paging = {**root, **metadata}
    total = _first_int(paging, ("total", "totalCount", "recordcount", "total_count"), len(rows))
    page_count = _first_int(paging, ("pageCount", "pagecount", "totalPages", "page_count"), 1)
    page_no = _first_int(paging, ("pageNo", "pageno", "page", "page_no"), requested_page)
    if page_no != requested_page:
        raise ValueError(f"交易所分页响应错位: 请求{requested_page}，返回{page_no}")
    return ListingPage(tuple(rows), page_no, page_count, total)


def collect_listing_pages(
    exchange: str, source_url: str, as_of_date: str,
    fetch_page: Callable[[int], bytes | str], max_pages: int = 1000,
) -> list[ExchangeSecurity]:
    records: list[ExchangeSecurity] = []
    expected_total = None
    expected_pages = None
    for page_no in range(1, max_pages + 1):
        page = parse_listing_page(fetch_page(page_no), page_no)
        if expected_total is None:
            expected_total, expected_pages = page.total_count, page.page_count
            if expected_pages < 1 or expected_pages > max_pages:
                raise ValueError(f"交易所分页总页数异常: {expected_pages}")
        elif (page.total_count, page.page_count) != (expected_total, expected_pages):
            raise ValueError("交易所分页期间总条数发生变化，请重新冻结快照")
        records.extend(_row_to_security(row, exchange, source_url, as_of_date) for row in page.rows)
        if page_no >= expected_pages:
            break
    if len(records) != expected_total:
        raise ValueError(f"交易所分页不完整: 声明{expected_total}条，实际{len(records)}条")
    if len({item.stock_code for item in records}) != len(records):
        raise ValueError("交易所分页结果包含重复证券代码")
    return records


def _row_to_security(row: dict, exchange: str, source_url: str, as_of_date: str) -> ExchangeSecurity:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    code = _first_value(lowered, CODE_KEYS)
    name = _clean_html(_first_value(lowered, NAME_KEYS))
    if not code or not name:
        raise ValueError("交易所证券记录缺少代码或简称")
    normalized_code = normalize_stock_code(str(code), exchange)
    return ExchangeSecurity(
        normalized_code, name, exchange,
        str(_first_value(lowered, INDUSTRY_KEYS) or "待分类").strip(),
        str(_first_value(lowered, ENTITY_KEYS) or normalized_code).strip().upper(),
        listing_status=str(_first_value(lowered, STATUS_KEYS) or "上市").strip(),
        source_url=source_url, as_of_date=as_of_date,
    )


def _first_list(data: dict, keys: tuple[str, ...]):
    for key in keys:
        if isinstance(data.get(key), list):
            return data[key]
    return None


def _first_int(data: dict, keys: tuple[str, ...], default: int) -> int:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return int(value)
    return default


def _first_value(data: dict, keys: tuple[str, ...]):
    for key in keys:
        value = data.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _clean_html(value) -> str:
    if value is None:
        return ""
    text = re.sub(r"<[^>]+>", "", str(value))
    return html.unescape(text).strip()
