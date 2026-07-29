from __future__ import annotations

import csv
import json
import re
import subprocess
import urllib.parse
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


HKEX_QUOTE_PAGE = "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote"
HKEX_QUOTE_API = "https://www1.hkex.com.hk/hkexwidget/data/getequityquote"


@dataclass(frozen=True)
class HKEXIssuerProfile:
    stock_code: str
    chinese_name: str
    chinese_short_name: str
    company_summary: str
    hsic_industry: str
    hsic_sub_sector: str
    csic_classification: str
    listing_category: str
    primary_market: str
    incorporation_place: str
    profile_updated_at: str
    source_url: str
    evidence_status: str


@dataclass(frozen=True)
class HKEXEvidenceDraft:
    decision_id: str
    batch_id: str
    operation: str
    supersedes: str
    stock_code: str
    decision: str
    sub_industry: str
    entity_id: str
    evidence_url: str
    evidence_date: str
    reviewer: str
    reviewed_at: str
    rationale: str
    review_status: str
    chinese_name: str
    chinese_short_name: str
    hsic_industry: str
    hsic_sub_sector: str
    company_summary: str
    mapping_version: str


def parse_hkex_access_token(page_html: str) -> str:
    function = re.search(r"LabCI\.getToken\s*=\s*function\s*\([^)]*\)\s*\{(.*?)\}", page_html, re.S)
    candidates = re.findall(r"(?<!//)\breturn\s+[\"']([^\"']+)[\"']", function.group(1) if function else "")
    candidates = [item for item in candidates if item != "Base64-AES-Encrypted-Token" and len(item) >= 20]
    if not candidates:
        raise ValueError("港交所报价页未找到有效访问令牌")
    return urllib.parse.unquote(candidates[-1])


def parse_hkex_quote_payload(payload: str, expected_code: str) -> HKEXIssuerProfile:
    text = payload.strip()
    match = re.fullmatch(r"[A-Za-z_$][\w$]*\((.*)\)\s*;?", text, re.S)
    if match:
        text = match.group(1)
    try:
        root = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("港交所报价接口未返回有效JSON/JSONP") from error
    data = root.get("data") or {}
    if str(data.get("responsecode")) != "000" or not isinstance(data.get("quote"), dict):
        raise ValueError(f"港交所报价接口响应失败: {data.get('responsecode')}")
    quote = data["quote"]
    code = normalize_hkex_profile_code(str(quote.get("sym") or quote.get("ric") or ""))
    expected = normalize_hkex_profile_code(expected_code)
    if code != expected:
        raise ValueError(f"港交所报价证券代码不一致: {code}!={expected}")
    name = str(quote.get("nm") or "").strip()
    summary = str(quote.get("summary") or "").strip()
    industry = str(quote.get("hsic_ind_classification") or "").strip()
    subsector = str(quote.get("hsic_sub_sector_classification") or "").strip()
    status = "candidate" if name and summary and (industry or subsector) else "incomplete"
    return HKEXIssuerProfile(
        expected, name, str(quote.get("nm_s") or "").strip(), summary,
        industry, subsector, str(quote.get("csic_classification") or "").strip(),
        str(quote.get("listing_category") or "").strip(),
        str(quote.get("primary_market") or "").strip(),
        str(quote.get("incorpin") or "").strip(),
        str(quote.get("db_updatetime") or "").strip(),
        make_hkex_quote_page_url(expected, "zh-HK"), status,
    )


def collect_hkex_issuer_profiles(
    stock_codes: Iterable[str], fetch_text: Callable[[str], str] | None = None,
) -> tuple[list[HKEXIssuerProfile], dict[str, str]]:
    codes = [normalize_hkex_profile_code(item) for item in stock_codes]
    if not codes:
        return [], {}
    fetch = fetch_text or _fetch_text
    token = parse_hkex_access_token(fetch(make_hkex_quote_page_url(codes[0], "zh-HK")))
    profiles = []
    raw_payloads = {}
    for index, code in enumerate(codes, 1):
        params = urllib.parse.urlencode({
            "sym": str(int(code[:5])), "token": token, "lang": "chi",
            "qid": index, "callback": "aegisHKEX",
        })
        payload = fetch(f"{HKEX_QUOTE_API}?{params}")
        profiles.append(parse_hkex_quote_payload(payload, code))
        raw_payloads[code] = payload
    return profiles, raw_payloads


def write_hkex_issuer_profiles(
    output_path: str | Path, raw_output_path: str | Path,
    profiles: Iterable[HKEXIssuerProfile], raw_payloads: dict[str, str],
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(HKEXIssuerProfile.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in profiles)
    raw_output = Path(raw_output_path)
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps({
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "api_url": HKEX_QUOTE_API,
        "payloads": raw_payloads,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_hkex_evidence_drafts(
    profiles_path: str | Path, universe: Iterable[object], mapping_path: str | Path,
    evidence_date: str,
) -> tuple[list[HKEXEvidenceDraft], dict]:
    with Path(profiles_path).open(encoding="utf-8-sig", newline="") as stream:
        profile_rows = list(csv.DictReader(stream))
    if not profile_rows or not set(HKEXIssuerProfile.__annotations__).issubset(profile_rows[0]):
        raise ValueError("港交所发行人资料字段不完整")
    mapping_config = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
    version = str(mapping_config.get("version") or "").strip()
    mappings = mapping_config.get("exact_sub_sector_mappings")
    if not version or not isinstance(mappings, dict):
        raise ValueError("港股行业映射配置缺少版本或精确映射")
    try:
        datetime.strptime(evidence_date, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("证据日期必须为YYYY-MM-DD") from error
    companies = {getattr(item, "stock_code"): item for item in universe}
    seen: set[str] = set()
    drafts = []
    date_token = evidence_date.replace("-", "")
    for row in profile_rows:
        code = normalize_hkex_profile_code(row["stock_code"])
        if code in seen:
            raise ValueError(f"港交所发行人资料证券代码重复: {code}")
        seen.add(code)
        company = companies.get(code)
        if company is None or not getattr(company, "included"):
            raise ValueError(f"港交所发行人资料未匹配纳入候选: {code}")
        subsector = row["hsic_sub_sector"].strip()
        proposed = str(mappings.get(subsector) or "").strip()
        mapped = bool(proposed)
        rationale = (
            f"港交所官方公司简介及恒生子行业“{subsector}”精确映射至“{proposed}”，待审核人核验并签名"
            if mapped else f"港交所恒生子行业“{subsector or '空'}”无精确能源映射，必须人工复核公司简介"
        )
        drafts.append(HKEXEvidenceDraft(
            f"DRAFT-HKEX-{date_token}-{code[:5]}", f"DRAFT-HKEX-{date_token}",
            "upsert", "", code, "include" if mapped else "", proposed,
            getattr(company, "entity_id"), row["source_url"].strip(), evidence_date,
            "", "", rationale, "proposed" if mapped else "manual_review",
            row["chinese_name"].strip(), row["chinese_short_name"].strip(),
            row["hsic_industry"].strip(), subsector, row["company_summary"].strip(), version,
        ))
    drafts.sort(key=lambda item: (item.review_status != "manual_review", item.stock_code))
    counts = Counter(item.review_status for item in drafts)
    summary = {
        "profile_count": len(profile_rows),
        "draft_count": len(drafts),
        "mapping_version": version,
        "review_status_counts": dict(sorted(counts.items())),
        "proposed_count": counts["proposed"],
        "manual_review_count": counts["manual_review"],
        "signed_count": 0,
        "applicable": False,
    }
    return drafts, summary


def write_hkex_evidence_drafts(
    output_path: str | Path, summary_path: str | Path,
    drafts: Iterable[HKEXEvidenceDraft], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(HKEXEvidenceDraft.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in drafts)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_hkex_quote_page_url(stock_code: str, language: str) -> str:
    code = normalize_hkex_profile_code(stock_code)
    return f"{HKEX_QUOTE_PAGE}?sc_lang={language}&sym={int(code[:5])}"


def normalize_hkex_profile_code(value: str) -> str:
    match = re.search(r"(?<!\d)(\d{1,5})(?:\.HK)?", value.strip().upper())
    if not match:
        raise ValueError(f"无效港股证券代码: {value}")
    return f"{match.group(1).zfill(5)}.HK"


def _fetch_text(url: str) -> str:
    # The widget host rejects browser-like cross-host Referer headers, while its
    # public JSONP endpoint accepts the same minimal request used by curl.
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code != 403:
            raise
        result = subprocess.run(
            ["curl", "-fsSL", url], check=True, capture_output=True, timeout=60,
        )
        return result.stdout.decode("utf-8")
