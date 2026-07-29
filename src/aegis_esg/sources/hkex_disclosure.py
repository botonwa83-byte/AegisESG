from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable


HKEXNEWS_ORIGIN = "https://www1.hkexnews.hk"
HKEX_STOCK_LOOKUP = HKEXNEWS_ORIGIN + "/search/prefix.do"
HKEX_TITLE_SEARCH = HKEXNEWS_ORIGIN + "/search/titlesearch.xhtml?lang=en"


@dataclass(frozen=True)
class HKEXDisclosure:
    company_code: str
    company_name: str
    report_year: int
    document_type: str
    source_url: str
    published_date: str
    title: str
    headline: str
    stock_id: str


class _TitleSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.row: dict | None = None
        self.field = ""
        self.in_headline = False
        self.in_doc_link = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "tr":
            self.row = {"release": "", "code": "", "name": "", "headline": "", "title": "", "href": ""}
        if self.row is None:
            return
        if tag == "td":
            if "release-time" in classes:
                self.field = "release"
            elif "stock-short-code" in classes:
                self.field = "code"
            elif "stock-short-name" in classes:
                self.field = "name"
        elif tag == "div" and "headline" in classes:
            self.in_headline = True
            self.field = "headline"
        elif tag == "div" and "doc-link" in classes:
            self.in_doc_link = True
        elif tag == "a" and self.in_doc_link and attributes.get("href"):
            self.row["href"] = attributes["href"]
            self.field = "title"

    def handle_endtag(self, tag):
        if tag == "tr" and self.row is not None:
            if self.row["href"]:
                self.rows.append(self.row)
            self.row = None
            self.field = ""
        elif tag == "td":
            self.field = ""
        elif tag == "div" and self.in_headline:
            self.in_headline = False
            self.field = ""
        elif tag == "div" and self.in_doc_link:
            self.in_doc_link = False
            self.field = ""
        elif tag == "a" and self.field == "title":
            self.field = ""

    def handle_data(self, data):
        if self.row is not None and self.field:
            self.row[self.field] += " " + data.strip()


def parse_stock_lookup(payload: bytes | str, expected_code: str) -> tuple[str, str]:
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    match = re.fullmatch(r"\s*callback\((.*)\);?\s*", text, re.S)
    if not match:
        raise ValueError("HKEXnews证券查询不是有效JSONP")
    data = json.loads(match.group(1))
    numeric = expected_code.split(".")[0].zfill(5)
    exact = [item for item in data.get("stockInfo", []) if str(item.get("code", "")).zfill(5) == numeric]
    if len(exact) != 1 or not exact[0].get("stockId"):
        raise ValueError(f"HKEXnews证券代码未唯一解析: {expected_code}")
    return str(exact[0]["stockId"]), str(exact[0].get("name", "")).strip()


def parse_title_search(payload: bytes | str, expected_code: str, stock_id: str) -> list[HKEXDisclosure]:
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    if "Listed Company Information Title Search" not in text:
        raise ValueError("HKEXnews标题检索返回非预期页面")
    parser = _TitleSearchParser()
    parser.feed(text)
    total_match = re.search(r"Total records found:\s*([0-9,]+)", text)
    if not total_match:
        raise ValueError("HKEXnews标题检索缺少总记录数")
    total = int(total_match.group(1).replace(",", ""))
    if total != len(parser.rows):
        raise ValueError(f"HKEXnews标题检索分页不完整: {len(parser.rows)}/{total}")
    expected_numeric = expected_code.split(".")[0].zfill(5)
    result = []
    for row in parser.rows:
        code = re.sub(r"\D", "", row["code"]).zfill(5)
        if code != expected_numeric:
            raise ValueError(f"HKEXnews标题检索证券代码错配: {code}/{expected_numeric}")
        release = re.sub(r"^.*Release Time:\s*", "", row["release"]).strip()
        date_match = re.search(r"(\d{2})/(\d{2})/(\d{4})", release)
        if not date_match:
            raise ValueError("HKEXnews公告发布日期无效")
        published = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
        title = _clean(row["title"])
        headline = _clean(row["headline"])
        document_type, report_year = classify_continuity_document(title, headline)
        if document_type:
            result.append(HKEXDisclosure(
                expected_code.upper(), re.sub(r"^Stock Short Name:\s*", "", _clean(row["name"])), report_year, document_type,
                urllib.parse.urljoin(HKEXNEWS_ORIGIN, html.unescape(row["href"])),
                published, title, headline, stock_id,
            ))
    return result


def classify_continuity_document(title: str, headline: str) -> tuple[str | None, int]:
    combined = f"{headline} {title}".lower()
    title_lower = title.lower().strip()
    headline_lower = headline.lower()
    year_match = re.search(r"\b(20\d{2})\b", title)
    report_year = int(year_match.group(1)) if year_match else 0
    is_annual_title = bool(re.match(r"^(?:20\d{2}\s+)?annual report\b", title_lower))
    if "annual report" in combined and "summary" not in combined and (
        "financial statements" in headline_lower or is_annual_title
    ):
        return "annual_report", report_year
    if any(term in combined for term in ("environmental, social and governance", "esg report", "sustainability report")):
        return "esg_report", report_year
    if "listing documents" in combined or "global offering" in title.lower() or "prospectus" in title.lower():
        return "listing_document", report_year
    if any(term in combined for term in ("change of company name", "change of name", "changed its name", "renamed")):
        return "name_change_announcement", report_year
    return None, 0


def discover_hkex_continuity_documents(
    stock_code: str, from_date: str, to_date: str,
    fetcher: Callable[[urllib.request.Request], bytes] | None = None,
) -> tuple[list[HKEXDisclosure], dict[str, object]]:
    fetcher = fetcher or _fetch
    numeric = stock_code.split(".")[0].zfill(5)
    lookup_url = HKEX_STOCK_LOOKUP + "?" + urllib.parse.urlencode({
        "callback": "callback", "lang": "EN", "type": "A", "name": numeric, "market": "SEHK",
    })
    lookup_request = urllib.request.Request(lookup_url, headers=_headers())
    lookup_payload = fetcher(lookup_request)
    stock_id, _ = parse_stock_lookup(lookup_payload, stock_code)
    start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
    if start > end:
        raise ValueError("HKEXnews检索起始日期晚于结束日期")
    payloads: list[str] = []

    def query_range(range_start: date, range_end: date) -> list[HKEXDisclosure]:
        form = urllib.parse.urlencode({
            "lang": "EN", "category": "0", "market": "SEHK", "searchType": "0",
            "documentType": "", "t1code": "", "t2Gcode": "", "t2code": "",
            "stockId": stock_id, "from": range_start.strftime("%Y%m%d"),
            "to": range_end.strftime("%Y%m%d"), "MB-Daterange": "0",
        }).encode("ascii")
        request = urllib.request.Request(HKEX_TITLE_SEARCH, data=form, headers=_headers())
        payload = fetcher(request)
        text = payload.decode("utf-8")
        payloads.append(text)
        try:
            return parse_title_search(text, stock_code, stock_id)
        except ValueError as error:
            if "分页不完整" not in str(error) or range_start == range_end:
                raise
            midpoint = range_start + timedelta(days=(range_end - range_start).days // 2)
            return query_range(range_start, midpoint) + query_range(midpoint + timedelta(days=1), range_end)

    discovered = query_range(start, end)
    unique = {item.source_url: item for item in discovered}
    rows = sorted(unique.values(), key=lambda item: (item.published_date, item.source_url), reverse=True)
    return rows, {
        "stock_lookup": lookup_payload.decode("utf-8"),
        "title_search_ranges": payloads,
    }


def write_hkex_disclosures(path: str | Path, rows: Iterable[HKEXDisclosure]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(HKEXDisclosure.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in rows)


def read_hkex_disclosures(path: str | Path) -> list[HKEXDisclosure]:
    result = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            try:
                result.append(HKEXDisclosure(
                    row["company_code"].strip().upper(), row["company_name"].strip(),
                    int(row["report_year"]), row["document_type"].strip(), row["source_url"].strip(),
                    row["published_date"].strip(), row["title"].strip(), row["headline"].strip(),
                    row["stock_id"].strip(),
                ))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"HKEXnews文件清单第{line}行格式错误") from error
    return result


def select_continuity_downloads(rows: Iterable[HKEXDisclosure]) -> tuple[list[HKEXDisclosure], dict]:
    allowed = {"annual_report", "esg_report", "listing_document", "name_change_announcement"}
    grouped: dict[tuple[str, str], list[HKEXDisclosure]] = {}
    seen_urls = set()
    for item in rows:
        if item.document_type not in allowed or not item.source_url.lower().endswith(".pdf"):
            continue
        if item.source_url in seen_urls:
            raise ValueError(f"HKEXnews文件清单URL重复: {item.source_url}")
        seen_urls.add(item.source_url)
        grouped.setdefault((item.company_code, item.document_type), []).append(item)

    def rank(item: HKEXDisclosure) -> tuple[int, int, str, str]:
        formal_listing = int("listing documents" in item.headline.lower())
        return item.report_year, formal_listing, item.published_date, item.source_url

    selected = [max(items, key=rank) for items in grouped.values()]
    selected.sort(key=lambda item: (item.company_code, item.document_type))
    by_type = Counter(item.document_type for item in selected)
    summary = {
        "candidate_count": len(seen_urls),
        "selected_count": len(selected),
        "company_count": len({item.company_code for item in selected}),
        "document_type_counts": dict(sorted(by_type.items())),
        "duplicate_target_count": len(selected) - len({
            (item.company_code, item.report_year, item.document_type) for item in selected
        }),
        "complete": bool(selected),
    }
    if summary["duplicate_target_count"]:
        raise ValueError("HKEXnews下载清单存在目标路径冲突")
    return selected, summary


def _headers() -> dict[str, str]:
    return {"User-Agent": "AegisESG/0.2 public-disclosure-collector", "Referer": HKEX_TITLE_SEARCH}


def _fetch(request: urllib.request.Request) -> bytes:
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("HKEXnews公开检索失败") from last_error


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()
