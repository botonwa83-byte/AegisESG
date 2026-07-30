from __future__ import annotations

import re
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
        re.compile(label + r"[^\d%]{0,35}" + NUMBER + r"\s*(" + units + r")", re.I),
        factors,
        confidence,
    )


RULES = (
    _rule("Q_E_GHG_INTENSITY", r"(?:温室气体|碳)排放强度", r"千克(?:二氧化碳当量|CO2e)?/万元|吨(?:二氧化碳当量|CO2e)?/万元", {"千克/万元": 1, "吨/万元": 1000}),
    _rule("Q_E_ENERGY_INTENSITY", r"(?:综合)?能源(?:消耗|消费)强度", r"千克标准煤/万元|吨标准煤/万元", {"千克标准煤/万元": 1, "吨标准煤/万元": 1000}),
    _rule("Q_E_NOX_INTENSITY", r"(?:氮氧化物|NOx)排放强度", r"克/万元|千克/万元", {"克/万元": 1, "千克/万元": 1000}),
    _rule("Q_E_SO2_INTENSITY", r"(?:二氧化硫|SO2)排放强度", r"克/万元|千克/万元", {"克/万元": 1, "千克/万元": 1000}),
    _rule("Q_E_WATER_INTENSITY", r"水资源(?:使用|消耗)强度", r"千克/万元|吨/万元|立方米/万元", {"千克/万元": 1, "吨/万元": 1000, "立方米/万元": 1000}),
    _rule("Q_E_SOLID_WASTE_INTENSITY", r"一般固体废物排放强度", r"千克/万元|吨/万元", {"千克/万元": 1, "吨/万元": 1000}),
    _rule("Q_S_SAFETY_INVEST_RATE", r"安全生产投入(?:占比|比例)", r"%|％", {"%": 1, "％": 1}),
    _rule("Q_S_RD_RATE", r"(?:研发(?:费用|投入)(?:占比|比例)|研发投入强度)", r"%|％", {"%": 1, "％": 1}),
    _rule("Q_G_DEBT_ASSET_RATE", r"资产负债率", r"%|％", {"%": 1, "％": 1}, .9),
)


DIRECT_RULES = (
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
        "Q_G_ROE",
        re.compile(r"加权平均净资产收益\s*率(?:\s*\(%\))?[^\d]{0,20}" + NUMBER, re.I),
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
    r"(?:/|per)\s*(?:RMB|CNY)\s*"
    r"(?P<scale>thousand|million|billion|100\s+million|10[,.]?000|1[,.]?000|10k|’000|'000)"
    r"(?:\s+(?:(?:of|in)\s+)?revenue)?"
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


def extract_batch_text_exports(
    document_index: str | Path,
    text_root: str | Path,
) -> tuple[list[Observation], dict[str, dict[str, int]]]:
    candidates: list[Observation] = []
    candidate_counts: Counter[str] = Counter()
    company_coverage: dict[str, set[str]] = defaultdict(set)
    text_root = Path(text_root)
    with Path(document_index).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        local = Path(row["local_path"])
        try:
            relative = local.relative_to("data/raw")
        except ValueError:
            relative = Path(row["company_code"]) / str(row["report_year"]) / local.name
        text_path = (text_root / relative).with_suffix(".txt")
        if not text_path.exists():
            continue
        items = extract_indicator_candidates(
            read_page_text_export(text_path), row["company_code"], row["company_name"],
            int(row["report_year"]), row["source_url"], row["local_path"],
        )
        candidates.extend(items)
        candidate_counts.update(item.indicator_code for item in items)
        for item in items:
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
        if re.search(r"近三年主要会计数据", page.text):
            summary_pages.add(page.page)
            if "营业收入" not in page.text and index + 1 < len(pages):
                summary_pages.add(pages[index + 1].page)
    for page in pages:
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
        for code, value, evidence, confidence in _extract_english_revenue_intensities(text):
            identity = (code, page.page, value)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(Observation(
                company_code=company_code, company_name=company_name, report_year=report_year,
                indicator_code=code, value=value, status=ValueStatus.PENDING,
                source_url=source_url, source_file=source_file, source_page=page.page,
                evidence_text=evidence, confidence=confidence,
            ))
        reduction = _extract_english_ghg_reduction(text, report_year)
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
    return candidates


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("（", "(").replace("）", ")")


def _canonical_unit(unit: str) -> str:
    compact = unit.replace("二氧化碳当量", "").replace("CO2e", "")
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
            scale = re.sub(r"\s+", " ", match.group("scale").lower())
            amount = scale_amounts.get(scale)
            if amount is None:
                continue
            mass_kg = 1 if compact_numerator in {"kg", "kilogram", "kilograms", "kgco2e", "kgco2-e"} else 1_000
            raw_value = float(match.group("value").replace(",", ""))
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
    if not re.search(rf"\b{report_year}\b[^\n]{{0,40}}\b{previous_year}\b", text):
        return None
    row = re.compile(
        r"(?i)\bTotal\s+(?:(?:Scope\s*1\s*(?:and|&|\+)\s*Scope\s*2\s*)?)"
        r"(?:GHG|greenhouse\s+gas)\s+emissions?"
        r"(?:\s*\(\s*Scope\s*1\s*(?:and|&|\+)\s*Scope\s*2\s*\))?\s*"
        r"(?:tCO[₂2](?:e|-e)?|tonnes?\s+of\s+(?:carbon\s+dioxide\s+equivalent|CO2e))\s+"
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


def _is_contextual_false_positive(code: str, text: str, match: re.Match[str]) -> bool:
    matched = match.group(0)
    if code in {"Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY"}:
        # A superscript footnote may appear between a table label and its unit, followed by
        # the actual current/prior-year values (e.g. "排放强度3 吨/万元 0.02 0.03").
        if re.match(r"\s*\d", text[match.end():match.end() + 12]):
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
    if value < 0:
        return False
    percentage_codes = {
        "Q_E_ALTERNATIVE_WATER_RATE", "Q_S_SAFETY_INVEST_RATE", "Q_S_RD_RATE",
        "Q_S_DONATION_RATE", "Q_G_DEBT_ASSET_RATE", "Q_G_ROE",
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
    if any(token in matched for token in ("同比", "增加", "减少", "提升", "下降", "变动", "较上年")):
        return True
    return False


def _extract_revenue_growth(raw_text: str, in_summary_section: bool = False) -> list[tuple[float, str]]:
    parsed = _extract_summary_revenue(raw_text, in_summary_section)
    if parsed is None:
        return []
    current, previous, evidence = parsed
    growth = (current - previous) / previous * 100
    return [(growth, evidence)] if -100 <= growth <= 1000 else []


def _extract_summary_revenue(raw_text: str, in_summary_section: bool = False) -> tuple[float, float, str] | None:
    if not in_summary_section and not re.search(r"(?:近三年主要会计数据|[(（]一[)）]\s*主要会计数据)", raw_text):
        return None
    repaired = _repair_wrapped_numbers(raw_text)
    number = re.compile(r"[+-]?[\d,]+(?:\.\d+)?")
    match = re.search(r"营业收入(?P<body>.{0,2000}?)(?:利润总额|归属于上市)", repaired, re.S)
    if not match:
        return None
    evidence = "营业收入" + match.group("body")
    values = [float(item.replace(",", "")) for item in number.findall(evidence)]
    if len(values) < 2 or values[1] == 0:
        return None
    scale = 10_000 if re.search(r"单位\s*[：:]\s*万元", raw_text) else 1
    return values[0] * scale, values[1] * scale, re.sub(r"\s+", " ", evidence)[:400]


def _repair_wrapped_numbers(raw_text: str) -> str:
    repaired = re.sub(r"(?<=[\d,])\s*\n\s*(?=[.,])", "", raw_text)
    return re.sub(
        r"(?m)(^|[ \t])([0-9,]+)\s*\n\s*(?=\d+\.\d+)",
        lambda match: match.group(1) + match.group(2),
        repaired,
    )


def _extract_balance_sheet_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    title = re.compile(r"(?m)^\s*合并资产负债表\s*$")
    profit_title = re.compile(r"(?m)^\s*合并利润表\s*$")
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
        "equity": r"(?:股东权益|所有者权益(?:（或股东权益）|\(或股东权益\))?)合计",
        "current_assets": r"流动资产合计",
        "accounts_receivable": r"(?<!其他)应收账款",
        "inventory": r"存货",
    }
    facts = {name: _find_statement_fact(statement_pages, pattern) for name, pattern in labels.items()}
    revenue = None
    revenue_page = None
    for index, page in enumerate(pages):
        in_summary = "近三年主要会计数据" in page.text or (
            index > 0 and "近三年主要会计数据" in pages[index - 1].text and "营业收入" not in pages[index - 1].text
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
        add("Q_G_DEBT_ASSET_RATE", liabilities.values[0] / assets.values[0] * 100, ("liabilities", "assets"))
    if revenue is not None and assets and len(assets.values) >= 2:
        add("Q_G_ASSET_TURNOVER", revenue / ((assets.values[0] + assets.values[1]) / 2), ("assets",))
    current_assets = facts.get("current_assets")
    if revenue is not None and current_assets and len(current_assets.values) >= 2:
        add("Q_G_CURRENT_ASSET_TURNOVER", revenue / ((current_assets.values[0] + current_assets.values[1]) / 2), ("current_assets",))
    receivable = facts.get("accounts_receivable")
    if revenue is not None and receivable and len(receivable.values) >= 2 and (receivable.values[0] + receivable.values[1]) != 0:
        add("Q_G_AR_TURNOVER", revenue / ((receivable.values[0] + receivable.values[1]) / 2), ("accounts_receivable",))
    inventory = facts.get("inventory")
    if receivable and inventory and current_assets and current_assets.values[0] != 0:
        add("Q_G_TWO_FUNDS_RATE", (receivable.values[0] + inventory.values[0]) / current_assets.values[0] * 100, ("accounts_receivable", "inventory", "current_assets"))
    equity = facts.get("equity")
    if equity and len(equity.values) >= 2 and equity.values[1] != 0:
        add("Q_G_CAPITAL_ACCUMULATION", (equity.values[0] - equity.values[1]) / equity.values[1] * 100, ("equity",))
    return result


def _find_statement_fact(pages: list[PageText], label_pattern: str) -> StatementFact | None:
    money = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")
    label = re.compile(label_pattern)
    for page in pages:
        repaired = _repair_wrapped_numbers(page.text)
        for match in label.finditer(repaired):
            fragment = repaired[match.start():match.end() + 180]
            values = tuple(float(item.replace(",", "")) for item in money.findall(fragment))
            if values:
                return StatementFact(values[:2], page.page, re.sub(r"\s+", " ", fragment)[:220])
    return None


def _extract_english_balance_sheet_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    title = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?statement of financial position(?:\s|$)|^\s*consolidated balance sheet\s*$",
    )
    end = re.compile(r"(?mi)^\s*(?:consolidated\s+)?statement of (?:profit|income|changes|cash flows?)")
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
        equity = _find_english_statement_fact(statement_pages, r"Total equity(?!\s+and)")
        revenue = _find_english_revenue_fact(pages)
        profit = _find_english_income_fact(pages, r"(?:Profit|Loss) for the year")
        profit_before_tax = _find_english_income_fact(
            pages, r"(?:Profit|Loss) before (?:income )?tax(?:ation)?",
        )
        finance_cost = _find_english_income_fact(
            pages, r"(?:Finance costs?|Interest expenses?)",
        )
        income_tax = _find_english_income_fact(
            pages, r"(?:Income tax expense|Taxation)",
        )
        depreciation_amortisation = _find_english_cashflow_fact(
            pages, r"Depreciation and amorti[sz]ation",
        )
        result = []
        if assets and liabilities and assets.values[0] > 0:
            value = liabilities.values[0] / assets.values[0] * 100
            if 0 <= value <= 1000:
                evidence = "English consolidated statement derived: " + liabilities.evidence + " | " + assets.evidence
                result.append(("Q_G_DEBT_ASSET_RATE", value, max(assets.page, liabilities.page), evidence))
        if assets and revenue and len(assets.values) >= 2:
            average_assets = (assets.values[0] + assets.values[1]) / 2
            if average_assets != 0:
                result.append((
                    "Q_G_ASSET_TURNOVER", revenue.values[0] / average_assets,
                    max(assets.page, revenue.page), "English consolidated statements derived: " +
                    revenue.evidence + " | " + assets.evidence,
                ))
        if current_assets and revenue and len(current_assets.values) >= 2:
            average_current_assets = (current_assets.values[0] + current_assets.values[1]) / 2
            if average_current_assets != 0:
                result.append((
                    "Q_G_CURRENT_ASSET_TURNOVER", revenue.values[0] / average_current_assets,
                    max(current_assets.page, revenue.page), "English consolidated statements derived: " +
                    revenue.evidence + " | " + current_assets.evidence,
                ))
        if receivable and revenue and len(receivable.values) >= 2:
            average_receivable = (receivable.values[0] + receivable.values[1]) / 2
            if average_receivable > 0:
                result.append((
                    "Q_G_AR_TURNOVER", revenue.values[0] / average_receivable,
                    max(receivable.page, revenue.page), "English consolidated statements derived: " +
                    revenue.evidence + " | " + receivable.evidence,
                ))
        if receivable and inventory and current_assets and current_assets.values[0] > 0:
            two_funds = (receivable.values[0] + inventory.values[0]) / current_assets.values[0] * 100
            if 0 <= two_funds <= 1000:
                result.append((
                    "Q_G_TWO_FUNDS_RATE", two_funds,
                    max(receivable.page, inventory.page, current_assets.page),
                    "English consolidated statement derived: " + receivable.evidence + " | " +
                    inventory.evidence + " | " + current_assets.evidence,
                ))
        if inventory and current_assets and current_liabilities and current_liabilities.values[0] > 0:
            quick_ratio = (current_assets.values[0] - inventory.values[0]) / current_liabilities.values[0] * 100
            if -1000 <= quick_ratio <= 1000:
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
                if -1000 <= roe <= 1000:
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
                    if -1000 <= roa <= 1000:
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
    return best_result


def _find_english_revenue_fact(pages: list[PageText]) -> StatementFact | None:
    return _find_english_income_fact(
        pages, r"(?:I\.\s*)?(?:(?:Total\s+)?Operating\s+)?Revenue",
    )


def _find_english_income_fact(pages: list[PageText], label_pattern: str) -> StatementFact | None:
    title = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?statement of (?:profit or loss|profit and loss|income)(?:\s|$)",
    )
    end = re.compile(r"(?mi)^\s*(?:consolidated\s+)?statement of (?:financial position|changes|cash flows?)")
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
    label = re.compile(rf"(?mi)^\s*{label_pattern}\b(?P<body>[^\n]*)$")
    number = re.compile(r"\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?")
    for page in pages:
        for match in label.finditer(_repair_wrapped_numbers(page.text)):
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
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                return StatementFact(tuple(values[:2]), page.page, evidence[:220])
    return None


def _extract_english_income_indicators(pages: list[PageText]) -> list[tuple[str, float, int, str]]:
    title = re.compile(
        r"(?mi)^\s*(?:consolidated\s+)?statement of (?:profit or loss|profit and loss|income)(?:\s|$)",
    )
    end = re.compile(r"(?mi)^\s*(?:consolidated\s+)?statement of (?:financial position|changes|cash flows?)")
    for start in (index for index, page in enumerate(pages) if title.search(page.text)):
        statement_pages = []
        for page in pages[start:start + 5]:
            if statement_pages and end.search(page.text):
                break
            statement_pages.append(page)
        revenue = _find_english_statement_fact(
            statement_pages, r"(?:I\.\s*)?(?:(?:Total\s+)?Operating\s+)?Revenue",
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
        )
        if research:
            rd_rate = abs(research.values[0]) / abs(revenue.values[0]) * 100
            if 0 <= rd_rate <= 100:
                result.append((
                    "Q_S_RD_RATE", rd_rate, max(revenue.page, research.page),
                    "English consolidated income statement derived: " +
                    research.evidence + " | " + revenue.evidence,
                ))
        total_costs = _find_english_statement_fact(
            statement_pages, r"(?:II\.\s*)?(?:Total operating costs?|Total operating expenses|Total costs and expenses)",
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


def _statement_page_range(
    pages: list[PageText], start_title: str, end_title: str, maximum_pages: int = 8,
) -> list[PageText]:
    start_pattern = re.compile(rf"(?m)^\s*{start_title}\s*$")
    end_pattern = re.compile(rf"(?m)^\s*{end_title}\s*$")
    start = next((index for index, page in enumerate(pages) if start_pattern.search(page.text)), None)
    if start is None:
        return []
    result = []
    for page in pages[start:start + maximum_pages]:
        if result and end_pattern.search(page.text):
            break
        result.append(page)
    return result


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
    }
    cash = {
        "operating_cash_inflow": _find_statement_fact(cash_pages, r"经营活动现金流入小计"),
        "operating_cashflow_net": _find_statement_fact(cash_pages, r"经营活动产生的\s*现金流\s*量净额"),
    }
    balance = {
        "assets": _find_statement_fact(balance_pages, r"资产总计"),
        "current_liabilities": _find_statement_fact(balance_pages, r"流动负债合计"),
    }
    revenue = None
    revenue_page = 0
    for index, page in enumerate(pages):
        in_summary = "近三年主要会计数据" in page.text or (
            index > 0 and "近三年主要会计数据" in pages[index - 1].text and "营业收入" not in pages[index - 1].text
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
        add("Q_G_CASH_REALIZATION", inflow.values[0] / revenue * 100, [inflow])
    net_cash, current_liabilities = cash["operating_cashflow_net"], balance["current_liabilities"]
    if net_cash and current_liabilities and current_liabilities.values[0] != 0:
        add("Q_G_CASH_CURRENT_LIABILITY", net_cash.values[0] / current_liabilities.values[0] * 100, [net_cash, current_liabilities])
    profit, interest, assets = income["profit_total"], income["interest_expense"], balance["assets"]
    if profit and interest:
        ebit = profit.values[0] + interest.values[0]
        if interest.values[0] != 0:
            add("Q_G_EBITDA_INTEREST", ebit / interest.values[0], [profit, interest])
        if assets and len(assets.values) >= 2 and (assets.values[0] + assets.values[1]) != 0:
            add("Q_G_ROA", ebit / ((assets.values[0] + assets.values[1]) / 2) * 100, [profit, interest, assets])
    return result
