from __future__ import annotations

import re
import unicodedata
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .models import Observation, ValueStatus


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


@dataclass(frozen=True)
class ExtractionRule:
    indicator_code: str
    pattern: re.Pattern[str]
    unit_factors: dict[str, float]
    confidence: float = 0.82


@dataclass(frozen=True)
class DirectRule:
    indicator_code: str
    pattern: re.Pattern[str]
    factor: float
    confidence: float


@dataclass(frozen=True)
class EnglishRevenueIntensityRule:
    indicator_code: str
    pattern: re.Pattern[str]
    confidence: float = .9


@dataclass(frozen=True)
class ReviewSummary:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    candidate_count: int
    distinct_values: str
    source_pages: str
    recommended_value: str
    review_reason: str


@dataclass(frozen=True)
class StatementFact:
    values: tuple[float, ...]
    page: int
    evidence: str


NUMBER = r"([+-]?[\d,]+(?:\.\d+)?)"


def _rule(code: str, label: str, units: str, factors: dict[str, float], confidence: float = .82) -> ExtractionRule:
    return ExtractionRule(
        code,
        re.compile(r"(?:" + label + r")" + r"[^\d%]{0,35}" + NUMBER + r"\s*(" + units + r")", re.I),
        factors,
        confidence,
    )


RULES = (
    _rule("Q_E_GHG_INTENSITY", r"(?:温室气体|碳)排放强度", r"千克(?:二氧化碳当量|CO2e)?/万元|吨(?:二氧化碳当量|CO2e)?/万元", {"千克/万元": 1, "吨/万元": 1000}),
    _rule("Q_E_ENERGY_INTENSITY", r"(?:综合)?能源(?:消耗|消费)强度", r"千克标准煤\s*/\s*万元(?:营收|营业收入)?|吨标准煤\s*/\s*万元(?:营收|营业收入)?", {"千克标准煤/万元": 1, "千克标准煤/万元营收": 1, "千克标准煤/万元营业收入": 1, "吨标准煤/万元": 1000, "吨标准煤/万元营收": 1000, "吨标准煤/万元营业收入": 1000}),
    _rule("Q_E_NOX_INTENSITY", r"(?:氮氧化物|NOx)排放强度", r"克/万元|千克/万元", {"克/万元": 1, "千克/万元": 1000}),
    _rule("Q_E_SO2_INTENSITY", r"(?:二氧化硫|SO2)排放强度", r"克/万元|千克/万元", {"克/万元": 1, "千克/万元": 1000}),
    _rule("Q_E_WATER_INTENSITY", r"水资源(?:使用|消耗)强度", r"千克/万元|吨/万元|立方米/万元", {"千克/万元": 1, "吨/万元": 1000, "立方米/万元": 1000}),
    _rule("Q_E_SOLID_WASTE_INTENSITY", r"一般固体废物排放强度", r"千克/万元|吨/万元", {"千克/万元": 1, "吨/万元": 1000}),
    _rule("Q_S_SAFETY_INVEST_RATE", r"安全生产投入占营业收入(?:的)?比例|安全生产投入(?:占比|比例)", r"%|％", {"%": 1, "％": 1}),
    _rule("Q_S_RD_RATE", r"(?:研发(?:费用|投入)(?:占比|比例)|研发投入强度)", r"%|％", {"%": 1, "％": 1}),
    _rule("Q_G_DEBT_ASSET_RATE", r"资产负债率", r"%|％", {"%": 1, "％": 1}, .9),
)


DIRECT_RULES = (
    DirectRule(
        "Q_G_DEBT_ASSET_RATE",
        re.compile(
            r"(?:the\s+)?ratio\s+of\s+total\s+liabilities\s+to\s+total\s+assets"
            r"(?:\s+of\s+the\s+(?:Group|Company))?\s+(?:was|is)\s+(?:approximately\s+)?"
            + NUMBER + r"\s*%", re.I,
        ),
        1.0,
        .96,
    ),
    DirectRule(
        "Q_S_DONATION_RATE",
        re.compile(
            r"Proportion\s+of\s+(?:the\s+)?donation\s+total\s+in\s+revenue"
            r"[^\d%]{0,20}" + NUMBER + r"\s*%", re.I,
        ),
        1.0,
        .94,
    ),
    DirectRule(
        "Q_E_ALTERNATIVE_WATER_RATE",
        re.compile(
            r"(?:Percentage|Proportion)\s+of\s+(?:the\s+)?recycled\s+water(?:\s+consumption)?"
            r"[^\d%]{0,40}" + NUMBER + r"\s*%", re.I,
        ),
        1.0,
        .93,
    ),
    DirectRule(
        "Q_S_SAFETY_INVEST_RATE",
        re.compile(
            r"Proportion\s+of\s+(?:work|production)\s+safety\s+investment\s+to\s+"
            r"(?:operating\s+)?revenue\s*%?\s*" + NUMBER, re.I,
        ),
        1.0,
        .94,
    ),
    DirectRule(
        "Q_S_SAFETY_INVEST_RATE",
        re.compile(
            r"Work\s+safety\s+investment\s+as\s*%\s+of\s*%\s*" + NUMBER +
            r"(?:\s+[\d,.]+){0,4}\s+revenue", re.I,
        ),
        1.0,
        .94,
    ),
    DirectRule(
        "Q_S_SAFETY_INVEST_RATE",
        re.compile(
            r"Proportion\s+of\s+(?:(?:work|production)\s+safety|safety\s+production)\s+investment"
            r"\s*\d{0,2}\s*%\s*(?:/|–|—|-)?\s*" + NUMBER, re.I,
        ),
        1.0,
        .94,
    ),
    DirectRule(
        "Q_S_SAFETY_INVEST_RATE",
        re.compile(
            r"安全生产投入占营业收入(?:的)?比例\s*[：:]?\s*" + NUMBER + r"\s*[%％]",
        ),
        1.0,
        .94,
    ),
    DirectRule(
        "Q_S_SAFETY_INVEST_RATE",
        re.compile(
            r"安全生产投入占营业收入(?:的)?比例\s*\n\s*" + NUMBER + r"\s*[%％]",
        ),
        1.0,
        .94,
    ),
    DirectRule(
        "Q_S_DIVIDEND_PER_SHARE",
        re.compile(r"(?<!final )(?<!interim )(?<!proposed )Dividend\s+per\s+share\s*\(\s*RMB\s+cents?\s*\)[^\d]{0,20}" + NUMBER, re.I),
        .01,
        .95,
    ),
    DirectRule(
        "Q_S_DIVIDEND_PER_SHARE",
        re.compile(r"(?<!final )(?<!interim )(?<!proposed )Dividend\s+per\s+share\s*\(\s*RMB\s*\)[^\d]{0,20}" + NUMBER, re.I),
        1.0,
        .95,
    ),
    DirectRule(
        "Q_S_DIVIDEND_PER_SHARE",
        re.compile(
            r"total\s+dividend\s+per\s+share\s+for\s+the\s+whole\s+year\s+"
            r"(?:amounts?|amounting)\s+to\s+RMB\s*" + NUMBER, re.I,
        ),
        1.0,
        .96,
    ),
    DirectRule(
        "Q_S_DIVIDEND_PER_SHARE",
        re.compile(
            r"Cash\s+Dividend\s+per\s+Share(?:\s*\([^)]*\))?\s+RMB\s*/\s*share\s*" + NUMBER,
            re.I,
        ),
        1.0,
        .95,
    ),
    DirectRule(
        "Q_S_RD_RATE",
        re.compile(
            r"(?:proportion\s+of\s+)?R&D(?:\s+investment)?\s+intensity\s+"
            r"(?:was|reached|to)\s*" + NUMBER + r"\s*%", re.I,
        ),
        1.0,
        .93,
    ),
    DirectRule(
        "Q_S_RD_RATE",
        re.compile(r"研发投入总额占营业收入比例\s*\(\s*%\s*\)\s*" + NUMBER, re.I),
        1.0,
        .96,
    ),
    DirectRule(
        "Q_S_RD_RATE",
        re.compile(r"研发投入占营业收入的比例\s*\(\s*%\s*\)\s*" + NUMBER, re.I),
        1.0,
        .96,
    ),
    DirectRule(
        "Q_S_RD_RATE",
        re.compile(r"研发投入占营业收入(?:的)?比例\s*" + NUMBER + r"\s*%", re.I),
        1.0,
        .96,
    ),
    DirectRule(
        "Q_G_ROE",
        # 分隔符排除正负号与括号：负号必须由NUMBER捕获；(1)等小节编号、M1等公式变量不得误作数值
        re.compile(r"加权平均净资产收益\s*率(?:\s*[（(]\s*%[）)])?[^\d（(+-]{0,20}(?<![A-Za-z])" + NUMBER, re.I),
        1.0,
        .92,
    ),
    DirectRule(
        "Q_S_DIVIDEND_PER_SHARE",
        re.compile(r"每\s*10\s*股\s*派息数(?:\s*\(元\))?(?:\s*\(含税\))?[^\d]{0,15}" + NUMBER, re.I),
        .1,
        .94,
    ),
)


_REVENUE_DENOMINATOR = (
        r"(?:/|per)\s*"
        r"(?:(?P<scale1>thousand|million|billion|100\s+million|10[,.]?000|1[,.]?000|10k|’000|'000)\s*(?:RMB|CNY|HKD|HK\$)"
        r"|(?:RMB|CNY|HKD|HK\$)\s*(?P<scale2>thousand|million|billion|100\s+million|10[,.]?000|1[,.]?000|10k|’000|'000))"
        r"(?:\s+(?:(?:of|in)\s+)?revenue)?\s*\)?"
)
_GHG_LABEL = (
    r"(?:total\s+)?(?:GHG|greenhouse\s+gas)\s+emissions?\s+(?:intensity|density)"
    r"(?:\s*\(\s*Scopes?\s*1\s*(?:and|&|\+)\s*(?:Scopes?\s*)?2\s*\))?"
)
_GHG_NUMERATOR = r"(?P<numerator>kg\s*CO2-?e|tCO2-?e|tonnes?(?:\s+of)?\s+CO2(?:\s+equivalents?|-?e)?)"
_MASS_NUMERATOR = r"(?P<numerator>kg|kilograms?|tonnes?|tons?)"
_SOLID_WASTE_LABEL = r"(?:total\s+)?non-hazardous\s+waste(?:\s+(?:generation|production|disposal|emission))?\s+intensity(?:Note\d+)?"
_HAZ_WASTE_LABEL = r"(?<!non-)hazardous\s+waste(?:\s+(?:generation|production|disposal|emission|discharge))?\s+intensity(?:Note\d+)?"
_WASTEWATER_LABEL = r"(?:wastewater|sewage)(?:\s+(?:discharge|emission))?\s+intensity(?:Note\d+)?"
_PM_LABEL = r"(?:(?:particulate(?:\s+matter)?|PM)\s+emissions?\s+intensity|intensity\s+of\s+(?:particulate(?:\s+matter)?|PM)\s+emissions?)"
_SO2_LABEL = (
    r"(?:(?:SO2|SOx|sulphur\s+(?:dioxide|oxides?)|sulfur\s+(?:dioxide|oxides?))"
    r"\s+emissions?\s+intensity|intensity\s+of\s+"
    r"(?:SO2|SOx|sulphur\s+(?:dioxide|oxides?)|sulfur\s+(?:dioxide|oxides?))\s+emissions?)"
)
ENGLISH_REVENUE_INTENSITY_RULES = (
    EnglishRevenueIntensityRule(
        "Q_E_ENERGY_INTENSITY",
        re.compile(
            r"comprehensive\s+energy\s+intensity\s+per\s+unit\s+of\s+revenue\s+was\s+"
            r"(?P<value>[\d,]+(?:\.\d+)?)\s*(?P<numerator>tonnes?)\s+of\s+"
            r"standard\s+coal(?:\s+equivalent)?\s+per\s+RMB\s+"
            r"(?P<scale>100\s+million|million|10[,.]?000|10k)\s+of\s+revenue", re.I,
        ),
        .95,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_GHG_INTENSITY",
        re.compile(
            _GHG_LABEL + r"[^\d]{0,100}?" + _GHG_NUMERATOR + r"\s*" +
            _REVENUE_DENOMINATOR + r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .92,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_NOX_INTENSITY",
        re.compile(
            r"(?:intensity\s+of\s+NOx\s+emissions|NOx\s+emissions?\s+intensity)"
            r"[^\d]{0,80}?" + _MASS_NUMERATOR + r"\s*" + _REVENUE_DENOMINATOR +
            r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_NOX_INTENSITY",
        re.compile(
            r"(?:intensity\s+of\s+NOx\s+emissions|NOx\s+emissions?\s+intensity)"
            r"[^\d]{0,80}?" + _MASS_NUMERATOR +
            r"\s*(?:/|per)\s*(?P<scale>million|billion|100\s+million|10[,.]?000|10k)\s*"
            r"(?:RMB|CNY)(?:\s+(?:in\s+)?revenue|\s+revenue)?\s*"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_SO2_INTENSITY",
        re.compile(
            _SO2_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR + r"\s*" + _REVENUE_DENOMINATOR +
            r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_SO2_INTENSITY",
        re.compile(
            _SO2_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR +
            r"\s*(?:/|per)\s*(?P<scale>million|billion|100\s+million|10[,.]?000|10k)\s*"
            r"(?:RMB|CNY|Yuan)(?:\s+(?:in\s+)?revenue|\s+(?:of\s+)?revenue)?\s*"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_PM_INTENSITY",
        re.compile(
            _PM_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR + r"\s*" +
            _REVENUE_DENOMINATOR + r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_PM_INTENSITY",
        re.compile(
            _PM_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR +
            r"\s*(?:/|per)\s*(?P<scale>million|billion|100\s+million|10[,.]?000|10k)\s*"
            r"(?:RMB|CNY|Yuan)(?:\s+(?:in\s+)?revenue|\s+(?:of\s+)?revenue)?\s*"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_WASTEWATER_INTENSITY",
        re.compile(
            _WASTEWATER_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR +
            r"\s*(?:/|per)\s*(?P<scale>million|billion|100\s+million|10[,.]?000|10k)\s*"
            r"(?:RMB|CNY|Yuan)(?:\s+(?:in\s+)?revenue|\s+(?:of\s+)?revenue)?\s*"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_HAZ_WASTE_INTENSITY",
        re.compile(
            _HAZ_WASTE_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR + r"\s*" +
            _REVENUE_DENOMINATOR + r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_HAZ_WASTE_INTENSITY",
        re.compile(
            _HAZ_WASTE_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR +
            r"\s*(?:/|per)\s*(?P<scale>million|billion|100\s+million|10[,.]?000|10k)\s*"
            r"(?:RMB|CNY|Yuan)(?:\s+(?:in\s+)?revenue|\s+(?:of\s+)?revenue)?\s*"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_SOLID_WASTE_INTENSITY",
        re.compile(
            _SOLID_WASTE_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR + r"\s*" +
            _REVENUE_DENOMINATOR + r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_SOLID_WASTE_INTENSITY",
        re.compile(
            _SOLID_WASTE_LABEL + r"[^\d]{0,80}?" + _MASS_NUMERATOR +
            r"\s*(?:/|per)\s*(?P<scale>million|billion|100\s+million|10[,.]?000|10k)\s*"
            r"(?:RMB|CNY|Yuan)(?:\s+(?:in\s+)?revenue|\s+(?:of\s+)?revenue)?\s*"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .91,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_GHG_INTENSITY",
        re.compile(
            _GHG_LABEL + r"[^\d]{0,100}?" + _GHG_NUMERATOR +
            r"\s*(?:/|per)\s*(?P<scale>million|billion|100\s+million|10[,.]?000|10k)\s*"
            r"(?:RMB|CNY)(?:\s+(?:of\s+)?revenue|\s+revenue)?\s*"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .92,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_GHG_INTENSITY",
        re.compile(
            _GHG_LABEL + r"[^\d]{0,100}?" + _GHG_NUMERATOR +
            r"\s*(?:/|per)\s*revenue\s+of\s+(?:RMB|CNY)\s+(?:in\s+)?"
            r"(?P<scale>thousand|million|billion)\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        .92,
    ),
    EnglishRevenueIntensityRule(
        "Q_E_ENERGY_INTENSITY",
        re.compile(
            r"(?:comprehensive|total)\s+energy\s+consumption\s+intensity"
            r"[^\d]{0,100}?(?P<numerator>kg|kilograms?|tonnes?)\s+(?:of\s+)?"
            r"(?:standard\s+)?coal\s+equivalent\s*" + _REVENUE_DENOMINATOR +
            r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
    ),
    EnglishRevenueIntensityRule(
        "Q_E_CLEAN_ENERGY_INTENSITY",
        re.compile(
            r"(?:clean|renewable|green)\s+energy\s+(?:consumption|production|use)\s+intensity"
            r"[^\d]{0,100}?(?P<numerator>kg|kilograms?|tonnes?)\s+(?:of\s+)?"
            r"(?:standard\s+)?coal\s+equivalent\s*" + _REVENUE_DENOMINATOR +
            r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
    ),
    EnglishRevenueIntensityRule(
        "Q_E_WATER_INTENSITY",
        re.compile(
            r"(?:total\s+)?water\s+consumption\s+intensity"
            r"[^\d]{0,100}?(?P<numerator>kg|kilograms?|tonnes?|cubic\s+metres?|m3)\s*" +
            _REVENUE_DENOMINATOR + r"\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
    ),
    EnglishRevenueIntensityRule(
        "Q_E_ENERGY_INTENSITY",
        re.compile(
            r"(?:comprehensive|total)\s+energy\s+consumption\s+intensity[^\d]{0,30}"
            r"(?P<value>[\d,]+(?:\.\d+)?)\s*"
            r"(?P<numerator>kg|kilograms?|tonnes?)\s+(?:of\s+)?(?:standard\s+)?"
            r"coal\s+equivalent\s*" + _REVENUE_DENOMINATOR, re.I,
        ),
    ),
    EnglishRevenueIntensityRule(
        "Q_E_WATER_INTENSITY",
        re.compile(
            r"(?:total\s+)?water\s+consumption\s+intensity[^\d]{0,30}"
            r"(?P<value>[\d,]+(?:\.\d+)?)\s*"
            r"(?P<numerator>kg|kilograms?|tonnes?|cubic\s+metres?|m3)\s*" +
            _REVENUE_DENOMINATOR, re.I,
        ),
    ),
    EnglishRevenueIntensityRule(
        "Q_E_GHG_INTENSITY",
        re.compile(
            _GHG_LABEL + r"[^\d]{0,30}(?P<value>[\d,]+(?:\.\d+)?)\s*" +
            _GHG_NUMERATOR + r"\s*" + _REVENUE_DENOMINATOR, re.I,
        ),
        .92,
    ),
)


def extract_pdf_text(path: str | Path) -> list[PageText]:
    try:
        import fitz  # type: ignore
    except ImportError as error:
        raise RuntimeError("PDF抽取需要安装可选依赖: pip install '.[pdf]'") from error
    document = fitz.open(str(path))
    return [PageText(index + 1, page.get_text("text")) for index, page in enumerate(document)]


def read_page_text_export(path: str | Path) -> list[PageText]:
    """Read the deterministic page-marked text format produced by extraction adapters."""
    content = Path(path).read_text(encoding="utf-8")
    parts = re.split(r"\n=== PAGE (\d+) ===\n", content)
    if len(parts) < 3:
        raise ValueError(f"未识别到PDF页码标记: {path}")
    return [PageText(int(parts[index]), parts[index + 1]) for index in range(1, len(parts), 2)]


def resolve_text_export_path(text_root: str | Path, row: dict[str, str]) -> Path | None:
    """Map a document-index row to its page-marked txt under ``text_root``.

    Supports both research layout (``data/text/<code>/<year>/``) and CI layout
    (``data/text/ci_collection/<code>/<year>/``), including absolute ``local_path``
    values written by some collectors.
    """
    text_root = Path(text_root)
    local = Path(row.get("local_path") or "")
    code = (row.get("company_code") or "").strip()
    year = str(row.get("report_year") or "").strip()
    stem_name = local.with_suffix(".txt").name if local.name else ""
    if not code or not year or not stem_name:
        return None
    candidates = [
        text_root / code / year / stem_name,
        text_root / "ci_collection" / code / year / stem_name,
    ]
    try:
        relative = local.relative_to("data/raw")
        candidates.append((text_root / relative).with_suffix(".txt"))
        if relative.parts[:1] == ("ci_collection",):
            candidates.append((text_root / Path(*relative.parts[1:])).with_suffix(".txt"))
    except ValueError:
        pass
    parts = local.parts
    if len(parts) >= 3:
        candidates.append(text_root / parts[-3] / parts[-2] / stem_name)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def extract_batch_text_exports(
    document_index: str | Path,
    text_root: str | Path,
    report_year: int | None = None,
) -> tuple[list[Observation], dict[str, dict[str, int]]]:
    from .env_intensity import (
        CompanyDocument, derive_env_intensity_candidates, derive_ghg_reduction_candidates,
    )
    from .social_invest import derive_social_invest_candidates

    candidates: list[Observation] = []
    candidate_counts: Counter[str] = Counter()
    company_coverage: dict[str, set[str]] = defaultdict(set)
    text_root = Path(text_root)
    with Path(document_index).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    companies: dict[tuple[str, int], list[tuple[dict, list[PageText]]]] = defaultdict(list)
    for row in rows:
        if report_year is not None and int(row["report_year"]) != report_year:
            continue
        text_path = resolve_text_export_path(text_root, row)
        if text_path is None:
            continue
        pages = read_page_text_export(text_path)
        companies[(row["company_code"], int(row["report_year"]))].append((row, pages))
    for (company_code, year), documents in sorted(companies.items()):
        company_candidates: list[Observation] = []
        company_documents: list[CompanyDocument] = []
        for row, pages in documents:
            items = extract_indicator_candidates(
                pages, row["company_code"], row["company_name"],
                int(row["report_year"]), row["source_url"], row["local_path"],
            )
            company_candidates.extend(items)
            company_documents.append(CompanyDocument(
                row["document_type"], pages, row["source_url"], row["local_path"],
            ))
        derived = derive_env_intensity_candidates(
            company_code, documents[0][0]["company_name"], year, company_documents,
            frozenset(item.indicator_code for item in company_candidates),
        )
        company_candidates.extend(derived)
        derived_social = derive_social_invest_candidates(
            company_code, documents[0][0]["company_name"], year, company_documents,
            frozenset(item.indicator_code for item in company_candidates),
        )
        company_candidates.extend(derived_social)
        derived_reduction = derive_ghg_reduction_candidates(
            company_code, documents[0][0]["company_name"], year, company_documents,
            frozenset(item.indicator_code for item in company_candidates),
        )
        company_candidates.extend(derived_reduction)
        candidates.extend(company_candidates)
        candidate_counts.update(item.indicator_code for item in company_candidates)
        for item in company_candidates:
            company_coverage[item.indicator_code].add(item.company_code)
    coverage = {
        code: {"candidate_count": candidate_counts[code], "company_count": len(companies)}
        for code, companies in sorted(company_coverage.items())
    }
    return candidates, coverage


def summarize_review_candidates(candidates: list[Observation]) -> list[ReviewSummary]:
    groups: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    for item in candidates:
        groups[(item.company_code, item.report_year, item.indicator_code)].append(item)
    result = []
    for key, items in sorted(groups.items()):
        values = sorted({round(float(item.value), 8) for item in items if item.value is not None})
        pages = sorted({item.source_page for item in items if item.source_page is not None})
        agreed = len(values) == 1
        result.append(ReviewSummary(
            company_code=key[0], company_name=items[0].company_name, report_year=key[1],
            indicator_code=key[2], candidate_count=len(items),
            distinct_values="|".join(f"{value:g}" for value in values),
            source_pages="|".join(str(page) for page in pages),
            recommended_value=f"{values[0]:g}" if agreed else "",
            review_reason="single_or_consistent" if agreed else "conflicting_candidates",
        ))
    return result


def extract_indicator_candidates(
    pages: list[PageText],
    company_code: str,
    company_name: str,
    report_year: int,
    source_url: str,
    source_file: str,
) -> list[Observation]:
    candidates: list[Observation] = []
    seen = set()
    summary_pages: set[int] = set()
    for index, page in enumerate(pages):
        if _is_summary_section_page(page.text):
            summary_pages.add(page.page)
            if "营业收入" not in page.text and index + 1 < len(pages):
                summary_pages.add(pages[index + 1].page)
    for page_index, page in enumerate(pages):
        text = _normalize(page.text)
        for rule in RULES:
            for match in rule.pattern.finditer(text):
                if _is_contextual_false_positive(rule.indicator_code, text, match):
                    continue
                raw_number, raw_unit = match.group(1), match.group(2)
                canonical_unit = _canonical_unit(raw_unit)
                factor = rule.unit_factors.get(canonical_unit)
                if factor is None:
                    continue
                value = float(raw_number.replace(",", "")) * factor
                if not _plausible_value(rule.indicator_code, value):
                    continue
                identity = (rule.indicator_code, page.page, value)
                if identity in seen:
                    continue
                seen.add(identity)
                start, end = max(0, match.start() - 45), min(len(text), match.end() + 45)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=rule.indicator_code, value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=text[start:end], confidence=rule.confidence,
                ))
        for value, evidence in _extract_revenue_growth(page.text, page.page in summary_pages):
            identity = ("Q_G_REVENUE_GROWTH", page.page, value)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(Observation(
                company_code=company_code, company_name=company_name, report_year=report_year,
                indicator_code="Q_G_REVENUE_GROWTH", value=value, status=ValueStatus.PENDING,
                source_url=source_url, source_file=source_file, source_page=page.page,
                evidence_text=evidence, confidence=.91,
            ))
        for rule in DIRECT_RULES:
            for match in rule.pattern.finditer(text):
                if _is_direct_false_positive(rule.indicator_code, text, match):
                    continue
                value = float(match.group(1).replace(",", "")) * rule.factor
                if not _plausible_value(rule.indicator_code, value):
                    continue
                identity = (rule.indicator_code, page.page, value)
                if identity in seen:
                    continue
                seen.add(identity)
                start, end = max(0, match.start() - 45), min(len(text), match.end() + 45)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=rule.indicator_code, value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=text[start:end], confidence=rule.confidence,
                ))
        rd_table = _extract_chinese_rd_rate_year_table(page.text, report_year)
        if rd_table:
            value, evidence = rd_table
            identity = ("Q_S_RD_RATE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_S_RD_RATE", value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=evidence, confidence=.97,
                ))
        alternative_water = _extract_alternative_water_rate(page.text, report_year)
        if alternative_water:
            value, evidence = alternative_water
            identity = ("Q_E_ALTERNATIVE_WATER_RATE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_E_ALTERNATIVE_WATER_RATE", value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.96,
                ))
        for code, value, evidence, confidence in _extract_english_revenue_intensities(text):
            identity = (code, page.page, round(value, 8))
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(Observation(
                company_code=company_code, company_name=company_name, report_year=report_year,
                indicator_code=code, value=value, status=ValueStatus.PENDING,
                source_url=source_url, source_file=source_file, source_page=page.page,
                evidence_text=evidence, confidence=confidence,
            ))
        reduction = _extract_english_ghg_reduction(page.text, report_year)
        if reduction:
            value, evidence = reduction
            identity = ("Q_E_GHG_REDUCTION_RATE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_E_GHG_REDUCTION_RATE", value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.93,
                ))
        cn_reduction = _extract_chinese_ghg_reduction_direct(page.text, report_year)
        if cn_reduction:
            value, evidence = cn_reduction
            identity = ("Q_E_GHG_REDUCTION_RATE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_E_GHG_REDUCTION_RATE", value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.94,
                ))
        env_investment = _extract_english_env_investment_rate(text, report_year)
        if env_investment:
            value, evidence = env_investment
            identity = ("Q_S_ENV_INVEST_RATE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_S_ENV_INVEST_RATE", value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.94,
                ))
        for code, value, evidence in _extract_english_current_first_environmental_table(page.text, report_year):
            identity = (code, page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=code, value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.95,
                ))
        for code, value, evidence in _extract_english_current_first_direct_rows(page.text, report_year):
            identity = (code, page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=code, value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=evidence, confidence=.95,
                ))
        for code, value, evidence in _extract_english_current_first_standard_coal_rows(
            page.text, report_year,
        ):
            identity = (code, page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=code, value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=evidence, confidence=.96,
                ))
        for code, value, evidence in _extract_english_current_year_interleaved_rows(page.text, report_year):
            identity = (code, page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=code, value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=evidence, confidence=.95,
                ))
        for code, value, evidence in _extract_english_yuan_current_first_rows(page.text, report_year):
            identity = (code, page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=code, value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=evidence, confidence=.95,
                ))
        for code, value, evidence in _extract_chinese_env_table_rows(page.text, report_year):
            identity = (code, page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code=code, value=value, status=ValueStatus.PENDING,
                    source_url=source_url, source_file=source_file, source_page=page.page,
                    evidence_text=evidence, confidence=.9,
                ))
        pay_per_employee = _extract_english_pay_per_employee(text, report_year)
        if pay_per_employee:
            value, evidence = pay_per_employee
            identity = ("Q_S_PAY_PER_EMPLOYEE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_S_PAY_PER_EMPLOYEE", value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.95,
                ))
        transposed_context = (pages[page_index - 1].text if page_index > 0 else "") + page.text
        transposed_roe = _extract_weighted_roe_transposed(page.text, transposed_context)
        if transposed_roe:
            value, evidence = transposed_roe
            identity = ("Q_G_ROE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_G_ROE", value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.94,
                ))
        summary_roe = _extract_summary_roe_row(page.text)
        if summary_roe:
            value, evidence = summary_roe
            identity = ("Q_G_ROE", page.page, round(value, 8))
            if identity not in seen:
                seen.add(identity)
                candidates.append(Observation(
                    company_code=company_code, company_name=company_name, report_year=report_year,
                    indicator_code="Q_G_ROE", value=value,
                    status=ValueStatus.PENDING, source_url=source_url, source_file=source_file,
                    source_page=page.page, evidence_text=evidence, confidence=.94,
                ))
    for code, value, source_page, evidence in _extract_balance_sheet_indicators(pages):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.94,
        ))
    for code, value, source_page, evidence in _extract_english_balance_sheet_indicators(pages):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.94,
        ))
    for code, value, source_page, evidence in _extract_income_cash_indicators(pages):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.94,
        ))
    for code, value, source_page, evidence in _extract_english_income_indicators(pages):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.93,
        ))
    for code, value, source_page, evidence in _extract_collapsed_english_income_rows(pages):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.95,
        ))
    for code, value, source_page, evidence in _extract_english_cashflow_indicators(pages):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.93,
        ))
    for code, value, source_page, evidence in _extract_english_employee_per_capita(pages, report_year):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.95,
        ))
    for code, value, source_page, evidence in _extract_chinese_employee_per_capita(pages):
        identity = (code, source_page, round(value, 8))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=source_url, source_file=source_file, source_page=source_page,
            evidence_text=evidence, confidence=.95,
        ))
    for code in ("Q_G_ROE", "Q_S_RD_RATE"):
        direct = [
            item for item in candidates
            if item.indicator_code == code and not item.evidence_text.startswith(_FALLBACK_PREFIX)
        ]
        if direct:
            candidates = [
                item for item in candidates
                if item.indicator_code != code or not item.evidence_text.startswith(_FALLBACK_PREFIX)
            ]
    return candidates


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("（", "(").replace("）", ")")


def _extract_chinese_rd_rate_year_table(text: str, report_year: int) -> tuple[float, str] | None:
    """Read an R&D/revenue percentage only when an explicit year header maps the row columns."""
    header = re.search(r"(?m)^\s*[^\n]*(?:20\d{2}\s*年?[^\n]*){2,}\s*$", text)
    row = re.search(
        r"(?m)^\s*研发(?:投入|费用)(?:总额)?占营业收入(?:的)?(?:比例|比率)\s*%\s*(?P<body>[^\n]+)$",
        text,
    )
    if not header or not row:
        return None
    years = [int(item) for item in re.findall(r"20\d{2}", header.group(0))]
    values = [float(item.replace(",", "")) for item in re.findall(r"[+-]?[\d,]+(?:\.\d+)?", row.group("body"))]
    if (
        report_year not in years or len(values) != len(years)
        or re.search(r"20\d{2}\s*[-—–至]\s*20\d{2}", header.group(0))
    ):
        return None
    value = values[years.index(report_year)]
    if not 0 <= value <= 100:
        return None
    evidence = re.sub(r"\s+", " ", header.group(0) + " | " + row.group(0)).strip()
    return value, "中文研发占收比显式年份表: " + evidence


def _extract_alternative_water_rate(text: str, report_year: int) -> tuple[float, str] | None:
    """Read group/company alternative-water rates without treating site KPIs as group KPIs."""
    if re.search(r"(?:基地|厂区|园区)\s*(?:ESG\s*)?指标绩效", text, re.I):
        return None
    narrative_patterns = (
        rf"(?:{report_year}\s*年[^。；;\n]{{0,30}})?(?:公司[^。；;\n]{{0,20}})?"
        r"(?:整体)?替代水源(?:使用|用水量)?占比(?:达到|达|为)\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        rf"(?:{report_year}\s*年[^。；;\n]{{0,40}})?(?:公司[^。；;\n]{{0,20}})?"
        r"循环水用量占比(?:达到|达|为)?\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        # 中水回用/使用占比；排除“中水电”装机占比碰撞
        r"水循环利用率\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"中水(?!电)回用率(?:达到|达|为)?\s*(?:\d{1,2}\s+)?(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"中水(?!电)使用占比(?:达到|达|为)\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"再生水(?:使用|用水量)?占比(?:达到|达|为)\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"再生水利用率(?:达到|达|为)?\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"回用水占比(?:达到|达|为)?\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"水资源循环利用率(?:达到|达|为)?\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"非常规水源占\s*总取水量比例\s*%\s*[\s\S]{0,200}?(?P<value>[\d,]+(?:\.\d+)?)(?=\s*\n)",
        r"循环用水量(?:为|达到|：|:)?\s*[\d,]+(?:\.\d+)?\s*万?吨[^。；;\n]{0,20}?占总取水量\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"回用水量(?:为|达到|：|:)?\s*[\d,]+(?:\.\d+)?\s*万?吨[^。；;\n]{0,20}?占总取水量\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"水资源(?:循环|回用)利用(?:率|量)[^。；;\n]{0,30}?占总取水量\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"替代性水源占总耗水量(?:的|为)?\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"替代水源占总耗水量(?:的|为)?\s*(?P<value>[\d,]+(?:\.\d+)?)\s*%",
        r"(?:the\s+)?(?:Group|Company)['’]s?[^.\n]{0,80}?(?:recycled|reused|alternative)\s+water"
        r"[^.\n]{0,120}?account(?:ed|ing)\s+for\s+(?P<value>[\d,]+(?:\.\d+)?)\s*%\s+of\s+"
        r"total\s+water\s+(?:withdrawal|consumption|use)",
        r"alternative\s+water\s+sources\s+accounted\s+for\s+(?P<value>[\d,]+(?:\.\d+)?)\s*%\s+of\s+total\s+water\s+(?:withdrawal|consumption|use)",
    )
    for pattern in narrative_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = float(match.group("value").replace(",", ""))
            if 0 <= value <= 100:
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                return value, "Alternative-water direct group rate: " + evidence[:260]

    # Horizontal explicit-year KPI tables, including a numeric footnote after the label.
    mode = _chinese_year_table_mode(text, report_year)
    if mode is None:
        header = r"(?:指标|项目|披露项|披露指标)(?:名称)?\s*单位"
        year_cell = r"\s*年?(?:数据|数值|值)?"
        if re.search(rf"{header}\s*{report_year}{year_cell}\s*{report_year - 1}{year_cell}", text):
            mode = "current-first"
        elif re.search(rf"{header}\s*(?:20\d{{2}}{year_cell}\s*){{1,2}}{report_year}{year_cell}", text):
            mode = "current-last"
    if mode in {"current-first", "current-last"}:
        label = r"(?:替代水源(?:使用|用水量)?占比|循环水用量占比|中水回用利用率|水资源循环利用率)\d*"
        match = re.search(rf"(?m)^\s*(?:{label})\s*%\s*(?P<body>[-—/\d,.\s]+)$", text)
        if match:
            values = re.findall(r"[+-]?[\d,]+(?:\.\d+)?", match.group("body"))
            if len(values) < 2:
                values = []
            value = float((values[0] if mode == "current-first" else values[-1]).replace(",", "")) if values else -1
            if 0 <= value <= 100:
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                return value, "Alternative-water explicit-year table: " + evidence[:260]

    # A recurring PDF layout renders the two years, unit and values vertically.
    if re.search(rf"水资源利用指标\s*{report_year - 1}\s*年\s*单位\s*{report_year}\s*年", text):
        match = re.search(
            r"替代水源(?:使用|用水量)?占比\d*\s*\n\s*%\s*\n\s*"
            r"[\d,]+(?:\.\d+)?\s*\n\s*(?P<current>[\d,]+(?:\.\d+)?)",
            text,
        )
        if match:
            value = float(match.group("current").replace(",", ""))
            if 0 <= value <= 100:
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                return value, "Alternative-water explicit-year vertical table: " + evidence[:260]
    # 年序两值行：同文档出现“上年→本年”锚点后按最后一值取本年（真实样例：300919.SZ）
    for label in (r"中水回用利用率", r"水资源循环利用率"):
        anchor = re.search(
            rf"(?m)^\s*(?:{label})\d*\s*%\s*(?:[-—]\s+)?[\d,]+(?:\.\d+)?\s+[\d,]+(?:\.\d+)?\s*$",
            text,
        )
        if not anchor:
            continue
        match = re.search(
            rf"(?m)^\s*(?:{label})\d*\s*%\s*(?:[-—]\s+)?[\d,]+(?:\.\d+)?\s+"
            rf"(?P<current>[\d,]+(?:\.\d+)?)\s*$",
            text,
        )
        if not match:
            continue
        value = float(match.group("current").replace(",", ""))
        if 0 <= value <= 100:
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return value, "Alternative-water two-value year-sequence row: " + evidence[:260]
    return None


def _canonical_unit(unit: str) -> str:
    if not unit:
        return ""
    compact = re.sub(r"\s+", "", unit.replace("二氧化碳当量", "").replace("CO2e", ""))
    return compact


def _extract_english_revenue_intensities(text: str) -> list[tuple[str, float, str, float]]:
    result = []
    scale_amounts = {
        "thousand": 1_000, "1,000": 1_000, "1000": 1_000, "’000": 1_000, "'000": 1_000,
        "10,000": 10_000, "10000": 10_000, "million": 1_000_000,
        "10k": 10_000, "100 million": 100_000_000, "billion": 1_000_000_000,
    }
    for rule in ENGLISH_REVENUE_INTENSITY_RULES:
        for match in rule.pattern.finditer(text):
            numerator = match.group("numerator").lower()
            compact_numerator = re.sub(r"\s+", "", numerator)
            scale = match.groupdict().get("scale1") or match.groupdict().get("scale2") or match.groupdict().get("scale3") or match.groupdict().get("scale") or ""
            scale = re.sub(r"\s+", " ", scale.lower())
            amount = scale_amounts.get(scale)
            if amount is None:
                continue
            mass_kg = 1 if compact_numerator in {"kg", "kilogram", "kilograms", "kgco2e", "kgco2-e"} else 1_000
            raw_group = match.groupdict().get("value")
            if raw_group is None:
                continue
            raw_value = float(raw_group.replace(",", ""))
            if raw_value <= 0:
                continue
            # Reject target/goal statements like "Not exceeding X"
            full_match = match.group(0)
            if re.search(r"(?:not\s+exceeding|target|goal|aim\s+to|strive\s+to)", full_match, re.I):
                continue
            value = raw_value * mass_kg * 10_000 / amount
            if rule.indicator_code in {"Q_E_NOX_INTENSITY", "Q_E_SO2_INTENSITY", "Q_E_PM_INTENSITY"}:
                value *= 1_000
            if not _plausible_value(rule.indicator_code, value):
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()[:300]
            result.append((rule.indicator_code, value, "English revenue intensity: " + evidence, rule.confidence))
    return result


def _extract_english_ghg_reduction(text: str, report_year: int) -> tuple[float, str] | None:
    previous_year = report_year - 1
    narrative = re.search(
        rf"(?i)\bIn\s+{report_year}\b[^.\n]{{0,100}}?\b(?:the\s+)?Group['’]s\s+total\s+"
        rf"(?:GHG|greenhouse\s+gas)\s+emissions?\s+(?:declined|decreased|fell)\s+by\s+"
        rf"(?P<value>[\d,]+(?:\.\d+)?)\s*%\s+year-on-year",
        text,
    )
    if narrative:
        value = float(narrative.group("value").replace(",", ""))
        if 0 <= value <= 100:
            evidence = re.sub(r"\s+", " ", narrative.group(0)).strip()
            return value, "English total-GHG YoY direct: " + evidence

    ascending_header = re.search(
        rf"(?mi)^\s*[^\n]*\b{previous_year}\b[^\n]{{0,30}}\b{report_year}\b\s*$",
        text,
    )
    if ascending_header:
        ascending_row = re.search(
            r"(?mi)^\s*(?:"
            r"Total\s+(?:GHG|greenhouse\s+gas)\s+emissions?(?:\s*\(\s*Scope\s*1\s*(?:and|&|\+)\s*(?:Scope\s*)?2\s*\))?"
            r"|(?:GHG|greenhouse\s+gas)\s+emissions?\s*\(\s*Scope\s*1\s*(?:and|&|\+)\s*(?:Scope\s*)?2\s*\)"
            r")\s*"
            r"(?:tCO[₂2](?:e|-e)?|tonnes?\s+(?:of\s+)?CO2e|Equivalent\s+of\s+carbon\s+dioxide\s+in\s+tonnes)\s+"
            r"(?P<body>[^\n]+)$",
            text,
        )
        if ascending_row:
            year_columns = [int(year) for year in re.findall(r"20\d{2}", ascending_header.group(0))]
            metric_body = re.sub(
                r"\(?[+-]?[\d,]+(?:\.\d+)?\s*%\)?", "", ascending_row.group("body"),
            )
            values = [
                float(raw.replace(",", "")) for raw in
                re.findall(r"[\d,]+(?:\.\d+)?", metric_body)
            ]
            pair = None
            if len(year_columns) == 2 and len(values) >= 2:
                pair = values[1], values[0]
            elif len(year_columns) >= 3 and len(values) >= len(year_columns):
                pair = values[-1], values[-2]
            elif len(year_columns) >= 3 and len(values) == 2:
                pair = values[1], values[0]
            if pair and pair[1] > 0:
                current, previous = pair
                reduction = (previous - current) / previous * 100
                if -1000 <= reduction <= 100:
                    evidence = re.sub(r"\s+", " ", ascending_row.group(0)).strip()
                    return reduction, "English same-scope GHG table derived: " + evidence
    if not re.search(rf"\b{report_year}\b[^\n]{{0,40}}\b{previous_year}\b", text):
        return None
    row = re.compile(
        r"(?i)\bTotal\s+(?:(?:Scope\s*1\s*(?:and|&|\+)\s*(?:Scope\s*)?2\s*)?)"
        r"(?:GHG|greenhouse\s+gas)\s+emissions?"
        r"(?:\s*\(\s*Scope\s*1\s*(?:and|&|\+)\s*(?:Scope\s*)?2\s*\))?\s*"
        r"(?:tCO[₂2](?:e|-e)?|tonnes?\s+of\s+(?:carbon\s+dioxide\s+equivalent|CO2e)"
        r"|Equivalent\s+of\s+carbon\s+dioxide\s+in\s+tonnes)\s+"
        r"(?P<current>[\d,]+(?:\.\d+)?)\s+(?P<previous>[\d,]+(?:\.\d+)?)\b"
        r"(?!\s+[\d,]+(?:\.\d+)?)",
    )
    match = row.search(text)
    if not match:
        return None
    current = float(match.group("current").replace(",", ""))
    previous = float(match.group("previous").replace(",", ""))
    if current < 0 or previous <= 0:
        return None
    reduction = (previous - current) / previous * 100
    if not -1000 <= reduction <= 100:
        return None
    evidence = re.sub(r"\s+", " ", match.group(0)).strip()
    return reduction, "English same-scope GHG table derived: " + evidence


# 中文减排率直接披露：仅接受方法论口径（报告期同比、排放总量、公司实际值）的两种版式——
# 单年表头KPI表“同比下降 %”行与公司锚定“同比减少/下降X%”叙述；目标/峰值/累计/强度口径拒绝。
_CN_GHG_REDUCTION_NUM = r"[\d,]+(?:\.\d+)?"
_CN_GHG_REDUCTION_TABLE_ROW = re.compile(
    rf"(?m)^\s*温室气体排放(?:总量|总排放量)?(?:同比)?(?:下降|减少)(?:率)?\s*%\s*(?P<value>{_CN_GHG_REDUCTION_NUM})\s*$"
)
_CN_GHG_REDUCTION_NARRATIVE = re.compile(
    rf"(?:公司|本集团|集团)[\s\S]{{0,16}}?温室气体(?:排放总量|总排放量|排放量)[\s\S]{{0,8}}?"
    rf"同比(?:减少|下降)[\s\S]{{0,8}}?(?P<value>{_CN_GHG_REDUCTION_NUM})\s*%"
)
_CN_GHG_REDUCTION_BAD = re.compile(r"目标|计划|规划|力争|预计|预测|强度|密度|较|峰值|累计|净排放")


def _extract_chinese_ghg_reduction_direct(text: str, report_year: int) -> tuple[float, str] | None:
    """Read a directly disclosed YoY total-GHG reduction rate (strict layouts only)."""
    if _chinese_year_table_mode(text, report_year) == "single-year":
        match = _CN_GHG_REDUCTION_TABLE_ROW.search(text)
        if match:
            value = float(match.group("value").replace(",", ""))
            if 0 < value <= 100:
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                return value, "中文减排率直接披露: " + evidence
    for match in _CN_GHG_REDUCTION_NARRATIVE.finditer(text):
        span = match.group(0)
        if _CN_GHG_REDUCTION_BAD.search(span):
            continue
        if str(report_year) not in span and "报告期内" not in span and "本年度" not in span:
            continue
        value = float(match.group("value").replace(",", ""))
        if not 0 < value <= 100:
            continue
        evidence = re.sub(r"\s+", " ", span).strip()
        return value, "中文减排率直接披露: " + evidence
    return None


def _extract_english_env_investment_rate(text: str, report_year: int) -> tuple[float, str] | None:
    previous_year = report_year - 1
    patterns = (
        re.compile(
            rf"Proportion\s+of\s+environmental\s+protection\s+investment\d*\s+"
            rf"Unit\s+{previous_year}\s+%\s+(?:/|N/?A|-)\s+{report_year}\s+"
            r"(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
        re.compile(
            r"Proportion\s+of\s+environmental\s+protection\s+investment\s*"
            r"\(\s*%\s*\)\s*(?P<value>[\d,]+(?:\.\d+)?)\b", re.I,
        ),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        value = float(match.group("value").replace(",", ""))
        if 0 <= value <= 100:
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return value, "English environmental investment table: " + evidence
    return None


def _extract_english_clean_energy_intensity_table(
    text: str, report_year: int,
) -> tuple[float, str] | None:
    """Derive renewable-energy intensity only from one current-first, same-unit table."""
    previous_year = report_year - 1
    older_year = report_year - 2
    if not re.search(
        rf"(?i)Indicator\s+Unit\s+{report_year}\s+{previous_year}\s+{older_year}", text,
    ):
        return None
    number = r"([\d,]+(?:\.\d+)?)"
    renewable = re.search(
        rf"(?im)^\s*Renewable\s+energy\s+consumption\s+Tonnes?\s+of\s+standard\s+coal\s+"
        rf"(?P<current>{number})\s+{number}\s+{number}\s*$", text,
    )
    comprehensive = re.search(
        rf"(?im)^\s*Comprehensive\s+energy\s+consumption\s+Tonnes?\s+of\s+standard\s+coal\s+"
        rf"(?P<current>{number})\s+{number}\s+{number}\s*$", text,
    )
    intensity = re.search(
        rf"(?ims)^\s*Intensity\s+of\s+comprehensive\s+energy\s+consumption\s+"
        rf"Tonnes?\s+of\s+standard\s+coal\s*/\s*RMB\s+"
        rf"(?P<scale>billion|million|10\s*k|10,?000)\s+in\s+revenue\s+"
        rf"(?P<current>{number})\s+{number}\s+{number}\s*$", text,
    )
    if not renewable or not comprehensive or not intensity:
        return None
    renewable_total = float(renewable.group("current").replace(",", ""))
    comprehensive_total = float(comprehensive.group("current").replace(",", ""))
    comprehensive_raw_intensity = float(intensity.group("current").replace(",", ""))
    if renewable_total < 0 or comprehensive_total <= 0 or renewable_total > comprehensive_total:
        return None
    scale = re.sub(r"\s+", "", intensity.group("scale").lower()).replace(",", "")
    denominator = {"billion": 1_000_000_000, "million": 1_000_000, "10k": 10_000, "10000": 10_000}.get(scale)
    if denominator is None:
        return None
    comprehensive_value = comprehensive_raw_intensity * 1_000 * 10_000 / denominator
    value = comprehensive_value * renewable_total / comprehensive_total
    if not _plausible_value("Q_E_CLEAN_ENERGY_INTENSITY", value):
        return None
    evidence = (
        f"renewable={renewable.group(0).strip()} | comprehensive={comprehensive.group(0).strip()} | "
        f"intensity={intensity.group(0).strip()}"
    )
    return value, "English same-table renewable energy intensity derived: " + re.sub(r"\s+", " ", evidence)


def _extract_english_current_first_environmental_table(
    text: str, report_year: int,
) -> list[tuple[str, float, str]]:
    """Derive revenue intensities from one assured, current-first environmental table."""
    clean = _extract_english_clean_energy_intensity_table(text, report_year)
    previous_year, older_year = report_year - 1, report_year - 2
    if not re.search(rf"(?i)Indicator\s+Unit\s+{report_year}\s+{previous_year}\s+{older_year}", text):
        return []
    number = r"[\d,]+(?:\.\d+)?"
    total = re.search(
        rf"(?im)^\s*Comprehensive\s+energy\s+consumption\s+Tonnes?\s+of\s+standard\s+coal\s+"
        rf"(?P<current>{number})\s+{number}\s+{number}\s*$", text,
    )
    intensity = re.search(
        rf"(?ims)^\s*Intensity\s+of\s+comprehensive\s+energy\s+consumption\s+"
        rf"Tonnes?\s+of\s+standard\s+coal\s*/\s*RMB\s+"
        rf"(?P<scale>billion|million|10\s*k|10,?000)\s+in\s+revenue\s+"
        rf"(?P<current>{number})\s+{number}\s+{number}\s*$", text,
    )
    if not total or not intensity:
        return [("Q_E_CLEAN_ENERGY_INTENSITY", clean[0], clean[1])] if clean else []
    scale = re.sub(r"\s+", "", intensity.group("scale").lower()).replace(",", "")
    scale_amount = {"billion": 1_000_000_000, "million": 1_000_000, "10k": 10_000, "10000": 10_000}.get(scale)
    total_energy = float(total.group("current").replace(",", ""))
    raw_energy_intensity = float(intensity.group("current").replace(",", ""))
    if scale_amount is None or total_energy <= 0 or raw_energy_intensity <= 0:
        return []
    revenue_scale_units = total_energy / raw_energy_intensity
    revenue_rmb = revenue_scale_units * scale_amount
    if revenue_rmb <= 0:
        return []
    base_evidence = (
        f"revenue basis from {total.group(0).strip()} | {intensity.group(0).strip()}"
    )
    result: list[tuple[str, float, str]] = []
    energy_value = total_energy * 1_000 * 10_000 / revenue_rmb
    result.append((
        "Q_E_ENERGY_INTENSITY", energy_value,
        "English current-first environmental table derived: " + re.sub(r"\s+", " ", base_evidence),
    ))
    if clean:
        result.append(("Q_E_CLEAN_ENERGY_INTENSITY", clean[0], clean[1]))

    direct_rows = (
        ("Q_E_NOX_INTENSITY", r"Intensity\s+of\s+NOx\s+emissions", "g"),
        ("Q_E_WATER_INTENSITY", r"Intensity\s+of\s+water\s+consumption", "kg"),
        ("Q_E_HAZ_WASTE_INTENSITY", r"Intensity\s+of\s+hazardous\s+waste(?:\s+generation)?", "kg"),
        ("Q_E_SOLID_WASTE_INTENSITY", r"Intensity\s+of\s+non-hazardous\s+waste(?:\s+generation)?", "kg"),
    )
    for code, label, target_unit in direct_rows:
        row = re.search(
            rf"(?ims)^\s*{label}\s+Tonnes?\s*/\s*RMB\s+{re.escape(intensity.group('scale'))}"
            rf"\s+in\s+revenue\s+(?P<current>{number})\s+{number}\s+{number}\s*$", text,
        )
        if not row:
            continue
        raw = float(row.group("current").replace(",", ""))
        mass_factor = 1_000_000 if target_unit == "g" else 1_000
        value = raw * mass_factor * 10_000 / scale_amount
        if _plausible_value(code, value):
            result.append((
                code, value, "English current-first environmental table derived: " +
                re.sub(r"\s+", " ", row.group(0).strip()),
            ))

    total_rows = (
        ("Q_E_SO2_INTENSITY", r"Total\s+SO2\s+emissions", 1_000_000),
        ("Q_E_WASTEWATER_INTENSITY", r"Total\s+wastewater\s+discharge", 1_000),
    )
    for code, label, mass_factor in total_rows:
        row = re.search(
            rf"(?im)^\s*{label}\s+Tonnes?\s+(?P<current>{number})\s+{number}\s+{number}\s*$", text,
        )
        if not row:
            continue
        raw_total = float(row.group("current").replace(",", ""))
        value = raw_total * mass_factor * 10_000 / revenue_rmb
        if _plausible_value(code, value):
            result.append((
                code, value, "English current-first environmental table derived: " +
                re.sub(r"\s+", " ", row.group(0).strip() + " | " + base_evidence),
            ))
    return result


def _extract_english_current_first_direct_rows(
    text: str, report_year: int,
) -> list[tuple[str, float, str]]:
    """Read explicit methodology-compatible intensity rows under a current-first header."""
    previous_year, older_year = report_year - 1, report_year - 2
    if not re.search(rf"(?i)Indicator\s+Unit\s+{report_year}\s+{previous_year}\s+{older_year}", text):
        return []
    number = r"[\d,]+(?:\.\d+)?"
    rules = (
        ("Q_E_GHG_INTENSITY", r"Intensity\s+of\s+Scope\s*1\s*&\s*2\s+GHG\s+emissions", r"Ton(?:nes?)?\s*/\s*RMB\s+million", 10.0),
        ("Q_E_WATER_INTENSITY", r"Intensity\s+of\s+total\s+water\s+consumption", r"Ton(?:nes?)?\s*/\s*RMB\s+million", 10.0),
        ("Q_E_HAZ_WASTE_INTENSITY", r"Intensity\s+of\s+hazardous\s+waste", r"kg\s*/\s*RMB\s+million", .01),
        ("Q_E_SOLID_WASTE_INTENSITY", r"Intensity\s+of\s+non-hazardous\s+waste", r"kg\s*/\s*RMB\s+million", .01),
    )
    rows = []
    for code, label, unit, factor in rules:
        separator = rf"\s+{unit}" if unit else ""
        match = re.search(
            rf"(?ims)^\s*{label}{separator}\s+(?P<current>{number})\s+{number}\s+{number}\s*$", text,
        )
        if not match:
            continue
        value = float(match.group("current").replace(",", "")) * factor
        if not _plausible_value(code, value):
            continue
        rows.append((
            code, value, "English current-first direct intensity row: " +
            re.sub(r"\s+", " ", match.group(0).strip()),
        ))
    investment = re.search(
        rf"(?ims)^\s*Total\s+Environmental\s+protection\s+investment\s+%\s+"
        rf"(?P<current>{number})\s+{number}\s+{number}\s+as\s*%\s+of\s+revenue\s*$", text,
    )
    if investment:
        value = float(investment.group("current").replace(",", ""))
        if _plausible_value("Q_S_ENV_INVEST_RATE", value):
            rows.append((
                "Q_S_ENV_INVEST_RATE", value, "English current-first direct intensity row: " +
                re.sub(r"\s+", " ", investment.group(0).strip()),
            ))
    return rows


def _extract_english_current_first_standard_coal_rows(
    text: str, report_year: int,
) -> list[tuple[str, float, str]]:
    """Read explicit tce/water revenue intensities from a current-first resource table."""
    previous_year, older_year = report_year - 1, report_year - 2
    if not re.search(
        rf"(?is)Type\s+of\s+resources\s+Unit\s+{report_year}\s+{previous_year}\s+{older_year}",
        text,
    ):
        return []
    if not re.search(
        r"(?is)intensity\s+data\s+above\s+is\s+calculated\s+by\s+dividing\s+"
        r"consumption\s+volume\s+by\s+revenue",
        text,
    ):
        return []
    number = r"[\d,]+(?:\.\d+)?"
    rules = (
        (
            "Q_E_ENERGY_INTENSITY",
            r"Intensity\s+of\s+integrated\s+energy\s+Ton\s+of\s+standard\s+coal\s*/\s*"
            rf"(?P<current>{number})\s+{number}\s+{number}\s+consumption\s+RMB\s*10,?000",
            1_000.0,
        ),
        (
            "Q_E_WATER_INTENSITY",
            r"Intensity\s+of\s+freshwater\s+consumption\s+Recycling\s+rate\s+of\s+water\s+"
            r"for\s+industrial\s+use\s+Ton\s*/\s*RMB\s*10,?000\s+"
            rf"(?P<current>{number})\s+{number}\s+{number}\s+%",
            1_000.0,
        ),
    )
    result = []
    for code, pattern, factor in rules:
        match = re.search(rf"(?is){pattern}", text)
        if not match:
            continue
        value = float(match.group("current").replace(",", "")) * factor
        if _plausible_value(code, value):
            result.append((
                code, value, "English current-first revenue resource row: " +
                re.sub(r"\s+", " ", match.group(0).strip()),
            ))
    return result


def _extract_english_current_year_interleaved_rows(
    text: str, report_year: int,
) -> list[tuple[str, float, str]]:
    """Handle audited PDF column order only when the page explicitly identifies the year."""
    if not re.search(rf"(?i)Unit\s+Year\s+{report_year}", text):
        return []
    match = re.search(
        r"(?is)Total\s+discharge\s+of\s+non-hazardous\s+waste\s+Tons\s+Intensity\s+"
        r"Ton\s*/\s*ten\s+thousand\s+RMB\s+[\d,]+(?:\.\d+)?\s+revenue\s+"
        r"(?P<value>[\d,]+(?:\.\d+)?)", text,
    )
    if not match:
        return []
    value = float(match.group("value").replace(",", "")) * 1_000
    if not _plausible_value("Q_E_SOLID_WASTE_INTENSITY", value):
        return []
    return [(
        "Q_E_SOLID_WASTE_INTENSITY", value,
        "English current-year interleaved waste row: " + re.sub(r"\s+", " ", match.group(0).strip()),
    )]


def _extract_english_yuan_current_first_rows(
    text: str, report_year: int,
) -> list[tuple[str, float, str]]:
    """Read current-first Million Yuan rows with spelled-out environmental units."""
    if not re.search(rf"(?i)Indicator\s+Name(?:\s+Unit)?\s+{report_year}", text):
        return []
    number = r"[\d,]+(?:\.\d+)?"
    rules = (
        (
            "Q_E_GHG_INTENSITY",
            r"GHG\s+emissions\s+intensity\s*\(\s*Scope\s*1\s+and\s+Scope\s*2\s*\)",
            r"Tons?\s+of\s+Carbon\s+Dioxide\s+Equivalent\s+per\s+Million\s+Yuan\s+of\s+Revenue",
            10.0,
        ),
        (
            "Q_E_WATER_INTENSITY", r"Water\s+consumption\s+intensity",
            r"Tons?\s+per\s+Million\s+Yuan\s+of\s+Revenue", 10.0,
        ),
        (
            "Q_E_PM_INTENSITY", r"Particulate\s+emissions\s+intensity",
            r"Kg\s+per\s+Million\s+Yuan\s+of\s+Revenue", 10.0,
        ),
    )
    result = []
    for code, label, unit, factor in rules:
        match = re.search(
            rf"(?ims)^\s*{label}\s+{unit}\s+(?P<current>{number})\s+{number}\s+{number}\s*$", text,
        )
        if not match:
            continue
        value = float(match.group("current").replace(",", "")) * factor
        if _plausible_value(code, value):
            result.append((
                code, value, "English current-first Million Yuan row: " +
                re.sub(r"\s+", " ", match.group(0).strip()),
            ))
    return result


_CN_NUMBER = r"[\d,]+(?:\.\d+)?"

_CN_TABLE_RULES: tuple[tuple[str, str, tuple[tuple[str, float], ...]], ...] = (
    ("Q_E_GHG_INTENSITY", r"(?:单位营收)?温室气体排放(?:强度|密度)(?:\s*[（(]范围\s*[一1]\s*[、和+]\s*(?:范围\s*)?[二2]\s*[）)])?", (
        ("万吨二氧化碳当量/百万元营业收入", 100000.0), ("万吨二氧化碳当量/百万元营收", 100000.0),
        # 吨/百万元 → 千克/万元：×1000/100 = ×10（勿用×1000，否则放大百倍）
        ("吨二氧化碳当量/百万元营业收入", 10.0), ("吨二氧化碳当量/百万元营收", 10.0),
        ("吨二氧化碳当量/百万营收", 10.0), ("吨二氧化碳当量/百万元", 10.0),
        ("吨二氧化碳当量/万元", 1000.0), ("吨二氧化碳当量/万元营收", 1000.0),
        ("吨二氧化碳当量/万元营业收入", 1000.0),
        ("吨二氧化碳当量/万元人民币营业收入", 1000.0),
        ("吨二氧化碳当量/亿元", 0.1),
        ("千克二氧化碳当量/万元", 1.0), ("tCO2e/百万元", 10.0), ("tCO2e/万元", 1000.0),
        ("吨/万元", 1000.0), ("吨/百万元", 10.0), ("吨/亿元", 0.1),
    )),
    # 神华/宏发等：碳排放强度（吨二氧化碳当量 ╱ 万元收入）或（tCO2e/万元）
    ("Q_E_GHG_INTENSITY", r"碳排放强度", (
        ("吨二氧化碳当量/万元收入", 1000.0), ("吨二氧化碳当量/万元营收", 1000.0),
        ("吨二氧化碳当量/万元营业收入", 1000.0), ("吨二氧化碳当量/万元人民币营业收入", 1000.0),
        ("吨二氧化碳当量/万元", 1000.0),
        ("吨/万元收入", 1000.0), ("吨/万元营收", 1000.0), ("吨/万元", 1000.0),
        ("千克二氧化碳当量/万元", 1.0), ("tCO2e/万元", 1000.0), ("tCO₂e/万元", 1000.0),
    )),
    # 三峡能源等：营收碳强度 吨二氧化碳/万元人民币收入
    ("Q_E_GHG_INTENSITY", r"营收碳强度", (
        ("吨二氧化碳/万元人民币收入", 1000.0), ("吨二氧化碳当量/万元人民币收入", 1000.0),
        ("吨二氧化碳/万元收入", 1000.0), ("吨二氧化碳/万元营收", 1000.0),
        ("吨二氧化碳/万元", 1000.0), ("吨/万元人民币收入", 1000.0), ("吨/万元", 1000.0),
    )),
    # 绩效表常见“每百万营收温室气体排放总量 + 吨二氧化碳当量”隐含强度（吨/百万元→千克/万元×10）
    ("Q_E_GHG_INTENSITY", r"每百万营收温室气体排放总量(?:\s*[（(]\s*范围\s*[一1]\s*[、和+及]\s*范围\s*[二2]\s*[）)])?", (
        ("吨二氧化碳当量", 10.0), ("吨", 10.0), ("tCO2e", 10.0),
    )),
    # “单位营收温室气体排放量（基于位置） 吨二氧化碳当量/万元”
    ("Q_E_GHG_INTENSITY",
     r"单位营收温室气体排放(?:量|总量)(?:\s*[（(]\s*基于(?:位置|市场)\s*[）)])?", (
        ("吨二氧化碳当量/百万元", 10.0), ("吨二氧化碳当量/百万元营收", 10.0),
        ("吨二氧化碳当量/百万元营业收入", 10.0), ("吨/百万元", 10.0),
        ("吨二氧化碳当量/万元", 1000.0), ("吨二氧化碳当量/万元营收", 1000.0),
        ("吨二氧化碳当量/万元营业收入", 1000.0), ("吨/万元", 1000.0),
        ("千克二氧化碳当量/万元", 1.0), ("千克/万元", 1.0),
    )),
    ("Q_E_ENERGY_INTENSITY", r"(?:单位营收)?(?:综合)?能源(?:消耗|消费|使用)(?:强度|密度|量)|综合能耗强度|每百万营收综合能耗强度|能源使用强度", (
        ("万吨标准煤/百万元营业收入", 100000.0), ("万吨标准煤/百万元营收", 100000.0),
        ("吨标准煤/百万元营业收入", 10.0), ("吨标准煤/百万元营收", 10.0),
        ("吨标准煤/万元", 1000.0), ("吨标准煤/万元营收", 1000.0), ("吨标准煤/万元营业收入", 1000.0),
        ("吨标准煤/万元人民币营业收入", 1000.0), ("吨标煤/万元人民币营业收入", 1000.0),
        ("吨标煤/万元", 1000.0), ("吨标煤/万元营收", 1000.0), ("吨标煤/万元营业收入", 1000.0),
        ("吨标准煤/百万元", 10.0), ("吨标煤/百万元", 10.0), ("吨标煤/百万元营收", 10.0),
        ("吨标准煤/亿元", 0.1),
        ("千克标准煤/万元", 1.0), ("千克标准煤/万元营收", 1.0), ("千克标准煤/万元营业收入", 1.0),
        ("吉焦/百万元", 0.341208),
    )),
    # 绩效表：每百万营收综合能耗强度 + 吨标煤（隐含 /百万元）
    ("Q_E_ENERGY_INTENSITY", r"每百万营收综合能耗(?:强度|总量)|每百万营收能源消耗(?:强度|总量)|单位营收综合能源消耗量", (
        ("吨标准煤", 10.0), ("吨标煤", 10.0), ("千克标准煤", 0.01),
        ("吨标煤/百万元", 10.0), ("吨标准煤/百万元", 10.0),
    )),
    ("Q_E_WATER_INTENSITY", r"水资源(?:使用|消耗)强度|(?:单位营收)?(?:用水|耗水|取水)(?:强度|密度|量)", (
        ("吨/万元", 1000.0), ("吨/万元营收", 1000.0), ("吨/万元营业收入", 1000.0),
        ("吨/万元人民币营业收入", 1000.0),
        ("吨/百万元", 10.0), ("立方米/万元", 1000.0), ("立方米/万元营收", 1000.0),
        ("立方米/百万元", 10.0), ("千克/万元", 1.0),
    )),
    ("Q_E_SO2_INTENSITY", r"二氧化硫排放强度", (
        ("吨/万元", 1_000_000.0), ("吨/百万元", 10_000.0),
        ("吨/百万元营收", 10_000.0), ("吨/百万元营业收入", 10_000.0),
        ("千克/万元", 1000.0), ("千克/百万元", 10.0), ("克/万元", 1.0), ("克/百万元", 0.01),
    )),
    ("Q_E_NOX_INTENSITY", r"氮氧化物排放强度|每百万营收氮氧化物排放量", (
        ("千克/万元", 1000.0), ("千克/百万元", 10.0), ("克/万元", 1.0), ("克/百万元", 0.01),
        ("吨/万元", 1_000_000.0), ("吨/百万元", 10_000.0), ("吨", 10_000.0),
    )),
    ("Q_E_PM_INTENSITY", r"颗粒物排放强度", (
        ("千克/万元", 1000.0), ("千克/百万元", 10.0), ("克/万元", 1.0), ("克/百万元", 0.01),
    )),
    ("Q_E_WASTEWATER_INTENSITY", r"废水排放强度", (
        ("吨/万元", 1000.0), ("吨/百万元", 10.0), ("千克/万元", 1.0),
    )),
    # 无害废弃物产生强度仅走亮点卡 value-before-label，避免把下一指标的前置数值误挂到本标签后
    ("Q_E_SOLID_WASTE_INTENSITY", r"一般固体废物(?:排放|产生)?(?:强度|密度)|一般固废(?:排放|产生)?(?:强度|密度)|一般废弃物产生强度|单位营收(?:一般|无害)废弃物(?:产生|处置)?量", (
        ("吨/万元", 1000.0), ("吨/万元营收", 1000.0), ("吨/万元营业收入", 1000.0),
        ("吨/营收万元", 1000.0), ("吨/万元（年营业收入）", 1000.0), ("吨/百万元", 10.0),
        ("吨/百万元营收", 10.0), ("吨/百万元营业收入", 10.0), ("千克/万元", 1.0),
    )),
    # 桂冠电力等：每百万营收产生的无害废弃物总量 吨/百万元
    ("Q_E_SOLID_WASTE_INTENSITY", r"每百万营收产生的无害废弃物总量|每百万营收无害废弃物(?:产生)?总量", (
        ("吨/百万元", 10.0), ("吨/百万元营收", 10.0), ("吨", 10.0),
    )),
    # 华银电力等竖排：无害废弃物总量 + 吨/百万元（拒绝对质量单位“吨”以免误吃产生量）
    ("Q_E_SOLID_WASTE_INTENSITY", r"无害废弃物总量", (
        ("吨/百万元", 10.0), ("吨/百万元营收", 10.0), ("吨/百万元营业收入", 10.0),
    )),
    ("Q_E_HAZ_WASTE_INTENSITY", r"危险废物排放强度|危险废物产生强度|危废排放强度|(?:单位营收)?危险废物密度|危险废弃物(?:排放|产生)?(?:强度|密度)|每百万营收产生的有害废弃物总量|单位营收危险废物产生量", (
        ("吨/万元", 1000.0), ("吨/百万元", 10.0), ("吨/亿元人民币营业收入", 0.1),
        ("吨/万元收入", 1000.0), ("吨/万元营收", 1000.0), ("吨/营收万元", 1000.0),
        ("吨/万元人民币营业收入", 1000.0), ("吨/万元（年营业收入）", 1000.0),
        ("吨/百万元营收", 10.0),
        ("吨/百万元营业收入", 10.0), ("吨/百万营收", 10.0),
        ("吨/亿元营业收入", 0.1), ("吨/亿元", 0.1), ("千克/万元", 1.0),
    )),
    ("Q_S_ENV_INVEST_RATE", r"环保(?:总)?投入占营业收入(?:的)?比例|环境保护总投入占营业收入(?:的)?比例", (("%", 1.0),)),
    ("Q_S_SAFETY_INVEST_RATE", r"安全生产投入占营业收入(?:的)?比例", (("%", 1.0),)),
    ("Q_S_RD_RATE", r"研发投入占营业收入(?:的)?比例", (("%", 1.0),)),
    ("Q_S_DONATION_RATE", r"(?:对外)?捐赠(?:总额)?占营业收入(?:的)?比例", (("%", 1.0),)),
)


def _cn_unit_fragment(unit: str) -> str:
    if unit == "%":
        return r"[（(]?\s*[%％]\s*[）)]?"
    fragment = re.escape(unit).replace("/", r"\s*[／/╱]\s*")
    for prefix in ("吨二", "千克二", "吨标", "千克标"):
        if prefix in fragment:
            fragment = fragment.replace(prefix, prefix[:-1] + r"\s*" + prefix[-1])
    return fragment + r"(?!产)"


def _normalize_kangxi(text: str) -> str:
    chars = (
        unicodedata.normalize("NFKC", ch) if "\u2f00" <= ch <= "\u2fdf" else ch
        for ch in text.replace("\x00", " ")
    )
    return "".join(chars)


def _chinese_year_table_mode(text: str, report_year: int) -> str | None:
    """Detect the year-column layout of a Chinese KPI table from its explicit header."""
    previous_year = report_year - 1
    if re.search(
        rf"指标名称\s*指标单位\s*{previous_year}\s*年数值\s*{report_year}\s*年数值", text,
    ):
        return "current-last"
    # 废气污染物种类表常见“单位 + 上年数值 + 本年数值”（真实样例：000791.SZ）
    pollutant_header = r"(?:废气)?污染物种类\s*单位"
    if re.search(
        rf"{pollutant_header}\s*{previous_year}\s*年?(?:数据|数值|值)?\s*{report_year}\s*年?(?:数据|数值|值)?",
        text,
    ):
        return "current-last"
    if re.search(
        rf"{pollutant_header}\s*{report_year}\s*年?(?:数据|数值|值)?\s*{previous_year}\s*年?(?:数据|数值|值)?",
        text,
    ):
        return "current-first"
    if re.search(rf"{pollutant_header}\s*{report_year}\s*年?(?:数据|数值|值)?", text):
        return "single-year"
    header = r"(?:指标|项目|披露项|披露指标)(?:名称)?\s*单\s*位"
    if re.search(rf"{header}\s*{report_year}\s*年?\s*{previous_year}\s*年?", text):
        return "current-first"
    if re.search(rf"{header}\s*(?:20\d{{2}}\s*年?\s*){{1,2}}{report_year}\s*年?", text):
        return "current-last"
    if re.search(rf"{header}\s*{report_year}\s*年?(?:数据|数值|值)?", text):
        return "single-year"
    postfix_header = r"(?:指标|项目|类别|披露项|披露指标)(?:名称)?"
    if re.search(rf"{postfix_header}\s*{report_year}\s*年?\s*{previous_year}\s*年?\s*单\s*位", text):
        return "current-first"
    if re.search(rf"{postfix_header}\s*(?:20\d{{2}}\s*年?\s*){{1,2}}{report_year}\s*年?\s*单\s*位", text):
        return "current-last"
    if re.search(rf"{postfix_header}\s*{report_year}\s*年?\s*单\s*位", text):
        return "single-year"
    # 禾迈等竖排KPI卡：关键绩效 单位 2025年
    if re.search(rf"(?:关键绩效|环境绩效|责任绩效|环保绩效)\s*单\s*位\s*{report_year}\s*年?", text):
        return "single-year"
    # 三峡能源等：环保绩效 单位 2023 年 2024 年 2025 年
    if re.search(
        rf"(?:关键绩效|环境绩效|责任绩效|环保绩效)\s*单\s*位\s*(?:20\d{{2}}\s*年?\s*){{1,2}}{report_year}\s*年?",
        text,
    ):
        return "current-last"
    # 裸表头：单位 2023 2024 2025（同页气候指标卡）
    if re.search(rf"(?m)^\s*单\s*位\s*(?:20\d{{2}}\s*){{1,2}}{report_year}\s*$", text):
        return "current-last"
    # 神华等附录绩效表：一级指标 二级指标 2023年 2024年 2025年
    appendix_header = r"(?:一级指标\s*二级指标|指标\s*单\s*位|二级指标)"
    if re.search(
        rf"{appendix_header}\s*(?:20\d{{2}}\s*年?\s*){{1,2}}{report_year}\s*年?",
        text,
    ):
        return "current-last"
    # 华银电力等：指标 单位\n2023年 2024年 2025年（单位与年份可换行）
    if re.search(
        rf"指标\s*单\s*位\s*\n\s*(?:20\d{{2}}\s*年\s*){{1,2}}{report_year}\s*年",
        text,
    ):
        return "current-last"
    if re.search(
        rf"(?:20\d{{2}}\s*年\s+){{2}}{report_year}\s*年",
        text,
    ) and re.search(r"(?:碳排放总量|二氧化硫排放总量|氮氧化物排放总量|能源消费总量|总耗水量)", text):
        return "current-last"
    # 宏发等：统计项目 2023年 2024年 2025年
    if re.search(
        rf"(?:统计项目|指标项目|关键指标)\s*(?:20\d{{2}}\s*年?\s*){{1,2}}{report_year}\s*年?",
        text,
    ):
        return "current-last"
    # 竖排年份卡：单位\n2023年\n...\n2025年（禾望电气等）
    if re.search(
        rf"(?m)^\s*单位\s*\n(?:.*\n){{0,3}}^\s*{report_year - 2}\s*年\s*\n[\s\S]{{0,80}}^\s*{previous_year}\s*年\s*\n[\s\S]{{0,80}}^\s*{report_year}\s*年\s*$",
        text,
    ) and re.search(r"(?:温室气体|碳排放|能源|取水|用水)", text):
        return "current-last"
    return None


def _expand_scientific_notation(text: str) -> str:
    """Expand PDF scientific notation such as ``5.294× 10-3`` into decimals."""

    def _repl(match: re.Match[str]) -> str:
        base = float(match.group(1))
        exp = int(match.group(2))
        # 报表几乎总是写 10-n 表示 10^(-n)
        value = base * (10 ** (-exp))
        return f"{value:.12g}"

    return re.sub(
        r"(\d+(?:\.\d+)?)\s*[×xX]\s*10\s*[−\-﹣]?\s*(\d+)",
        _repl,
        text,
    )


def _collapse_spaced_cn_units(text: str) -> str:
    """Collapse PDF letter-spacing inside common Chinese intensity units/headers."""
    patterns = (
        r"吨\s*标\s*准\s*煤\s*/\s*百\s*万\s*元(?:\s*营\s*业\s*收\s*入|\s*营\s*收)?",
        r"吨\s*标\s*煤\s*/\s*百\s*万\s*元(?:\s*营\s*业\s*收\s*入|\s*营\s*收)?",
        r"吨\s*二\s*氧\s*化\s*碳\s*当\s*量\s*/\s*(?:万\s*元|百\s*万\s*元)(?:\s*营\s*业\s*收\s*入|\s*营\s*收)?",
        r"千克\s*标\s*准\s*煤\s*/\s*万\s*元(?:\s*营\s*业\s*收\s*入|\s*营\s*收)?",
        r"立\s*方\s*米\s*/\s*百\s*万\s*元(?:\s*营\s*业\s*收\s*入|\s*营\s*收)?",
    )
    repaired = text
    for pattern in patterns:
        repaired = re.sub(pattern, lambda m: re.sub(r"\s+", "", m.group(0)), repaired)
    # 表头“指标 单 位 / 环 境 绩 效”
    repaired = re.sub(r"指\s*标\s+单\s*位", "指标 单位", repaired)
    repaired = re.sub(r"单\s+位", "单位", repaired)
    repaired = re.sub(r"环\s*境\s*绩\s*效", "环境绩效", repaired)
    return repaired


def _repair_wrapped_cn_env_labels(text: str) -> str:
    """Join common PDF wraps in Chinese environmental KPI labels/units."""
    repairs = (
        (r"温室气体\s*\n\s*排放总量", "温室气体排放总量"),
        (r"温室气体\s*\n\s*排放强度", "温室气体排放强度"),
        (r"温室气体\s*\n\s*排放密度", "温室气体排放密度"),
        (r"吨二氧\s*\n\s*化碳当量", "吨二氧化碳当量"),
        (r"吨二氧化碳\s*\n\s*当量", "吨二氧化碳当量"),
        (r"吨二氧化碳当量\s*\n\s*/\s*\n\s*百万营收", "吨二氧化碳当量/百万营收"),
        (r"吨二氧化碳当量\s*/\s*\n\s*百万营收", "吨二氧化碳当量/百万营收"),
        (r"吨二氧化碳当量\s*\n\s*/\s*百万营收", "吨二氧化碳当量/百万营收"),
        (r"营收碳强度\s*吨二氧化碳\s*/\s*\n\s*万元人民币收入", "营收碳强度 吨二氧化碳/万元人民币收入"),
        (r"吨二氧化碳\s*/\s*\n\s*万元人民币收入", "吨二氧化碳/万元人民币收入"),
        (r"一般固体废物产生\s*\n\s*总量", "一般固体废物产生总量"),
        (r"一般固体废物排放\s*\n\s*密度", "一般固体废物排放密度"),
        (r"危险废物排放\s*\n\s*密度", "危险废物排放密度"),
        (r"每百万营收产生的\s*\n\s*有害废弃物总量", "每百万营收产生的有害废弃物总量"),
        (r"每百万营收产生的\s*\n\s*无害废弃物总量", "每百万营收产生的无害废弃物总量"),
        (r"吨/\s*\n\s*[（(]\s*年营业收入\s*[）)]", "吨/万元（年营业收入）"),
        (r"吨/\s*万元\s*\n\s*[（(]\s*年营业收入\s*[）)]", "吨/万元（年营业收入）"),
    )
    repaired = text
    for pattern, repl in repairs:
        repaired = re.sub(pattern, repl, repaired)
    return repaired


def _extract_chinese_env_table_rows(text: str, report_year: int) -> list[tuple[str, float, str]]:
    """Read methodology-compatible rows from Chinese KPI tables with explicit year headers."""
    text = _collapse_spaced_cn_units(
        _expand_scientific_notation(
            _repair_wrapped_cn_env_labels(_repair_wrapped_numbers(_normalize_kangxi(text)))
        )
    )
    mode = _chinese_year_table_mode(text, report_year)
    results: list[tuple[str, float, str]] = []
    for code, label, units in _CN_TABLE_RULES:
        factors = dict(units)
        # 较长单位优先，避免“吨/万元”抢先匹配“吨/万元（年营业收入）”
        unit_pattern = "(?:" + "|".join(
            f"(?:{_cn_unit_fragment(unit)})"
            for unit, _ in sorted(units, key=lambda item: len(item[0]), reverse=True)
        ) + ")"
        label_group = rf"(?:{label})(?:\s*注\s*\d+)?"
        patterns: list[tuple[str, str]] = []
        if mode == "current-first":
            patterns.append((
                "current-first",
                rf"^\s*{label_group}\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s+(?:{_CN_NUMBER}|/)(?:\s+(?:{_CN_NUMBER}|/))?\s*$",
            ))
            patterns.append((
                "current-first-postfix-unit",
                rf"^\s*{label_group}\s*(?P<current>{_CN_NUMBER})\s+(?:{_CN_NUMBER}|/)(?:\s+(?:{_CN_NUMBER}|/))?\s*(?P<unit>{unit_pattern})\s*$",
            ))
        elif mode == "current-last":
            patterns.append((
                "current-last",
                rf"^\s*{label_group}\s*(?P<unit>{unit_pattern})\s*{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*$",
            ))
            patterns.append((
                "current-last-postfix-unit",
                rf"^\s*{label_group}\s*{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})\s*$",
            ))
            # 标签括号带单位：碳排放强度（吨二氧化碳当量 ╱ 万元收入） 5.59 5.89 6.78
            patterns.append((
                "current-last-paren-unit",
                rf"^\s*{label_group}\s*[（(]\s*(?P<unit>{unit_pattern})\s*[）)]\s*"
                rf"{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*$",
            ))
            # 标签与单位分行：一般固体废物排放密度\n吨/万元（年营业收入） v1 v2 v3
            patterns.append((
                "current-last-label-newline-unit",
                rf"(?m)^\s*{label_group}\s*\n\s*(?P<unit>{unit_pattern})\s*"
                rf"{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*$",
            ))
            # 竖排三年值：标签\n(范围)\n单位\nv1\nv2\nv3（禾望电气等）
            patterns.append((
                "current-last-vertical-three",
                rf"(?m)^\s*{label_group}\s*(?:\n\s*[（(][^）\n]{{0,40}}[）)])?\s*\n\s*"
                rf"(?P<unit>{unit_pattern})\s*\n\s*"
                rf"{_CN_NUMBER}\s*\n\s*{_CN_NUMBER}\s*\n\s*(?P<current>{_CN_NUMBER})\s*$",
            ))
        elif mode == "single-year":
            patterns.append((
                "single-year",
                rf"^\s*{label_group}\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s*$",
            ))
            # 竖排KPI卡：标签\n单位\n数值（禾迈等）
            patterns.append((
                "single-year-vertical",
                rf"(?m)^\s*{label_group}\s*\n\s*(?P<unit>{unit_pattern})\s*\n\s*(?P<current>{_CN_NUMBER})\s*$",
            ))
        patterns.append((
            "row-year-suffix",
            rf"^\s*{label_group}\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})\s*{report_year}\s*年\s*$",
        ))
        # 无表头但仍是显式收入强度：标签\n单位 数值 或 标签\n数值\n单位
        if code in {
            "Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY",
            "Q_E_SO2_INTENSITY", "Q_E_NOX_INTENSITY", "Q_E_HAZ_WASTE_INTENSITY",
            "Q_E_SOLID_WASTE_INTENSITY", "Q_S_SAFETY_INVEST_RATE", "Q_S_RD_RATE",
            # Q_S_ENV_INVEST_RATE 常为亮点卡数值在前，避免标签后误吃下一指标百分比
        }:
            # 单值竖排：数值后不得再跟同年序列，避免把三年卡的首年误当本期
            patterns.append((
                "vertical-unit-value",
                rf"(?m)^\s*{label_group}\s*\n\s*(?P<unit>{unit_pattern})\s+(?P<current>{_CN_NUMBER})\s*"
                rf"(?!\n\s*{_CN_NUMBER})\s*$",
            ))
            patterns.append((
                "vertical-value-unit",
                rf"(?m)^\s*{label_group}\s*\n\s*(?P<current>{_CN_NUMBER})\s*\n\s*(?P<unit>{unit_pattern})\s*$",
            ))
            # 标签换行后数值与单位同行：综合能源消耗强度\n0.95吨标准煤/百万元营收
            patterns.append((
                "vertical-value-unit-same-line",
                rf"(?m)^\s*{label_group}\s*\n\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})\s*$",
            ))
            patterns.append((
                "vertical-unit-then-value",
                rf"(?m)^\s*{label_group}\s*\n\s*(?P<unit>{unit_pattern})\s*\n\s*(?P<current>{_CN_NUMBER})\s*"
                rf"(?!\n\s*{_CN_NUMBER})\s*$",
            ))
            # 安全/研发占比：标签\n0.06%
            if code in {"Q_S_SAFETY_INVEST_RATE", "Q_S_RD_RATE"}:
                patterns.append((
                    "vertical-percent",
                    rf"(?m)^\s*{label_group}\s*\n\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>[%％])\s*$",
                ))
            # 无表头时的竖排三年收入强度：取末列本期值
            if code in {
                "Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_NOX_INTENSITY",
                "Q_E_WATER_INTENSITY", "Q_E_SOLID_WASTE_INTENSITY", "Q_E_HAZ_WASTE_INTENSITY",
            } and mode is None:
                patterns.append((
                    "vertical-three-year-intensity",
                    rf"(?m)^\s*{label_group}\s*(?:\n\s*[（(][^）\n]{{0,40}}[）)])?\s*\n\s*"
                    rf"(?P<unit>{unit_pattern})\s*\n\s*"
                    rf"{_CN_NUMBER}\s*\n\s*{_CN_NUMBER}\s*\n\s*(?P<current>{_CN_NUMBER})\s*$",
                ))
            # 双栏拼版：标签后插入其他议题，再出现单位与三年值（帝尔激光）
            if code == "Q_E_ENERGY_INTENSITY":
                revenue_unit = (
                    r"(?:吨标准煤|吨标煤)\s*/\s*百万元(?:营收|营业收入)?"
                    r"|(?:千克标准煤)\s*/\s*万元(?:营收|营业收入)?"
                )
                patterns.append((
                    "interleaved-vertical-three",
                    rf"每百万营收综合能耗强度[\s\S]{{0,160}}?(?P<unit>{revenue_unit})\s*\n\s*"
                    rf"{_CN_NUMBER}\s*\n\s*{_CN_NUMBER}\s*\n\s*(?P<current>{_CN_NUMBER})\b",
                ))
        if code in {
            "Q_E_HAZ_WASTE_INTENSITY", "Q_E_NOX_INTENSITY", "Q_E_ENERGY_INTENSITY",
            "Q_E_SOLID_WASTE_INTENSITY", "Q_E_WATER_INTENSITY",
        } and mode is None:
            patterns.append((
                "single-value-revenue-unit",
                rf"^\s*{label_group}\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})\s*$",
            ))
            patterns.append((
                "single-unit-value-revenue",
                rf"^\s*{label_group}\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s*$",
            ))
        for pattern_mode, row in patterns:
            for match in re.finditer(row, text, re.M):
                unit_key = re.sub(r"\s+", "", match.group("unit"))
                unit_key = unit_key.replace("／", "/").replace("╱", "/")
                # 仅当整段被括号包裹时去壳；勿用 strip('（）')，否则会剥掉“吨/万元（年营业收入）”的右括号
                if (
                    (unit_key.startswith("（") and unit_key.endswith("）"))
                    or (unit_key.startswith("(") and unit_key.endswith(")"))
                ):
                    unit_key = unit_key[1:-1]
                factor = factors.get(unit_key)
                if factor is None:
                    continue
                nearby = text[max(0, match.start() - 24):min(len(text), match.end() + 24)]
                if code in {"Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY"} and re.search(
                    r"产值|产量|发电量|单位产品|万元产值", nearby,
                ):
                    continue
                value = float(match.group("current").replace(",", "")) * factor
                if not _plausible_value(code, value):
                    continue
                results.append((
                    code, value,
                    f"Chinese {pattern_mode} environmental table row: " + re.sub(r"\s+", " ", match.group(0)).strip(),
                ))
    # 去重：同一指标同一数值可能被横排与竖排模式各命中一次
    deduped: list[tuple[str, float, str]] = []
    seen: set[tuple[str, float]] = set()
    for code, value, evidence in results:
        key = (code, round(value, 6))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((code, value, evidence))
    results = deduped
    # Some ESG KPI tables split one pollutant into label / total / unit / value / intensity /
    # unit / value bands. Accept only an explicit report-year emissions-performance table and
    # the exact SO2 substance label; SOx and permit/target tables cannot enter this branch.
    if re.search(rf"(?:废气污染物(?:排放|减排)情况|污染物排放)[\s\S]{{0,120}}指标\s*单位\s*{report_year}\s*年", text):
        match = re.search(
            r"二氧化硫\s*\n\s*排放总量\s*\n\s*吨\s*\n\s*[\d,]+(?:\.\d+)?\s*\n\s*"
            r"排放强度\s*\n\s*吨\s*/\s*百万元(?:营收|营业收入)\s*\n\s*"
            r"(?P<current>[\d,]+(?:\.\d+)?)",
            text,
        )
        if match:
            value = float(match.group("current").replace(",", "")) * 10_000
            if _plausible_value("Q_E_SO2_INTENSITY", value):
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                results.append((
                    "Q_E_SO2_INTENSITY", value,
                    "Chinese explicit-year split pollutant intensity row: " + evidence[:260],
                ))
    results.extend(_extract_chinese_highlight_intensities(text))
    # 再次去重（亮点卡可能与表行重叠）
    deduped = []
    seen = set()
    for code, value, evidence in results:
        key = (code, round(value, 6))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((code, value, evidence))
    return deduped


def _extract_chinese_highlight_intensities(text: str) -> list[tuple[str, float, str]]:
    """亮点卡常见“数值 + 单位 + 换行标签”或双栏强度拼版。"""
    results: list[tuple[str, float, str]] = []

    def _add(code: str, raw: str, factor: float, evidence: str) -> None:
        value = float(raw.replace(",", "")) * factor
        if _plausible_value(code, value):
            results.append((
                code, value,
                "Chinese highlight intensity: " + re.sub(r"\s+", " ", evidence).strip()[:260],
            ))

    # 顺钠股份等：0.68 吨标煤/百万元\n单位营收综合能源消耗量
    highlight_rows = (
        (
            "Q_E_ENERGY_INTENSITY", 10.0,
            rf"(?P<current>{_CN_NUMBER})\s*(?:吨标准煤|吨标煤)\s*/\s*百万元(?:营收|营业收入)?\s*\n\s*"
            rf"单位营收(?:综合)?能源(?:消耗|消费)?(?:量|强度)?",
        ),
        (
            "Q_E_GHG_INTENSITY", 10.0,
            rf"(?P<current>{_CN_NUMBER})\s*(?:吨二氧化碳当量|吨CO2e|tCO2e)\s*/\s*百万元(?:营收|营业收入)?\s*\n\s*"
            rf"单位营收(?:温室气体|碳排放)(?:排放)?(?:量|强度)?",
        ),
        (
            "Q_E_WATER_INTENSITY", 10.0,
            rf"(?P<current>{_CN_NUMBER})\s*(?:立方米|吨|m³)\s*/\s*百万元(?:营收|营业收入)?\s*\n\s*"
            rf"单位营收(?:耗水|用水|取水)(?:量|强度)?",
        ),
        # 金冠电气等：数值在前的无害废弃物强度
        (
            "Q_E_SOLID_WASTE_INTENSITY", 10.0,
            rf"(?P<current>{_CN_NUMBER})\s*\n\s*吨\s*/\s*百万元\s*\n\s*营业收入\s*\n\s*"
            rf"(?:无害|一般)废弃物产生强度",
        ),
        (
            "Q_E_HAZ_WASTE_INTENSITY", 10.0,
            rf"(?P<current>{_CN_NUMBER})\s*\n\s*吨\s*/\s*百万元\s*\n\s*营业收入\s*\n\s*"
            rf"危险废弃物产生强度",
        ),
        # 水资源使用强度：总量行后的强度值在前
        (
            "Q_E_WATER_INTENSITY", 10.0,
            rf"(?P<current>{_CN_NUMBER})\s*\n\s*水资源使用强度\s*\n\s*吨\s*/\s*百万元",
        ),
        (
            "Q_S_ENV_INVEST_RATE", 1.0,
            rf"(?P<current>{_CN_NUMBER})\s*[%％]\s*\n\s*"
            rf"(?:环境保护总投入|环保(?:总)?投入)占营业收入(?:的)?比例",
        ),
    )
    for code, factor, pattern in highlight_rows:
        for match in re.finditer(pattern, text, re.M | re.I):
            _add(code, match.group("current"), factor, match.group(0))

    # 双栏亮点：GHG/能耗强度同组两值 + 分列单位标签（金冠电气）
    dual = re.search(
        rf"吨\s*二\s*氧\s*化\s*碳\s*当\s*量\s*/\s*\n\s*"
        rf"(?P<ghg>{_CN_NUMBER})\s+(?P<energy>{_CN_NUMBER})\s*\n\s*"
        rf"百万元营业收入\s*\n\s*温室气体排放强度\s+能源使用强度\s*\n\s*"
        rf"吨标准煤\s*/\s*(?:百万\s*\n\s*元营业收入|百万元(?:营业收入)?)",
        text,
    )
    if dual:
        _add("Q_E_GHG_INTENSITY", dual.group("ghg"), 10.0, dual.group(0))
        _add("Q_E_ENERGY_INTENSITY", dual.group("energy"), 10.0, dual.group(0))
    return results


def _extract_english_pay_per_employee(text: str, report_year: int) -> tuple[float, str] | None:
    pattern = re.compile(
        rf"As\s+(?:at|of)\s+31(?:st)?\s+December\s+{report_year},\s+the\s+Group\s+had\s+"
        r"(?P<employees>[\d,]+)\s+(?:full-time\s+)?employees\b.{0,300}?"
        r"(?:Total\s+)?staff\s+costs?\b.{0,100}?\b(?:amounted\s+to|was)\s+"
        r"RMB\s*(?P<cost>[\d,]+(?:\.\d+)?)\s+million\b",
        re.I,
    )
    match = pattern.search(text)
    if not match:
        return None
    employees = int(match.group("employees").replace(",", ""))
    cost_million = float(match.group("cost").replace(",", ""))
    if employees <= 0 or cost_million < 0:
        return None
    value = cost_million * 100 / employees
    if value > 1000:
        return None
    evidence = re.sub(r"\s+", " ", match.group(0)).strip()[:500]
    return value, "English same-group RMB staff cost derived: " + evidence


_WEIGHTED_ROE_ROW = re.compile(
    r"归\s*属\s*于\s*公\s*司\s*普\s*通\s*股\s*股\s*东\s*的\s*净\s*利\s*润\s*([+-]?[\d,]+(?:\.\d+)?)\s*%"
)
_WEIGHTED_ROE_SPLIT_ROW = re.compile(
    r"归\s*属\s*于\s*公\s*司\s*普\s*通\s*股\s*股\s*东\s*(?:的\s*净\s*)?"
    r"([+-]?[\d,]+(?:\.\d+)?)\s*%\s+[+-]?[\d.]+\s+[+-]?[\d.]+\s+(?:的\s*)?(?:净\s*)?利\s*润"
)


def _extract_weighted_roe_transposed(text: str, context: str) -> tuple[float, str] | None:
    """Read the exchange-mandated transposed ROE/EPS table (value carries an explicit % sign)."""
    if "加权平均净资产收益率" not in context:
        return None
    for pattern in (_WEIGHTED_ROE_ROW, _WEIGHTED_ROE_SPLIT_ROW):
        for match in pattern.finditer(text):
            prefix = re.sub(r"\s+", "", text[max(0, match.start() - 30):match.start()])
            if "扣除非经常" in prefix:
                continue
            value = float(match.group(1).replace(",", ""))
            if not -1000 <= value <= 1000:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return value, "加权平均净资产收益率转置表: " + evidence[:220]
    return None


_ROE_SUMMARY_LABEL = re.compile(
    r"加\s*权\s*平\s*均\s*净\s*资\s*产\s*"
    r"(?:[（(]\s*亏\s*损\s*[）)]\s*[/／]\s*)?"
    r"收\s*益\s*率\s*(?:[（(]\s*%\s*[）)]|%)?\s*"
    r"(?:[（(][^（）()]{0,60}?计\s*算\s*[）)]\s*)?"
)
_ROE_CELL = re.compile(
    r"\s*(?:"
    r"(?P<paren>\([+-]?[\d,]+(?:\.\d+)?\)\s*%?)"
    r"|(?P<pct>[+-]?[\d,]+(?:\.\d+)?\s*%)"
    r"|(?P<bare>[+-]?[\d,]+(?:\.\d+)?)"
    r"|(?P<na>不适用|\*|—|--|-)"
    r")"
)


def _extract_summary_roe_row(text: str) -> tuple[float, str] | None:
    """Read the ROE row of the exchange-mandated summary table (主要会计数据).

    Handles split labels across lines, parenthesized negatives, labels declaring
    the unit as （%）so cells omit the sign, and multi-line （依据…计算）notes.
    The current-year column is always first; a leading 不适用 cell means the
    current year is genuinely not applicable and yields no candidate.
    """
    for label in _ROE_SUMMARY_LABEL.finditer(text):
        before = re.sub(r"\s+", "", text[max(0, label.start() - 30):label.start()])
        if "扣除" in before:
            continue
        declared_percent = "%" in label.group(0)
        cells = []
        cursor = label.end()
        for _ in range(6):
            cell = _ROE_CELL.match(text, cursor)
            if not cell or cell.group(0).strip() == "":
                break
            token = cell.group(0).strip()
            cells.append((token, cell))
            cursor = cell.end()
        if not cells:
            continue
        first = cells[0][0]
        if first == "不适用":
            continue
        value: float | None = None
        for token, cell in cells:
            if cell.group("paren"):
                value = -float(cell.group("paren").strip("()% ").replace(",", ""))
                break
            if cell.group("pct"):
                value = float(cell.group("pct").rstrip("% ").replace(",", ""))
                break
            if cell.group("bare"):
                if not declared_percent:
                    break
                number = float(cell.group("bare").replace(",", ""))
                following = text[cell.end():cell.end() + 2]
                if following.strip().startswith("年") or abs(number) >= 1000:
                    break
                value = number
                break
            if token != "*":
                break
        if value is None or not -1000 <= value <= 1000:
            continue
        evidence = re.sub(r"\s+", " ", text[label.start():cursor]).strip()
        return value, "主要会计数据加权平均净资产收益率行: " + evidence[:240]
    return None


def _is_contextual_false_positive(code: str, text: str, match: re.Match[str]) -> bool:
    matched = match.group(0)
    if code in {"Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY"}:
        # A superscript footnote may appear between a table label and its unit, followed by
        # the actual current/prior-year values (e.g. "排放强度3 吨/万元 0.02 0.03").
        if re.match(r"\s*\d", text[match.end():match.end() + 12]):
            return True
        # Methodology denominator is consolidated operating revenue, not output/production value.
        nearby = text[max(0, match.start() - 24):min(len(text), match.end() + 24)]
        if re.search(r"产值|产量|发电量|单位产品|万元产值", nearby):
            return True
    if code == "Q_G_DEBT_ASSET_RATE":
        if any(token in matched for token in ("超过", "低于", "不低于", "不超过", "＝", "=")):
            return True
        nearby = text[max(0, match.start() - 18):min(len(text), match.end() + 18)]
        if "被担保对象" in nearby or "计算公式" in nearby:
            return True
    if code == "Q_S_RD_RATE":
        nearby = text[max(0, match.start() - 8):match.end()]
        if "产业研发" in nearby or "业务研发" in nearby or "超" in matched or "约" in matched:
            return True
    return False


def _plausible_value(code: str, value: float) -> bool:
    if code == "Q_G_ROE":
        # 亏损公司ROE合法为负；自由文本匹配保留正向上限，表格行抽取器才放宽到±1000
        return -1000 <= value <= 100
    if value < 0:
        return False
    percentage_codes = {
        "Q_E_ALTERNATIVE_WATER_RATE", "Q_S_SAFETY_INVEST_RATE", "Q_S_RD_RATE",
        "Q_S_DONATION_RATE", "Q_S_ENV_INVEST_RATE", "Q_G_DEBT_ASSET_RATE",
    }
    if code in percentage_codes and value > 100:
        return False
    if code == "Q_S_DIVIDEND_PER_SHARE" and value > 100:
        return False
    return True


def _is_direct_false_positive(code: str, text: str, match: re.Match[str]) -> bool:
    if code != "Q_G_ROE":
        return False
    before = text[max(0, match.start() - 18):match.start()]
    matched = match.group(0)
    if "扣除非经常性损益" in before:
        return True
    if any(token in matched for token in ("同比", "增加", "减少", "提升", "下降", "上升", "增长", "变动", "较上年", "不适用")):
        return True
    return False


def _extract_revenue_growth(raw_text: str, in_summary_section: bool = False) -> list[tuple[float, str]]:
    parsed = _extract_summary_revenue(raw_text, in_summary_section)
    if parsed is None:
        return []
    current, previous, evidence = parsed
    growth = (current - previous) / previous * 100
    return [(growth, evidence)] if -100 <= growth <= 1000 else []


_SUMMARY_SECTION_MARKERS = (
    "近三年主要会计数据",
    "主要会计数据和财务指标",
    "主要会计数据及财务指标",
    "会计数据和财务指标摘要",
    "按中国企业会计准则编制的主要财务数据",
)


def _is_summary_section_page(text: str) -> bool:
    return any(marker in text for marker in _SUMMARY_SECTION_MARKERS)


def _extract_summary_revenue(raw_text: str, in_summary_section: bool = False) -> tuple[float, float, str] | None:
    if not in_summary_section and not re.search(
        r"(?:近三年主要会计数据|[(（]一[)）]\s*主要会计数据|主要会计数据(?:和|及)财务指标|"
        r"会计数据和财务指标摘要|按中国企业会计准则编制的主要财务数据)",
        raw_text,
    ):
        return None
    repaired = _repair_wrapped_numbers(raw_text)
    number = re.compile(r"[+-]?[\d,]+(?:\.\d+)?")
    match = re.search(
        r"营业收入(?P<body>.{0,2000}?)(?:利润总额|营业利润|归属于母公司|归属于上市)",
        repaired,
        re.S,
    )
    if not match:
        return None
    evidence = "营业收入" + match.group("body")
    values = [float(item.replace(",", "")) for item in number.findall(evidence)]
    # 跳过同比增减百分比列夹在两年数值之间的情形：取前两个绝对值较大的会计金额
    if len(values) < 2:
        return None
    # 典型：营业收入 2,864,469 2,937,981 (2.5) 3,012,812 → 取前两列年度值
    current, previous = values[0], values[1]
    if previous == 0:
        return None
    if re.search(r"人民币\s*百万元|单位\s*[：:]\s*百万元(?:\s*币种\s*[：:]\s*人民币)?", raw_text):
        scale = 1_000_000
    elif re.search(r"人民币\s*千元|单位\s*[：:]\s*千元(?:\s*币种\s*[：:]\s*人民币)?", raw_text):
        scale = 1_000
    elif re.search(r"单位\s*[：:]\s*万元", raw_text):
        scale = 10_000
    else:
        scale = 1
    return current * scale, previous * scale, re.sub(r"\s+", " ", evidence)[:400]


def _repair_wrapped_numbers(raw_text: str) -> str:
    """Join PDF line-breaks that split thousand-separated numbers.

    Examples:
    - ``477,\\n044.50`` → ``477,044.50``
    - ``252,302.35 477\\n044.50`` → ``252,302.35 477,044.50``
    """
    repaired = re.sub(r"(?<=[\d,])\s*\n\s*(?=[.,])", "", raw_text)
    # Incomplete integer group + newline + exactly-3-digit continuation (with optional decimals).
    # Do not treat the fractional part of a decimal (e.g. 38.30\n191.85) as a thousand group.
    repaired = re.sub(
        r"(?<![,\d.])(\d{1,3})\s*\n\s*(\d{3}(?:\.\d+)?)\b",
        r"\1,\2",
        repaired,
    )
    return re.sub(
        r"(?m)(^|[ \t])([0-9,]+)\s*\n\s*(?=\d+\.\d+)",
        lambda match: match.group(1) + match.group(2),
        repaired,
    )


_STATEMENT_TITLE_PREFIX = r"(?:\d{1,2}、|[（(][一二三四五六七八九十]+[)）])?"


def _extract_balance_sheet_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    title = re.compile(
        rf"(?m)^\s*{_STATEMENT_TITLE_PREFIX}\s*合并资产负债[ \t\r\n]*表(?:[ \t]*[：:]?[ \t]*元)?[ \t]*$",
    )
    profit_title = re.compile(rf"(?m)^\s*{_STATEMENT_TITLE_PREFIX}\s*合并利润[ \t\r\n]*表[ \t]*$")
    start = next((index for index, page in enumerate(pages) if title.search(page.text)), None)
    if start is None:
        return []
    statement_pages = []
    for page in pages[start:start + 8]:
        if statement_pages and profit_title.search(page.text):
            break
        statement_pages.append(page)
    labels = {
        "assets": r"资产总计",
        "liabilities": r"(?<!流动)(?<!非流动)负债合计",
        "current_assets": r"流动资产合计",
        "current_liabilities": r"(?<!非)流动负债合计",
        "accounts_receivable": r"(?<!其他)应收账款",
        "inventory": r"存货",
    }
    facts = {name: _find_statement_fact(statement_pages, pattern) for name, pattern in labels.items()}
    facts["equity"] = _find_equity_fact(statement_pages)
    equivalent_assets = _find_statement_fact(statement_pages, r"负债和所有者权益总计")
    if equivalent_assets and (
        facts.get("assets") is None or not _accounting_identity_holds(
            facts.get("assets"), facts.get("liabilities"), facts.get("equity"),
        )
    ):
        # Definitionally equal to total assets; useful when a band-split PDF
        # detaches the 资产总计 label from its numeric cells.
        facts["assets"] = StatementFact(
            equivalent_assets.values, equivalent_assets.page,
            "资产等价闭合行: " + equivalent_assets.evidence,
        )
    if facts.get("liabilities") is None and facts.get("assets") and facts.get("equity"):
        assets = facts["assets"]
        equity = facts["equity"]
        if (
            assets.evidence.startswith("资产等价闭合行: ")
            and len(assets.values) >= 2 and len(equity.values) >= 2
            and all(asset > equity_value >= 0 for asset, equity_value in zip(assets.values[:2], equity.values[:2]))
        ):
            # A band-split PDF may detach the explicit 负债合计 row from its values while retaining
            # the audited total-equity and liabilities-plus-equity rows. Recover both periods only
            # from that exact accounting identity; ordinary asset rows never enable this fallback.
            liability_values = tuple(
                asset - equity_value for asset, equity_value in zip(assets.values[:2], equity.values[:2])
            )
            facts["liabilities"] = StatementFact(
                liability_values, max(assets.page, equity.page),
                "资产负债恒等式派生: " + assets.evidence + " | " + equity.evidence,
            )
    if not _accounting_identity_holds(facts.get("assets"), facts.get("liabilities"), facts.get("equity")):
        return []
    for larger_name, smaller_name in (
        ("assets", "current_assets"),
        ("current_assets", "inventory"),
        ("current_assets", "accounts_receivable"),
        ("liabilities", "current_liabilities"),
    ):
        if not _subsumption_consistent(facts.get(larger_name), facts.get(smaller_name)):
            facts[larger_name] = None
            facts[smaller_name] = None
    revenue = None
    revenue_page = None
    for index, page in enumerate(pages):
        in_summary = _is_summary_section_page(page.text) or (
            index > 0 and _is_summary_section_page(pages[index - 1].text) and "营业收入" not in pages[index - 1].text
        )
        parsed = _extract_summary_revenue(page.text, in_summary)
        if parsed:
            revenue, _, _ = parsed
            revenue_page = page.page
            break
    result = []
    def add(code: str, value: float, fact_names: tuple[str, ...]) -> None:
        used = [facts[name] for name in fact_names if facts.get(name)]
        page = max(item.page for item in used) if used else (revenue_page or 0)
        evidence = " | ".join(item.evidence for item in used)
        if revenue is not None and code in {"Q_G_ASSET_TURNOVER", "Q_G_AR_TURNOVER", "Q_G_CURRENT_ASSET_TURNOVER"}:
            evidence = f"营业收入={revenue:g} | " + evidence
        result.append((code, value, page, "合并报表自动派生: " + evidence))
    assets, liabilities = facts.get("assets"), facts.get("liabilities")
    if assets and liabilities and assets.values[0] != 0:
        debt_rate = liabilities.values[0] / assets.values[0] * 100
        if 0.5 <= debt_rate <= 200:
            add("Q_G_DEBT_ASSET_RATE", debt_rate, ("liabilities", "assets"))
    if revenue is not None and assets and len(assets.values) >= 2:
        asset_turnover = revenue / ((assets.values[0] + assets.values[1]) / 2)
        if 0.02 <= asset_turnover <= 10:
            add("Q_G_ASSET_TURNOVER", asset_turnover, ("assets",))
    current_assets = facts.get("current_assets")
    if revenue is not None and current_assets and len(current_assets.values) >= 2:
        current_turnover = revenue / ((current_assets.values[0] + current_assets.values[1]) / 2)
        if 0.05 <= current_turnover <= 30:
            add("Q_G_CURRENT_ASSET_TURNOVER", current_turnover, ("current_assets",))
    receivable = facts.get("accounts_receivable")
    if revenue is not None and receivable and len(receivable.values) >= 2 and (receivable.values[0] + receivable.values[1]) != 0:
        ar_turnover = revenue / ((receivable.values[0] + receivable.values[1]) / 2)
        if 0.1 <= ar_turnover <= 1000:
            add("Q_G_AR_TURNOVER", ar_turnover, ("accounts_receivable",))
    inventory = facts.get("inventory")
    if receivable and inventory and current_assets and current_assets.values[0] != 0:
        two_funds = (receivable.values[0] + inventory.values[0]) / current_assets.values[0] * 100
        if 0 <= two_funds <= 100:
            add("Q_G_TWO_FUNDS_RATE", two_funds, ("accounts_receivable", "inventory", "current_assets"))
    current_liabilities = facts.get("current_liabilities")
    if current_assets and inventory and current_liabilities and current_liabilities.values[0] != 0:
        quick_ratio = (current_assets.values[0] - inventory.values[0]) / current_liabilities.values[0] * 100
        if 0 < quick_ratio <= 1000:
            add("Q_G_QUICK_RATIO", quick_ratio, ("current_assets", "inventory", "current_liabilities"))
    equity = facts.get("equity")
    if equity and len(equity.values) >= 2 and equity.values[1] != 0:
        add("Q_G_CAPITAL_ACCUMULATION", (equity.values[0] - equity.values[1]) / equity.values[1] * 100, ("equity",))
    return result


def _accounting_identity_holds(
    assets: StatementFact | None, liabilities: StatementFact | None, equity: StatementFact | None,
) -> bool:
    """Reject statements whose parsed rows violate 资产 = 负债 + 权益 (column-interleave artifact)."""
    if assets and liabilities and assets.values[0] > 0 and liabilities.values[0] > assets.values[0] * 2:
        return False
    if not (assets and liabilities and equity):
        return True
    if assets.values[0] <= 0:
        return False
    expected = liabilities.values[0] + equity.values[0]
    return abs(assets.values[0] - expected) / assets.values[0] <= 0.05


def _subsumption_consistent(
    larger: StatementFact | None, smaller: StatementFact | None, tolerance: float = 0.02,
) -> bool:
    """Check containment between statement rows (e.g. 流动资产 ⊂ 总资产)."""
    if not (larger and smaller):
        return True
    return larger.values[0] >= smaller.values[0] * (1 - tolerance)


def _find_statement_fact(pages: list[PageText], label_pattern: str) -> StatementFact | None:
    money = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
    label = re.compile(label_pattern)
    for page in pages:
        repaired = _repair_wrapped_numbers(page.text)
        for match in label.finditer(repaired):
            fragment = repaired[match.start():match.end() + 180]
            raw_values = money.findall(fragment)
            if not raw_values:
                continue
            first_number_at = fragment.find(raw_values[0], match.end() - match.start())
            between = fragment[match.end() - match.start():first_number_at]
            if "：" in between or ":" in between:
                continue
            values = tuple(float(item.replace(",", "")) for item in raw_values)
            return StatementFact(values[:2], page.page, re.sub(r"\s+", " ", fragment)[:220])
    return None


def _find_equity_fact(pages: list[PageText]) -> StatementFact | None:
    money = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
    label = re.compile(r"(?:股东权益|所有者权益(?:（或股东权益）|\(或股东权益\))?)\s*合\s*计")
    for page in pages:
        repaired = _repair_wrapped_numbers(page.text)
        for match in label.finditer(repaired):
            prefix = re.sub(r"\s+", "", repaired[max(0, match.start() - 30):match.start()])
            if "母公司" in prefix or "归属于母公" in prefix:
                continue
            fragment = repaired[match.start():match.end() + 180]
            raw_values = money.findall(fragment)
            if not raw_values:
                continue
            first_number_at = fragment.find(raw_values[0], match.end() - match.start())
            between = fragment[match.end() - match.start():first_number_at]
            if "：" in between or ":" in between:
                continue
            values = tuple(float(item.replace(",", "")) for item in raw_values)
            return StatementFact(values[:2], page.page, re.sub(r"\s+", " ", fragment)[:220])
    return None


def _extract_english_balance_sheet_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    title = re.compile(
        r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+financial\s+position(?:\s|$)"
        r"|^\s*consolidated\s+balance\s+sheet\s*$",
    )
    end = re.compile(
        r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+(?:profit|income|changes|cash\s+flows?)"
        r"|^\s*consolidated\s+(?:income|profit)\s+statement\s*$",
    )
    starts = [index for index, page in enumerate(pages) if title.search(page.text)]
    best_result = []
    for start in starts:
        statement_pages = []
        for page in pages[start:start + 6]:
            if statement_pages and end.search(page.text):
                break
            statement_pages.append(page)
        assets = _find_english_statement_fact(statement_pages, r"Total assets(?!\s+less)")
        liabilities = _find_english_statement_fact(statement_pages, r"Total liabilities(?!\s+and)")
        current_assets = _find_english_statement_fact(statement_pages, r"Total current assets")
        current_liabilities = _find_english_statement_fact(statement_pages, r"Total current liabilities")
        receivable = _find_english_statement_fact(statement_pages, r"(?:Trade|Accounts) receivables?")
        inventory = _find_english_statement_fact(statement_pages, r"Inventor(?:y|ies)")
        equity = (
            _find_english_statement_fact(statement_pages, r"Total equity(?!\s+and)")
            or _find_cas_english_equity_fact(statement_pages)
        )
        implicit = _find_english_implicit_balance_facts(statement_pages)
        if implicit:
            assets = assets or implicit["assets"]
            liabilities = liabilities or implicit["liabilities"]
            current_assets = current_assets or implicit["current_assets"]
            current_liabilities = current_liabilities or implicit["current_liabilities"]
            equity = equity or implicit["equity"]
        revenue = _find_english_revenue_fact(pages)
        profit = _find_english_income_fact(
            pages, r"(?:(?:Profit|Loss) for the year|(?:[IV]{1,3}\s*[.:]?\s*)?Net profit(?!\s+attributable))",
        )
        profit_before_tax = _find_english_income_fact(
            pages, r"(?:(?:Profit|Loss) before (?:income )?tax(?:ation)?|(?:[IV]{1,3}\s*[.:]?\s*)?Total profit(?!\s+and))",
        )
        finance_cost = _find_english_income_fact(
            pages, r"(?:Finance costs?|(?:Including\s*:\s*)?Interest expenses?)",
        )
        income_tax = _find_english_income_fact(
            pages, r"(?:(?:Less\s*:\s*)?Income tax expenses?|Taxation)",
        )
        depreciation_amortisation = _find_english_cashflow_fact(
            pages, r"Depreciation and amorti[sz]ation",
        )
        if not _accounting_identity_holds(assets, liabilities, equity):
            continue
        balance_facts = {
            "assets": assets, "liabilities": liabilities, "current_assets": current_assets,
            "current_liabilities": current_liabilities, "inventory": inventory, "receivable": receivable,
        }
        for larger_name, smaller_name in (
            ("assets", "current_assets"),
            ("current_assets", "inventory"),
            ("current_assets", "receivable"),
            ("liabilities", "current_liabilities"),
        ):
            if not _subsumption_consistent(balance_facts[larger_name], balance_facts[smaller_name]):
                balance_facts[larger_name] = None
                balance_facts[smaller_name] = None
        assets = balance_facts["assets"]
        liabilities = balance_facts["liabilities"]
        current_assets = balance_facts["current_assets"]
        current_liabilities = balance_facts["current_liabilities"]
        inventory = balance_facts["inventory"]
        receivable = balance_facts["receivable"]
        result = []
        if assets and liabilities and assets.values[0] > 0:
            value = liabilities.values[0] / assets.values[0] * 100
            if 0.5 <= value <= 200:
                evidence = "English consolidated statement derived: " + liabilities.evidence + " | " + assets.evidence
                result.append(("Q_G_DEBT_ASSET_RATE", value, max(assets.page, liabilities.page), evidence))
        if assets and revenue and len(assets.values) >= 2:
            average_assets = (assets.values[0] + assets.values[1]) / 2
            if average_assets != 0:
                asset_turnover = revenue.values[0] / average_assets
                if 0.02 <= asset_turnover <= 10:
                    result.append((
                        "Q_G_ASSET_TURNOVER", asset_turnover,
                        max(assets.page, revenue.page), "English consolidated statements derived: " +
                        revenue.evidence + " | " + assets.evidence,
                    ))
        if current_assets and revenue and len(current_assets.values) >= 2:
            average_current_assets = (current_assets.values[0] + current_assets.values[1]) / 2
            if average_current_assets != 0:
                current_turnover = revenue.values[0] / average_current_assets
                if 0.05 <= current_turnover <= 30:
                    result.append((
                        "Q_G_CURRENT_ASSET_TURNOVER", current_turnover,
                        max(current_assets.page, revenue.page), "English consolidated statements derived: " +
                        revenue.evidence + " | " + current_assets.evidence,
                    ))
        if receivable and revenue and len(receivable.values) >= 2:
            average_receivable = (receivable.values[0] + receivable.values[1]) / 2
            if average_receivable > 0:
                ar_turnover = revenue.values[0] / average_receivable
                if 0.1 <= ar_turnover <= 1000:
                    result.append((
                        "Q_G_AR_TURNOVER", ar_turnover,
                        max(receivable.page, revenue.page), "English consolidated statements derived: " +
                        revenue.evidence + " | " + receivable.evidence,
                    ))
        if receivable and inventory and current_assets and current_assets.values[0] > 0:
            two_funds = (receivable.values[0] + inventory.values[0]) / current_assets.values[0] * 100
            if 0 <= two_funds <= 100:
                result.append((
                    "Q_G_TWO_FUNDS_RATE", two_funds,
                    max(receivable.page, inventory.page, current_assets.page),
                    "English consolidated statement derived: " + receivable.evidence + " | " +
                    inventory.evidence + " | " + current_assets.evidence,
                ))
        if inventory and current_assets and current_liabilities and current_liabilities.values[0] > 0:
            quick_ratio = (current_assets.values[0] - inventory.values[0]) / current_liabilities.values[0] * 100
            if 0 < quick_ratio <= 1000:
                result.append((
                    "Q_G_QUICK_RATIO", quick_ratio,
                    max(inventory.page, current_assets.page, current_liabilities.page),
                    "English consolidated statement derived: " + current_assets.evidence + " | " +
                    inventory.evidence + " | " + current_liabilities.evidence,
                ))
        if equity and len(equity.values) >= 2 and equity.values[1] != 0:
            growth = (equity.values[0] - equity.values[1]) / abs(equity.values[1]) * 100
            if -1000 <= growth <= 1000:
                result.append((
                    "Q_G_CAPITAL_ACCUMULATION", growth, equity.page,
                    "English consolidated statement derived: " + equity.evidence,
                ))
        if profit and equity and len(equity.values) >= 2:
            average_equity = (equity.values[0] + equity.values[1]) / 2
            if average_equity != 0:
                roe = profit.values[0] / average_equity * 100
                if -300 <= roe <= 300:
                    result.append((
                        "Q_G_ROE", roe, max(profit.page, equity.page),
                        "English consolidated statements derived: " + profit.evidence +
                        " | " + equity.evidence,
                    ))
        if profit_before_tax and finance_cost:
            interest = abs(finance_cost.values[0])
            ebit = profit_before_tax.values[0] + interest
            if interest > 0:
                coverage = ebit / interest
                if -1000 <= coverage <= 1000:
                    result.append((
                        "Q_G_EBITDA_INTEREST", coverage,
                        max(profit_before_tax.page, finance_cost.page),
                        "English consolidated income statement derived: " +
                        profit_before_tax.evidence + " | " + finance_cost.evidence,
                    ))
            if assets and len(assets.values) >= 2:
                average_assets = (assets.values[0] + assets.values[1]) / 2
                if average_assets != 0:
                    roa = ebit / average_assets * 100
                    if -100 <= roa <= 100:
                        result.append((
                            "Q_G_ROA", roa, max(profit_before_tax.page, finance_cost.page, assets.page),
                            "English consolidated statements derived: " +
                            profit_before_tax.evidence + " | " + finance_cost.evidence +
                            " | " + assets.evidence,
                        ))
        if all((profit, income_tax, finance_cost, depreciation_amortisation, revenue)):
            ebitda = (
                profit.values[0] + abs(income_tax.values[0]) + abs(finance_cost.values[0]) +
                abs(depreciation_amortisation.values[0])
            )
            margin = ebitda / revenue.values[0] * 100 if revenue.values[0] else None
            if margin is not None and -1000 <= margin <= 1000:
                used = (profit, income_tax, finance_cost, depreciation_amortisation, revenue)
                result.append((
                    "Q_G_EBITDA_MARGIN", margin, max(item.page for item in used),
                    "English consolidated statements derived: " +
                    " | ".join(item.evidence for item in used),
                ))
        if len(result) > len(best_result):
            best_result = result
    summary_debt = _extract_english_summary_debt_rate(pages)
    if summary_debt and not any(code == "Q_G_DEBT_ASSET_RATE" for code, *_ in best_result):
        best_result.append(summary_debt)
    return best_result


def _extract_english_summary_debt_rate(pages: list[PageText]) -> tuple[str, float, int, str] | None:
    """Use an audited multi-year financial summary only with three-line identity closure."""
    number = re.compile(r"\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?")

    def row(page_text: str, label: str) -> tuple[float, float] | None:
        match = re.search(rf"(?mi)^\s*{label}(?:\s+[^\d(\n][^\n]*)?\s+(?P<body>[^\n]+)$", page_text)
        if not match:
            return None
        values = []
        for raw in number.findall(match.group("body")):
            parsed = float(raw.strip("()").replace(",", ""))
            values.append(-parsed if raw.startswith("(") else parsed)
        return tuple(values[:2]) if len(values) >= 2 else None

    for page in pages:
        if not re.search(
            r"(?:Five[- ]Year Financial Summary|Financial Summary|五年(?:財務|财务)(?:概要|摘要))",
            page.text, re.I,
        ):
            continue
        header = re.search(r"(?m)^\s*(20\d{2})\s+(20\d{2})(?:\s+20\d{2}){0,4}\s*$", page.text)
        if not header or int(header.group(1)) <= int(header.group(2)):
            continue
        assets = row(page.text, r"Total assets(?:\s+總資產)?")
        liabilities = row(page.text, r"Total liabilities(?:\s+總負債)?")
        net_assets = row(page.text, r"Net assets(?:\s+資產淨值)?")
        if not (assets and liabilities and net_assets):
            continue
        if any(value <= 0 for value in assets + net_assets):
            continue
        if any(
            abs(assets[i] - abs(liabilities[i]) - net_assets[i]) / assets[i] > 0.001
            for i in range(2)
        ):
            continue
        value = abs(liabilities[0]) / assets[0] * 100
        if not 0.5 <= value <= 200:
            continue
        evidence = (
            "English audited financial summary derived: two-year assets = liabilities + net assets; "
            f"assets={assets[0]:g},{assets[1]:g}; liabilities={liabilities[0]:g},{liabilities[1]:g}; "
            f"net_assets={net_assets[0]:g},{net_assets[1]:g}"
        )
        return "Q_G_DEBT_ASSET_RATE", value, page.page, evidence
    return None


def _find_english_revenue_fact(pages: list[PageText]) -> StatementFact | None:
    return _find_english_income_fact(
        pages, r"(?:I\.\s*)?(?:Total\s+revenue\s+from\s+operations|(?:(?:Total\s+)?Operating\s+)?Revenue)",
    )


_CAS_ENGLISH_RD = re.compile(r"(?i)research\s+and\s+development\s+expenses?(?P<body>[\s\S]{0,80})")


def _find_cas_english_rd_fact(pages: list[PageText]) -> StatementFact | None:
    """Find R&D expense in CAS-format English income statements where the label
    'Research and development expenses' wraps across lines before its values."""
    number = re.compile(r"\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?")
    for page in pages:
        match = _CAS_ENGLISH_RD.search(_repair_wrapped_numbers(page.text))
        if not match:
            continue
        raw_values = number.findall(match.group("body"))
        if len(raw_values) < 2:
            continue
        values = tuple(float(raw.strip("()").replace(",", "")) for raw in raw_values[:2])
        evidence = re.sub(r"\s+", " ", match.group(0)).strip()
        return StatementFact(values, page.page, evidence[:220])
    return None


_CAS_ENGLISH_EQUITY = re.compile(
    r"(?i)total\s+owners['’]?\s*equity(?:[\s\S]{0,40}?equity\))?(?P<body>[\s\S]{0,80})"
)


def _find_cas_english_equity_fact(pages: list[PageText]) -> StatementFact | None:
    """Find total equity in CAS-format English balance sheets ('Total owners' equity',
    whose '(or shareholders' equity)' suffix and values may wrap onto the next line)."""
    number = re.compile(r"\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?")
    for page in pages:
        match = _CAS_ENGLISH_EQUITY.search(_repair_wrapped_numbers(page.text))
        if not match:
            continue
        raw_values = number.findall(match.group("body"))
        values = []
        for raw in raw_values:
            negative = raw.startswith("(") and raw.endswith(")")
            value = float(raw.strip("()").replace(",", ""))
            values.append(-value if negative else value)
        if len(values) < 2:
            continue
        evidence = re.sub(r"\s+", " ", match.group(0)).strip()
        return StatementFact(tuple(values[:2]), page.page, evidence[:220])
    return None


def _find_english_income_fact(pages: list[PageText], label_pattern: str) -> StatementFact | None:
    title = re.compile(
        r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+"
        r"(?:profit\s+or\s+loss|profit\s+and\s+loss|income|comprehensive\s+income)(?:\s|$)"
        r"|^\s*consolidated\s+(?:income|profit)\s+statement\s*$",
    )
    end = re.compile(
        r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+(?:financial\s+position|changes|cash\s+flows?)"
        r"|^\s*parent\s+(?:company\s+)?(?:income|profit)\s+statement\s*$",
    )
    for start in (index for index, page in enumerate(pages) if title.search(page.text)):
        statement_pages = []
        for page in pages[start:start + 5]:
            if statement_pages and end.search(page.text):
                break
            statement_pages.append(page)
        fact = _find_english_statement_fact(statement_pages, label_pattern)
        if fact:
            return fact
    return None


def _find_english_cashflow_fact(pages: list[PageText], label_pattern: str) -> StatementFact | None:
    title = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?(?:statement\s+of\s+cash\s+flows?|cash\s+flow\s+statement)(?:\s|$)",
    )
    end = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?statement\s+of\s+"
        r"(?:financial position|profit|income|changes)",
    )
    for start in (index for index, page in enumerate(pages) if title.search(page.text)):
        statement_pages = []
        for page in pages[start:start + 6]:
            if statement_pages and end.search(page.text):
                break
            statement_pages.append(page)
        fact = _find_english_statement_fact(statement_pages, label_pattern)
        if fact:
            return fact
    return None


def _find_english_statement_fact(pages: list[PageText], label_pattern: str) -> StatementFact | None:
    label = re.compile(
        rf"(?mi)^\s*(?:[^\x00-\x7F][^\n]{{0,30}}?\s+)?{label_pattern}\b(?P<body>[^\n]*)$",
    )
    number = re.compile(r"\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?")
    for page in pages:
        repaired = re.sub(r"[“”]\s*\n\s*-\s*\n\s*[“”]", "“-”", _repair_wrapped_numbers(page.text))
        for match in label.finditer(repaired):
            raw_values = number.findall(match.group("body"))
            values = []
            for raw in raw_values:
                negative = raw.startswith("(") and raw.endswith(")")
                value = float(raw.strip("()").replace(",", ""))
                values.append(-value if negative else value)
            original_count = len(values)
            if len(values) == 3 and abs(values[0]) <= 999:
                values = values[1:]
            elif len(values) != 2:
                continue
            if original_count == 2 and abs(values[0]) <= 100 and abs(values[1]) > 1000:
                continue
            if len(values) == 2:
                # Some report summaries present explicit ascending columns (2024 2025).
                # Normalize to current-first only when a two-year header is present on
                # the same page before the row; never infer order from document dates.
                prefix = repaired[:match.start()]
                year_headers = list(re.finditer(
                    r"(?m)^\s*(20\d{2})\s+(20\d{2})(?:\s|$)", prefix,
                ))
                reordered = False
                if year_headers:
                    first_year, second_year = map(int, year_headers[-1].groups())
                    if first_year < second_year and second_year - first_year == 1:
                        values.reverse(); reordered = True
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                if reordered:
                    evidence += " [ascending year columns normalized current-first]"
                return StatementFact(tuple(values[:2]), page.page, evidence[:220])
    return None


def _find_english_implicit_balance_facts(pages: list[PageText]) -> dict[str, StatementFact] | None:
    """Recover a two-column balance sheet whose section totals are unlabeled.

    Some IFRS layouts print section subtotals immediately before the next heading.  They
    are accepted only when all five subtotals are present and both years independently
    satisfy assets = equity + current liabilities + non-current liabilities.
    """
    value = r"\(?[\d,]+(?:\.\d+)?\)?"

    def before(heading: str) -> StatementFact | None:
        pattern = re.compile(
            rf"(?mi)^\s*(?P<current>{value})\s+(?P<prior>{value})\s*$\n\s*{heading}\b",
        )
        for page in pages:
            match = pattern.search(page.text)
            if not match:
                continue
            parsed = []
            for name in ("current", "prior"):
                raw = match.group(name)
                number = float(raw.strip("()").replace(",", ""))
                parsed.append(-number if raw.startswith("(") else number)
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return StatementFact(tuple(parsed), page.page, "implicit section subtotal: " + evidence[:180])
        return None

    current_assets = before(r"Current liabilities")
    current_liabilities = before(r"Net current (?:assets|liabilities)")
    equity = before(r"Non-current liabilities")
    non_current_liabilities = before(r"Equity and non-current liabilities")
    assets_less_current_liabilities = _find_english_statement_fact(
        pages, r"Total assets less current liabilities",
    )
    required = (
        current_assets, current_liabilities, equity,
        non_current_liabilities, assets_less_current_liabilities,
    )
    if not all(required):
        return None
    assert current_assets and current_liabilities and equity
    assert non_current_liabilities and assets_less_current_liabilities
    asset_values = []
    liability_values = []
    for index in range(2):
        current_debt = abs(current_liabilities.values[index])
        non_current_debt = abs(non_current_liabilities.values[index])
        assets = assets_less_current_liabilities.values[index] + current_debt
        liabilities = current_debt + non_current_debt
        if assets <= 0 or equity.values[index] <= 0:
            return None
        if abs(assets - equity.values[index] - liabilities) / assets > 0.001:
            return None
        asset_values.append(assets); liability_values.append(liabilities)
    page = max(item.page for item in required if item)
    closure = (
        "implicit IFRS section totals; two-year accounting identity closure: "
        + " | ".join(item.evidence for item in required if item)
    )
    return {
        "assets": StatementFact(tuple(asset_values), page, closure[:500]),
        "liabilities": StatementFact(tuple(liability_values), page, closure[:500]),
        "current_assets": current_assets,
        "current_liabilities": StatementFact(
            tuple(abs(item) for item in current_liabilities.values),
            current_liabilities.page, current_liabilities.evidence,
        ),
        "equity": equity,
    }


def _extract_english_income_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    title = re.compile(
        r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+"
        r"(?:profit\s+or\s+loss|profit\s+and\s+loss|income|comprehensive\s+income)(?:\s|$)"
        r"|^\s*consolidated\s+(?:income|profit)\s+statement\s*$",
    )
    end = re.compile(
        r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+(?:financial\s+position|changes|cash\s+flows?)"
        r"|^\s*parent\s+(?:company\s+)?(?:income|profit)\s+statement\s*$",
    )
    for start in (index for index, page in enumerate(pages) if title.search(page.text)):
        statement_pages = []
        for page in pages[start:start + 5]:
            if statement_pages and end.search(page.text):
                break
            statement_pages.append(page)
        revenue = _find_english_statement_fact(
            statement_pages, r"(?:I\.\s*)?(?:Total\s+revenue\s+from\s+operations|(?:(?:Total\s+)?Operating\s+)?Revenue)",
        )
        if not revenue or revenue.values[0] == 0:
            continue
        result = []
        if revenue.values[1] != 0:
            growth = (revenue.values[0] - revenue.values[1]) / abs(revenue.values[1]) * 100
            if -100 <= growth <= 1000:
                result.append((
                    "Q_G_REVENUE_GROWTH", growth, revenue.page,
                    "English consolidated income statement derived: " + revenue.evidence,
                ))
        operating = _find_english_statement_fact(
            statement_pages, r"(?:II{1,2}\.\s*)?(?:Operating profit|Profit from operations)",
        )
        if operating:
            margin = operating.values[0] / revenue.values[0] * 100
            if -1000 <= margin <= 1000:
                result.append((
                    "Q_G_OPERATING_MARGIN", margin, max(revenue.page, operating.page),
                    "English consolidated income statement derived: " +
                    operating.evidence + " | " + revenue.evidence,
                ))
            if operating.values[1] != 0:
                operating_growth = (
                    (operating.values[0] - operating.values[1]) / abs(operating.values[1]) * 100
                )
                if -1000 <= operating_growth <= 1000:
                    result.append((
                        "Q_G_OPERATING_PROFIT_GROWTH", operating_growth, operating.page,
                        "English consolidated income statement derived: " + operating.evidence,
                    ))
        research = _find_english_statement_fact(
            statement_pages, r"(?:Research and development|R&D) (?:expenses?|expenditure|costs?)",
        ) or _find_cas_english_rd_fact(statement_pages)
        if research:
            rd_rate = abs(research.values[0]) / abs(revenue.values[0]) * 100
            if 0 <= rd_rate <= 100:
                result.append((
                    "Q_S_RD_RATE", rd_rate, max(revenue.page, research.page),
                    "English consolidated income statement derived: " +
                    research.evidence + " | " + revenue.evidence,
                ))
        total_costs = _find_english_statement_fact(
            statement_pages, r"(?:II\.\s*)?(?:Total operating costs?|Total cost of operations|Total operating expenses|Total costs and expenses)",
        )
        if total_costs:
            cost_rate = abs(total_costs.values[0]) / abs(revenue.values[0]) * 100
            if 0 <= cost_rate <= 1000:
                result.append((
                    "Q_G_COST_REVENUE_RATE", cost_rate, max(revenue.page, total_costs.page),
                    "English consolidated income statement derived: " +
                    total_costs.evidence + " | " + revenue.evidence,
                ))
        if result:
            return result
    return []


def _extract_collapsed_english_income_rows(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    """Recover revenue only from a deterministic PDF column-collapse signature."""
    pattern = re.compile(
        r"Revenue\s+\d+\s+Cost\s+of\s+sales\s+and\s+services\s+provided\s+\d+\s+Gross\s+profit\s+"
        r"(?P<current>[\d,]+(?:\.\d+)?)\s+\([\d,]+(?:\.\d+)?\)\s+"
        r"(?P<previous>[\d,]+(?:\.\d+)?)\s+\([\d,]+(?:\.\d+)?\)\s+"
        r"[\d,]+(?:\.\d+)?\s+[\d,]+(?:\.\d+)?", re.I,
    )
    title = re.compile(
        r"(?is)Consolidated\s+Statement\s+of\s+Profit\s+or\s+Loss\s+and\s+Other\s+Comprehensive\s+Income",
    )
    for page in pages:
        if not title.search(page.text):
            continue
        normalized = _normalize(page.text)
        match = pattern.search(normalized)
        if not match:
            continue
        current = float(match.group("current").replace(",", ""))
        previous = float(match.group("previous").replace(",", ""))
        if current < 0 or previous <= 0:
            return []
        growth = (current - previous) / previous * 100
        if not -100 <= growth <= 1000:
            return []
        return [(
            "Q_G_REVENUE_GROWTH", growth, page.page,
            "English collapsed statement row derived: " + re.sub(r"\s+", " ", match.group(0)),
        )]
    return []


def _extract_english_cashflow_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    title = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?(?:statement\s+of\s+cash\s+flows?|cash\s+flow\s+statement)(?:\s|$)",
    )
    end = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?statement\s+of\s+"
        r"(?:financial position|profit|income|changes)",
    )
    revenue = _find_english_revenue_fact(pages)
    current_liabilities = None
    balance_title = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?statement of financial position(?:\s|$)|"
        r"^\s*consolidated balance sheet\s*$",
    )
    for start in (index for index, page in enumerate(pages) if balance_title.search(page.text)):
        current_liabilities = _find_english_statement_fact(
            pages[start:start + 6], r"Total current liabilities",
        )
        if current_liabilities:
            break
    best_result = []
    for start in (index for index, page in enumerate(pages) if title.search(page.text)):
        statement_pages = []
        for page in pages[start:start + 6]:
            if statement_pages and end.search(page.text):
                break
            statement_pages.append(page)
        net_operating_cash = _find_english_statement_fact(
            statement_pages,
            r"Net cash (?:flows? )?(?:(?:generated )?from|(?:used )?in|inflow from) operating activities",
        )
        customer_receipts = _find_english_statement_fact(
            statement_pages,
            r"(?:(?:Cash\s+)?Receipts\s+from\s+customers|Cash\s+received\s+from\s+sales\s+of\s+goods\s+"
            r"(?:and\s+provision|or\s+rendering)\s+of\s+services)",
        )
        result = []
        if net_operating_cash and current_liabilities and current_liabilities.values[0] > 0:
            ratio = net_operating_cash.values[0] / current_liabilities.values[0] * 100
            if -1000 <= ratio <= 1000:
                result.append((
                    "Q_G_CASH_CURRENT_LIABILITY", ratio,
                    max(net_operating_cash.page, current_liabilities.page),
                    "English consolidated statements derived: " + net_operating_cash.evidence +
                    " | " + current_liabilities.evidence,
                ))
        if customer_receipts and revenue and revenue.values[0] != 0:
            ratio = customer_receipts.values[0] / revenue.values[0] * 100
            if -1000 <= ratio <= 1000:
                result.append((
                    "Q_G_CASH_REALIZATION", ratio,
                    max(customer_receipts.page, revenue.page),
                    "English consolidated statements derived: " + customer_receipts.evidence +
                    " | " + revenue.evidence,
                ))
        if len(result) > len(best_result):
            best_result = result
    return best_result


def _extract_english_employee_per_capita(
    pages: list[PageText], report_year: int,
) -> list[tuple[str, float, int, str]]:
    employee_pattern = re.compile(
        rf"As\s+at\s+31\s+December\s+{report_year},\s+the\s+Group\s+had\s+a\s+total\s+of\s+"
        r"(?P<count>[\d,]+)\s+full-time\s+employees\b", re.I,
    )
    employee_fact = None
    for page in pages:
        match = employee_pattern.search(_normalize(page.text))
        if match:
            employee_fact = (int(match.group("count").replace(",", "")), page.page, match.group(0))
            break
    if not employee_fact or employee_fact[0] <= 0:
        return []
    number = r"\(?[\d,]+(?:\.\d+)?\)?"
    for page in pages:
        text = page.text
        if not (
            re.search(r"Expressed\s+in\s+RMB\s+unless\s+otherwise\s+indicated", text, re.I)
            and re.search(r"Increase\s+during\s+the\s+year", text, re.I)
            and "Employee benefits payable" in text
        ):
            continue
        def values(label: str) -> list[float]:
            match = re.search(rf"(?mi)^\s*{label}(?P<body>[^\n]*(?:\n(?![A-Z—-])[^\n]*)?)", text)
            if not match:
                return []
            result = []
            for raw in re.findall(number, match.group("body")):
                negative = raw.startswith("(")
                value = float(raw.strip("()").replace(",", ""))
                result.append(-value if negative else value)
            return result
        welfare = values(r"Staff welfare")
        social = values(r"Social insurance")
        housing = values(r"Housing provident fund")
        education = values(r"Labour union operating funds and\s+staff education funds")
        if not (welfare and len(social) >= 2 and len(housing) >= 2 and len(education) >= 2):
            continue
        welfare_increase = welfare[0]
        benefit_increase = welfare_increase + social[1] + housing[1]
        education_increase = education[1]
        employees, employee_page, employee_evidence = employee_fact
        common = (
            f"English RMB employee note derived: employees={employees} | "
            f"{employee_evidence} | current-year increases on page {page.page}"
        )
        return [
            ("Q_S_BENEFIT_PER_EMPLOYEE", benefit_increase / 10_000 / employees,
             max(employee_page, page.page), common),
            ("Q_S_EDU_PER_EMPLOYEE", education_increase / 10_000 / employees,
             max(employee_page, page.page), common),
        ]
    return []


_CN_NUM = r"[\d,]+(?:\.\d+)?"
_CN_EMP_TOTAL = re.compile(r"(?:报告期末)?在职员工的数量合计\s*[（(]?\s*人?\s*[）)]?\s*(?P<count>[\d,]+)")
_CN_EMP_PARENT = re.compile(r"(?:报告期末)?母公司在职员工的数量\s*[（(]?\s*人?\s*[）)]?\s*(?P<count>[\d,]+)")
_CN_EMP_SUB = re.compile(r"(?:报告期末)?主要子公司在职员工的数量\s*[（(]?\s*人?\s*[）)]?\s*(?P<count>[\d,]+)")
_CN_EMP_H_LABEL = re.compile(
    r"报告期末母公司在职员工的数量[（(]\s*人\s*[）)][^\n]*报告期末主要子公司在职员工的数量[（(]\s*人\s*[）)]"
    r"[^\n]*报告期末在职员工的数量合计[（(]\s*人\s*[）)]"
)
_CN_EMP_H_NUMBER = re.compile(r"(?m)^\s*([\d,]{1,12})\s*$")
_CN_EMP_BSE_HEADER = re.compile(r"按工作性质分类[^\n]{0,80}期末人数")
_CN_EMP_BSE_TOTAL = re.compile(
    rf"(?m)^\s*员工总计\s+(?P<v0>{_CN_NUM})\s+(?P<v1>{_CN_NUM})\s+(?P<v2>{_CN_NUM})\s+(?P<v3>{_CN_NUM})\s*$"
)
_CN_COMP_SECTION_START = re.compile(r"合并财务报表项目注释")
_CN_COMP_SECTION_END = re.compile(r"母公司财务报表(?:主要)?项目注释")
_CN_COMP_HEADER = re.compile(r"(?:期初|年初)余额\s+(?:本期|本年)增加\s+(?:本期|本年)减少\s+(?:期末|年末)余额")
_CN_COMP_HEADER_TRUNC = re.compile(r"(?:期初|年初)余额\s+(?:本期|本年)增加\s+(?:本期|本年)减少(?!\s*(?:期末|年末)余额)")
_CN_COMP_HEADER_STRIP = re.compile(
    r"(?:项目\s*)?(?:期初|年初)余额\s+(?:本期|本年)增加\s+(?:本期|本年)减少(?:\s+(?:期末|年末)余额)?"
)
_CN_COMP_TABLE_TITLE = re.compile(r"短期薪酬(?:列示|情况)?\s*$", re.M)
_CN_UNIT_FACTORS = {"元": 1.0, "千元": 1e3, "万元": 1e4, "百万元": 1e6}


def _cn_employee_count_horizontal(pages: list[PageText]) -> tuple[int, int, str] | None:
    """Read the three-column horizontal employee table: labels share one line and values
    are scattered by two-column PDF flow; accept only an exact 母公司+子公司=合计 triple
    corroborated by a nearby 专业构成/教育程度 合计."""
    combined = ""
    page_marks: list[tuple[int, int]] = []
    for page in pages:
        page_marks.append((len(combined), page.page))
        combined += page.text + "\n"
    label = _CN_EMP_H_LABEL.search(combined)
    if not label:
        return None
    label_page = next(page for offset, page in reversed(page_marks) if offset <= label.start())
    window = combined[label.end():label.end() + 1500]
    nums = [int(m.group(1).replace(",", "")) for m in _CN_EMP_H_NUMBER.finditer(window)]
    for i in range(len(nums) - 2):
        a, b, c = nums[i], nums[i + 1], nums[i + 2]
        if a + b == c and 0 < a and 0 < b and c <= 2_000_000:
            if re.search(rf"(?:合计|员工总计)\s*(?:{c:,}|{c})(?![\d,])", window):
                return c, label_page, f"员工情况表水平布局: 母公司{a}+子公司{b}=合计{c}"
    return None


def _cn_employee_count(pages: list[PageText]) -> tuple[int, int, str] | None:
    """Locate the period-end group employee count with scope consistency checks."""
    for page in pages:
        total = _CN_EMP_TOTAL.search(page.text)
        if total:
            count = int(total.group("count").replace(",", ""))
            parent = _CN_EMP_PARENT.search(page.text)
            subsidiary = _CN_EMP_SUB.search(page.text)
            if parent and subsidiary:
                p = int(parent.group("count").replace(",", ""))
                s = int(subsidiary.group("count").replace(",", ""))
                if p + s != count:
                    continue
            if count > 0:
                return count, page.page, re.sub(r"\s+", " ", total.group(0)).strip()
        if _CN_EMP_BSE_HEADER.search(page.text):
            match = _CN_EMP_BSE_TOTAL.search(page.text)
            if match:
                values = [float(match.group(f"v{i}").replace(",", "")) for i in range(4)]
                if abs(values[0] + values[1] - values[2] - values[3]) < 1 and values[3] > 0:
                    return (
                        int(values[3]), page.page,
                        "员工情况表员工总计期末人数: " + re.sub(r"\s+", " ", match.group(0)).strip(),
                    )
    return _cn_employee_count_horizontal(pages)


def _cn_comp_note_section(pages: list[PageText]) -> list[PageText]:
    """Bound the consolidated-statement notes; never read the parent-company notes."""
    start = end = None
    for index, page in enumerate(pages):
        if start is None and _CN_COMP_SECTION_START.search(page.text):
            start = index
        elif start is not None and _CN_COMP_SECTION_END.search(page.text):
            end = index
            break
    if start is not None:
        return pages[start:end]
    occurrences = [
        page for page in pages
        if re.search(r"应付职工薪酬(?:列示|情况)?\s*$", page.text, re.M)
    ]
    if len(occurrences) == 1:
        return pages
    return []


def _cn_resolve_increase(cells: list[float], trailing_pool: set[float] | None = None) -> float | None:
    """Pick the 本期/本年增加 column; accounting identity 期末=期初+增加-减少 must hold.

    3-cell rows lack one column: （增加,减少,期末） and （年初,增加,减少） with zero 期末 are
    self-checking; otherwise the implied 期末 must appear verbatim in the page's trailing
    detached 年末余额 column cluster (exact cents match) to bind the 增加 column safely.
    """
    tolerance = 1.0
    if len(cells) == 4:
        if abs(cells[0] + cells[1] - cells[2] - cells[3]) <= tolerance:
            return cells[1]
        return None
    if len(cells) == 3:
        if abs(cells[0] - cells[1] - cells[2]) <= tolerance:
            return cells[0]
        if abs(cells[0] + cells[1] - cells[2]) <= tolerance:
            return cells[1]
        implied_end = cells[0] + cells[1] - cells[2]
        if trailing_pool and any(abs(implied_end - pool) <= 0.01 for pool in trailing_pool):
            return cells[1]
        return None
    if len(cells) == 2:
        if abs(cells[0] - cells[1]) <= tolerance:
            return cells[0]
        implied_end = cells[0] - cells[1]
        if implied_end > 0 and trailing_pool and any(abs(implied_end - pool) <= 0.01 for pool in trailing_pool):
            return cells[0]
    return None


def _cn_comp_row(text: str, label: str) -> tuple[float, str] | None:
    # 表头剥离后标签可在行首或行中；数值体以中文/序号/行尾为界，避免吞入下一行序号
    stripped = _CN_COMP_HEADER_STRIP.sub("", text)
    pattern = re.compile(
        rf"(?<![\u4e00-\u9fff、，,])[ \t]*(?:[（(]\s*\d+\s*[）)]\s*|\d+\s*[、.．]\s*)?{label}[ \t]*"
        rf"(?P<body>(?:[ \t]*(?:{_CN_NUM}|-))+?)"
        rf"(?=\s*(?:[\u4e00-\u9fff]|[（(]\s*\d+\s*[）)]|\d+\s*[、.．]|\n\s*-|$))"
    )
    for match in pattern.finditer(stripped):
        cells = []
        for raw in re.findall(rf"{_CN_NUM}|-", match.group("body")):
            cells.append(0.0 if raw == "-" else float(raw.replace(",", "")))
        trailing_pool = {
            float(number.replace(",", ""))
            for number in re.findall(r"(?m)^\s*([\d,]+\.\d{1,2})\s*$", stripped[match.end():])
        }
        increase = _cn_resolve_increase(cells, trailing_pool)
        if increase is not None and increase > 0:
            return increase, re.sub(r"\s+", " ", match.group(0)).strip()
    return None


def _cn_comp_unit(page_text: str, section_head: str) -> float | None:
    table_unit = re.search(r"单位[：:]\s*(?:人民币)?\s*(百万元|千元|万元|元)", page_text)
    if table_unit:
        return _CN_UNIT_FACTORS[table_unit.group(1)]
    declared = re.search(
        r"(?:以|为)\s*人民币\s*(百万元|千元|万元|元)\s*列示|[（(]金额单位[：:]\s*人民币\s*(百万元|千元|万元|元)[）)]",
        section_head,
    )
    if declared:
        return _CN_UNIT_FACTORS[declared.group(1) or declared.group(2)]
    return 1.0


_CN_COMP_ROWS = (
    ("pay", r"工\s*资\s*、\s*奖\s*金\s*、\s*津\s*贴\s*和\s*补\s*贴"),
    ("welfare", r"职\s*工\s*福\s*利\s*费"),
    ("social", r"社\s*会\s*保\s*险\s*费"),
    ("housing", r"住\s*房\s*公\s*积\s*金"),
    ("education", r"工\s*会\s*经\s*费\s*(?:和|及)\s*职\s*工\s*教\s*育\s*经\s*费"),
)
_CN_PER_CAPITA_RANGES = {
    "Q_S_PAY_PER_EMPLOYEE": (1.0, 150.0),
    "Q_S_BENEFIT_PER_EMPLOYEE": (0.05, 60.0),
    "Q_S_EDU_PER_EMPLOYEE": (0.005, 30.0),
}


def _extract_chinese_employee_per_capita(
    pages: list[PageText],
) -> list[tuple[str, float, int, str]]:
    """Derive per-capita pay/benefit/education from the consolidated 应付职工薪酬 note.

    同页闭环：短期薪酬列示的列头与数据行必须在同一页，员工数取报告期末在职合计
    （母公司+子公司交叉校验）或北交所员工总计期末人数（期初+新增-减少=期末校验），
    禁止跨表拼接母公司附注口径。
    """
    employee_fact = _cn_employee_count(pages)
    if not employee_fact:
        return []
    employees, employee_page, employee_evidence = employee_fact
    section = _cn_comp_note_section(pages)
    if not section:
        return []
    section_head = "".join(page.text for page in section[:4])
    for index, page in enumerate(section):
        header = _CN_COMP_HEADER.search(page.text) or _CN_COMP_HEADER_TRUNC.search(page.text)
        if not (header and _CN_COMP_TABLE_TITLE.search(page.text)):
            continue
        probe = page.text + (section[index + 1].text if index + 1 < len(section) else "")
        if "职工福利费" not in probe and "工会经费" not in probe and "工资、奖金" not in probe:
            continue
        row_pages = [page]
        after_header = page.text[header.end():]
        has_inline_rows = any(
            re.search(label, after_header) for _, label in _CN_COMP_ROWS
        )
        if not has_inline_rows and index + 1 < len(section):
            # 表头在页尾、数据行在下一页：仅当标题与完整表头同页且后续无其他行时才绑定
            row_pages.append(section[index + 1])
        rows: dict[str, tuple[float, str]] = {}
        row_pages_used: dict[str, int] = {}
        for row_page in row_pages:
            for key, label in _CN_COMP_ROWS:
                if key in rows:
                    continue
                row = _cn_comp_row(row_page.text, label)
                if row:
                    rows[key] = row
                    row_pages_used[key] = row_page.page
        if "education" not in rows and not {"welfare", "social", "housing"} <= rows.keys():
            if "pay" not in rows:
                continue
        unit_factor = _cn_comp_unit(page.text, section_head)
        if unit_factor is None:
            continue
        base = f"中文应付职工薪酬附注派生: 员工数={employees}(第{employee_page}页 {employee_evidence})"
        result = []
        combos = [
            ("Q_S_PAY_PER_EMPLOYEE", ["pay"]),
            ("Q_S_BENEFIT_PER_EMPLOYEE", ["welfare", "social", "housing"]),
            ("Q_S_EDU_PER_EMPLOYEE", ["education"]),
        ]
        for code, keys in combos:
            if not all(key in rows for key in keys):
                continue
            total = sum(rows[key][0] for key in keys)
            value = total * unit_factor / 10_000 / employees
            low, high = _CN_PER_CAPITA_RANGES[code]
            if not low <= value <= high:
                continue
            row_evidence = " | ".join(f"{rows[key][1]}(第{row_pages_used[key]}页)" for key in keys)
            result.append((
                code, value, max(employee_page, *(row_pages_used[key] for key in keys)),
                f"{base} | {row_evidence}",
            ))
        if result:
            return result
    return []


def _statement_page_range(
    pages: list[PageText], start_title: str, end_title: str, maximum_pages: int = 8,
) -> list[PageText]:
    start_pattern = re.compile(rf"(?m)^\s*{_STATEMENT_TITLE_PREFIX}\s*{start_title}\s*$")
    end_pattern = re.compile(rf"(?m)^\s*{_STATEMENT_TITLE_PREFIX}\s*{end_title}\s*$")
    start = next((index for index, page in enumerate(pages) if start_pattern.search(page.text)), None)
    if start is None:
        return []
    result = []
    for page in pages[start:start + maximum_pages]:
        if result and end_pattern.search(page.text):
            break
        result.append(page)
    return result


def _supplementary_cashflow_text(pages: list[PageText]) -> str | None:
    marker = "将净利润调节为经营活动现金流量"
    for index, page in enumerate(pages):
        position = page.text.find(marker)
        if position < 0:
            continue
        joined = page.text[position:] + "\n" + "\n".join(
            follow.text for follow in pages[index + 1:index + 3]
        )
        end = re.search(r"不涉及现金收支|现金及现金等价物净变动", joined)
        if end:
            joined = joined[:end.start()]
        return joined
    return None


def _extract_supplementary_depreciation_amortization(text: str) -> tuple[float, str] | None:
    money = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
    specs = (
        ("固定资产折旧", r"固定资产折旧(?:\s*、\s*油气资产折耗)?(?:\s*、\s*生产\s*性生物资产折旧)?", True),
        ("使用权资产折旧", r"(?<!新增)使用权资产折旧", False),
        ("无形资产摊销", r"(?<!其他)无形资产摊销", True),
        ("长期待摊费用摊销", r"长期待摊费用摊销", True),
    )
    total = 0.0
    parts = []
    for name, pattern, required in specs:
        match = re.search(pattern, text)
        values = money.findall(text[match.end():match.end() + 120]) if match else []
        if not values:
            if required:
                return None
            continue
        value = float(values[0].replace(",", ""))
        total += value
        parts.append(f"{name}={value:g}")
    return total, "+".join(parts)


_FALLBACK_PREFIX = "合并报表回退派生: "


def _extract_income_cash_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    income_pages = _statement_page_range(pages, "合并利润表", "母公司利润表", 6)
    cash_pages = _statement_page_range(pages, "合并现金流量表", "母公司现金流量表", 8)
    balance_pages = _statement_page_range(pages, "合并资产负债表", "合并利润表", 8)
    if not income_pages:
        return []
    income = {
        "operating_cost": _find_statement_fact(income_pages, r"营业总成本"),
        "operating_profit": _find_statement_fact(income_pages, r"营业利润"),
        "profit_total": _find_statement_fact(income_pages, r"利润总额"),
        "interest_expense": _find_statement_fact(income_pages, r"利息费用"),
        "net_profit": _find_statement_fact(income_pages, r"五\s*、\s*净利润[（(]净亏损以"),
        "income_tax": _find_statement_fact(
            income_pages,
            r"所得税费用(?!\s*[-–—/\s]*[一-鿿、]{0,12}(?:费用|成本|收入|支出|收益|利润|税金))",
        ),
        "rd_expense": _find_statement_fact(
            income_pages,
            r"研发费用(?!率)(?!\s*[-–—/\s]*[一-鿿、]{0,12}(?:费用|成本|收入|支出|收益|利润|税金))",
        ),
    }
    cash = {
        "operating_cash_inflow": _find_statement_fact(cash_pages, r"经营活动现金流入小计"),
        "operating_cashflow_net": _find_statement_fact(cash_pages, r"经营活动产生的\s*现金流\s*量净额"),
    }
    balance = {
        "assets": _find_statement_fact(balance_pages, r"资产总计"),
        "liabilities": _find_statement_fact(balance_pages, r"(?<!流动)(?<!非流动)负债合计"),
        "current_liabilities": _find_statement_fact(balance_pages, r"(?<!非)流动负债合计"),
        "equity": _find_equity_fact(balance_pages),
    }
    if not _accounting_identity_holds(balance.get("assets"), balance.get("liabilities"), balance.get("equity")):
        balance = {}
    elif not _subsumption_consistent(balance.get("liabilities"), balance.get("current_liabilities")):
        balance["liabilities"] = None
        balance["current_liabilities"] = None
    revenue = None
    revenue_page = 0
    for index, page in enumerate(pages):
        in_summary = _is_summary_section_page(page.text) or (
            index > 0 and _is_summary_section_page(pages[index - 1].text) and "营业收入" not in pages[index - 1].text
        )
        parsed = _extract_summary_revenue(page.text, in_summary)
        if parsed:
            revenue, _, _ = parsed
            revenue_page = page.page
            break
    if revenue is None or revenue == 0:
        return []
    result = []
    def add(code: str, value: float, used: list[StatementFact]) -> None:
        result.append((
            code, value, max([item.page for item in used] + [revenue_page]),
            "合并利润/现金流量表自动派生: 营业收入=" + f"{revenue:g} | " +
            " | ".join(item.evidence for item in used),
        ))
    op = income["operating_profit"]
    if op:
        add("Q_G_OPERATING_MARGIN", op.values[0] / revenue * 100, [op])
        if len(op.values) >= 2 and op.values[1] != 0:
            magnitude_ratio = abs(op.values[0] / op.values[1])
            if .1 <= magnitude_ratio <= 10:
                add("Q_G_OPERATING_PROFIT_GROWTH", (op.values[0] - op.values[1]) / op.values[1] * 100, [op])
    cost = income["operating_cost"]
    if cost:
        add("Q_G_COST_REVENUE_RATE", cost.values[0] / revenue * 100, [cost])
    inflow = cash["operating_cash_inflow"]
    if inflow:
        cash_realization = inflow.values[0] / revenue * 100
        if 10 <= cash_realization <= 500:
            add("Q_G_CASH_REALIZATION", cash_realization, [inflow])
    net_cash, current_liabilities = cash["operating_cashflow_net"], balance.get("current_liabilities")
    if net_cash and current_liabilities and current_liabilities.values[0] != 0:
        add("Q_G_CASH_CURRENT_LIABILITY", net_cash.values[0] / current_liabilities.values[0] * 100, [net_cash, current_liabilities])
    profit, interest, assets = income["profit_total"], income["interest_expense"], balance.get("assets")
    if profit and interest:
        ebit = profit.values[0] + interest.values[0]
        if interest.values[0] != 0:
            add("Q_G_EBITDA_INTEREST", ebit / interest.values[0], [profit, interest])
        if assets and len(assets.values) >= 2 and (assets.values[0] + assets.values[1]) != 0:
            roa = ebit / ((assets.values[0] + assets.values[1]) / 2) * 100
            if -100 <= roa <= 100:
                add("Q_G_ROA", roa, [profit, interest, assets])
    net_profit, income_tax = income["net_profit"], income["income_tax"]
    supplement = _supplementary_cashflow_text(pages)
    depreciation = _extract_supplementary_depreciation_amortization(supplement) if supplement else None
    if net_profit and income_tax and interest and depreciation:
        da_total, da_evidence = depreciation
        ebitda = net_profit.values[0] + income_tax.values[0] + interest.values[0] + da_total
        margin = ebitda / revenue * 100
        if -1000 <= margin <= 1000:
            used = [net_profit, income_tax, interest]
            result.append((
                "Q_G_EBITDA_MARGIN", margin,
                max([item.page for item in used] + [revenue_page]),
                "合并利润/现金流量表自动派生: 营业收入=" + f"{revenue:g} | 折旧摊销=(" +
                da_evidence + ") | " + " | ".join(item.evidence for item in used),
            ))
    equity = balance.get("equity")
    if net_profit and equity and len(equity.values) >= 2 and (equity.values[0] + equity.values[1]) != 0:
        roe = net_profit.values[0] / ((equity.values[0] + equity.values[1]) / 2) * 100
        if -300 <= roe <= 300:
            result.append((
                "Q_G_ROE", roe, max(net_profit.page, equity.page),
                _FALLBACK_PREFIX + "净利润/平均净资产: " + net_profit.evidence + " | " + equity.evidence,
            ))
    rd_expense = income["rd_expense"]
    if rd_expense:
        rd_rate = rd_expense.values[0] / revenue * 100
        if 0 <= rd_rate <= 100:
            result.append((
                "Q_S_RD_RATE", rd_rate, max(rd_expense.page, revenue_page),
                _FALLBACK_PREFIX + "研发费用/营业收入: 营业收入=" + f"{revenue:g} | " + rd_expense.evidence,
            ))
    return result
