"""Derive 投入/捐赠占营收 social rates from totals and consolidated revenue.

Same methodology discipline as env_intensity: consolidated revenue from the
annual report, explicit group-scope totals, consistent-source checks,
suppression when the company already discloses the rate, and plausible bounds.
环保/安全生产投入与对外捐赠总额以报告期单值为准：累计口径、预算/计划口径、
强度口径一律拒绝。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .env_intensity import (
    CompanyDocument,
    _RevenueFact,
    _chinese_consolidated_revenue,
    _distinct,
    _english_consolidated_revenue,
)
from .extraction import _chinese_year_table_mode, _normalize_kangxi
from .models import Observation, ValueStatus

_CN_NUMBER = r"[\d,]+(?:\.\d+)?"
# 元口径统一为人民币元
_MONEY_UNITS: tuple[tuple[str, float], ...] = (
    ("亿元人民币", 100_000_000.0), ("百万元人民币", 1_000_000.0),
    ("万元人民币", 10_000.0), ("千元人民币", 1_000.0),
    ("亿元", 100_000_000.0), ("百万元", 1_000_000.0), ("万元", 10_000.0), ("千元", 1_000.0), ("元", 1.0),
)

# (指标, 标签, 合理区间%)：环保投入/安全生产投入/对外捐赠占营业收入比例
_CN_INVEST_RULES: tuple[tuple[str, str, tuple[float, float]], ...] = (
    (
        "Q_S_ENV_INVEST_RATE",
        r"(?<!累计)(?<!历年)环保(?:总)?投入(?:金额)?(?!\s*强度)(?!密度)",
        (0.001, 50.0),
    ),
    (
        "Q_S_SAFETY_INVEST_RATE",
        r"(?<!累计)(?<!历年)(?:职业健康(?:与)?)?安全生产(?:总)?投入(?:金额)?(?!\s*强度)(?!密度)",
        (0.0001, 30.0),
    ),
    (
        "Q_S_DONATION_RATE",
        r"(?<!接受)(?<!累计)(?<!历年)对外捐赠|公益捐赠(?:总额|支出)?(?!支出超出)|慈善捐赠(?:总额)?",
        (0.00001, 10.0),
    ),
)

_CN_BAD_BETWEEN = re.compile(r"约|大约|增加|减少|降至|降低|下降|增长|同比|目标|计划|规划|控制在|以内|超|超过|近|预算|拟")
_CN_BAD_PREFIX = re.compile(r"目标|计划|规划|减少|降低|增加|预计|预测|预算|拟|力争")
_CN_PARTIAL_SCOPE = re.compile(
    r"\d+\s*家[^。；\n]{0,8}(?:企业|电厂|子公司|公司|项目|基地|工厂)|所属[^。；\n]{0,8}(?:企业|电厂|子公司|项目|基地|工厂)|子公司|分公司|项目公司|生产基地"
)

# 公司已披露占营收比例（即使版式未被直接规则解析）时抑制派生
_SUPPRESS_RULES = {
    "Q_S_ENV_INVEST_RATE": re.compile(
        r"环保(?:总)?投入[\s\S]{0,24}占[\s\S]{0,12}(?:营业收入|营收|收入比例|总比)", re.I,
    ),
    "Q_S_SAFETY_INVEST_RATE": re.compile(
        r"安全生产投入[\s\S]{0,24}占[\s\S]{0,12}(?:营业收入|营收|收入比例|总比)", re.I,
    ),
    "Q_S_DONATION_RATE": re.compile(
        r"(?:对外|公益|慈善)?捐赠[\s\S]{0,24}占[\s\S]{0,12}(?:营业收入|营收|收入比例|总比)", re.I,
    ),
}

# 营业外支出等附注表头：本期发生额为首列
_CN_NOTE_HEADER = re.compile(r"本期发生额[\s\S]{0,30}上期发生额|本期金额[\s\S]{0,30}上期金额")


@dataclass(frozen=True)
class _InvestTotal:
    indicator_code: str
    total_rmb: float
    source_file: str
    source_page: int
    evidence: str


def _unit_factors() -> dict[str, float]:
    return {unit: factor for unit, factor in _MONEY_UNITS}


def _cn_invest_rows(text: str, report_year: int, source_file: str, page: int) -> list[_InvestTotal]:
    """Parse 投入/捐赠 totals from Chinese disclosures.

    Year-table rows need an explicit year header; note tables (营业外支出等) with
    本期发生额/上期发生额 headers are current-first; single-value, value-first and
    group-anchored narrative forms follow the same guard discipline as env totals.
    """
    text = _normalize_kangxi(text)
    mode = _chinese_year_table_mode(text, report_year)
    note_mode = bool(_CN_NOTE_HEADER.search(text))
    results: list[_InvestTotal] = []
    forms: list[str] = []
    factors = _unit_factors()
    unit_pattern = "(?:" + "|".join(unit for unit, _ in _MONEY_UNITS) + ")"
    for code, label, _bounds in _CN_INVEST_RULES:
        row_patterns: list[tuple[str, str]] = []
        if mode == "current-first":
            row_patterns.append((
                "current-first",
                rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})(?:\s+(?:{_CN_NUMBER}|/|-|—)){{0,2}}\s*$",
            ))
        elif mode == "current-last":
            row_patterns.append((
                "current-last",
                rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*"
                rf"(?:{_CN_NUMBER}|/|-|—)(?:\s+(?:{_CN_NUMBER}|/|-|—))?\s+(?P<current>{_CN_NUMBER})\s*$",
            ))
        if note_mode:
            # 附注行：对外捐赠 224,016.92 97,606.72 224,016.92（本期发生额为首列，单位在表头）
            row_patterns.append((
                "note-current-first",
                rf"(?m)^\s*(?:{label})\s+(?P<current>{_CN_NUMBER})(?:\s+(?:{_CN_NUMBER}|/|-|—)){{0,3}}\s*$",
            ))
        row_patterns.append((
            "single-value",
            rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s*$",
        ))
        # 竖排KPI：安全生产投入\n万元\n41.36 或 万元\n/\n/\n41.36
        row_patterns.append((
            "vertical-unit-value",
            rf"(?m)^\s*(?:{label})\s*\n\s*(?P<unit>{unit_pattern})\s*\n\s*"
            rf"(?:(?:{_CN_NUMBER}|/|-|—)\s*\n\s*){{0,2}}(?P<current>{_CN_NUMBER})\s*$",
        ))
        # 叙述：全年安全生产投入金额达 1,103.05 万元
        row_patterns.append((
            "year-narrative",
            rf"(?:全年|报告期(?:内)?|本年度)(?:{label})\s*(?:金额)?(?:达|为|共计|共|：|:)?\s*"
            rf"(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})",
        ))
        row_patterns.append((
            "value-first",
            # 允许行尾同比/增减叙述（如“安全生产投入金额 7,377.09 万元 同比增长 41.32%”）
            rf"(?m)^\s*(?:{label})\s*(?:为|达到|：|:)?\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})"
            rf"(?![ \t]*(?:{_CN_NUMBER}|%))"
            rf"(?:\s+(?:同比|较|比上年|增长|下降|减少|增加)[^\n]*)?"
            rf"\s*[。；;，,、]?\s*$",
        ))
        row_patterns.append((
            "narrative",
            rf"(?m)(?:公司|本集团|集团)\s*(?:{label})\s*(?:为|达到|共计|共|：|:)?\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})(?![ \t]*(?:{_CN_NUMBER}|%))(?=\s*(?:$|[，。；,、]))",
        ))
        row_patterns.append((
            "statement",
            rf"(?m)(?:{label})\s*(?:为|达到|共计|共|：|:)?\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})"
            rf"(?![ \t]*(?:{_CN_NUMBER}|%))(?![ \t]*(?:以上|以内|以下|左右|余|超|的))(?=\s*(?:$|[；;，,。、]|\s+[\u4e00-\u9fff（(]))",
        ))
        # 附注胶粘行：对外捐赠 55,114.26 53,604.03 55,114.26 非流动资产…（本期=非经常性损益，
        # 首值=第三值为结构锚点；单位须本页表头“单位：元/万元”明示，不猜单位）
        row_patterns.append((
            "note-glued",
            rf"(?m)(?:{label})\s+(?P<current>{_CN_NUMBER})(?:\s+(?P<v2>{_CN_NUMBER}))?(?:\s+(?P<v3>{_CN_NUMBER}))?"
            rf"(?=\s+(?:[\u4e00-\u9fff（(]|/)|\s*$)",
        ))
        for form, row in row_patterns:
            if form in {"current-first", "current-last"} and mode is None:
                continue
            if form == "note-current-first" and not note_mode:
                continue
            for match in re.finditer(row, text):
                if form in {"narrative", "statement", "year-narrative"}:
                    sentence_start = max(text.rfind(mark, 0, match.start()) for mark in ("。", "；", ";")) + 1
                    window = text[max(sentence_start, match.start() - 120):match.start()]
                    if _CN_BAD_PREFIX.search(window) or _CN_PARTIAL_SCOPE.search(window):
                        continue
                else:
                    prefix = text[max(0, match.start() - 24):match.start()]
                    if _CN_BAD_PREFIX.search(prefix):
                        continue
                if form == "statement":
                    # 行首情形仅当value-first确实覆盖（单位后仅剩终止符到行尾）时让位，
                    # 行首胶粘行（“环保投入 4,153.91万元 环境领域…”）仍由statement承接
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    if not text[line_start:match.start()].strip():
                        rest = text[match.end():text.find("\n", match.end()) if "\n" in text[match.end():] else len(text)]
                        if re.fullmatch(r"\s*[。；;，,、]?\s*", rest):
                            continue
                between = text[match.start():match.start("current")]
                if _CN_BAD_BETWEEN.search(between):
                    continue
                if form == "note-glued":
                    v3 = match.group("v3")
                    current_raw = match.group("current").replace(",", "")
                    if v3 is None:
                        # 两值附注行须本页有本期发生额表头锚定首列
                        if not note_mode:
                            continue
                    elif abs(float(v3.replace(",", "")) - float(current_raw)) > 1e-9:
                        continue
                    header_unit = re.search(r"单位[：:]\s*(亿元|百万元|万元|千元|元)", text)
                    if not header_unit:
                        continue
                    factor = factors[header_unit.group(1)]
                    total_rmb = float(current_raw) * factor
                    if total_rmb <= 0:
                        continue
                    evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                    results.append(_InvestTotal(
                        code, total_rmb, source_file, page,
                        f"Chinese {form} social investment row: {evidence[:220]}",
                    ))
                    forms.append(form)
                    continue
                if form == "note-current-first":
                    # 附注单位在表头“单位：元/万元”，行内不带单位
                    header_unit = re.search(r"单位[：:]\s*(亿元|百万元|万元|千元|元)", text)
                    if not header_unit:
                        continue
                    factor = factors[header_unit.group(1)]
                else:
                    unit_key = re.sub(r"\s+", "", match.group("unit"))
                    factor = factors.get(unit_key)
                    if factor is None:
                        continue
                total_rmb = float(match.group("current").replace(",", "")) * factor
                if total_rmb <= 0:
                    continue
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                results.append(_InvestTotal(
                    code, total_rmb, source_file, page,
                    f"Chinese {form} social investment row: {evidence[:220]}",
                ))
                forms.append(form)
    keep = [True] * len(results)
    for code in {item.indicator_code for item in results}:
        anchored = [
            item.total_rmb for item, form in zip(results, forms)
            if item.indicator_code == code and form in {"current-first", "current-last", "note-current-first", "note-glued"}
        ]
        if not anchored:
            continue
        for index, (item, form) in enumerate(zip(results, forms)):
            if item.indicator_code != code or form in {"current-first", "current-last", "note-current-first", "note-glued"}:
                continue
            if all(
                abs(item.total_rmb - value) > max(abs(item.total_rmb), abs(value), 1.0) * 1e-4
                for value in anchored
            ):
                keep[index] = False
    return [item for item, retained in zip(results, keep) if retained]


def derive_social_invest_candidates(
    company_code: str,
    company_name: str,
    report_year: int,
    documents: list[CompanyDocument],
    skip_indicators: frozenset[str] = frozenset(),
) -> list[Observation]:
    """Derive 投入/捐赠总额÷营收 rates for one company and report year."""
    revenues: list[_RevenueFact] = []
    totals: dict[str, list[_InvestTotal]] = {}
    for doc in documents:
        if doc.document_type == "annual_report":
            revenue = _chinese_consolidated_revenue(doc) or _english_consolidated_revenue(doc)
            if revenue:
                revenues.append(revenue)
        for page in doc.pages:
            for total in _cn_invest_rows(page.text, report_year, doc.source_file, page.page):
                totals.setdefault(total.indicator_code, []).append(total)
    if not revenues or _distinct([item.revenue_rmb for item in revenues]):
        return []
    revenue = revenues[0]
    full_text = "\n".join(page.text for doc in documents for page in doc.pages)
    results: list[Observation] = []
    for code, items in sorted(totals.items()):
        if code in skip_indicators:
            continue
        if _distinct([item.total_rmb for item in items]):
            continue
        suppress = _SUPPRESS_RULES.get(code)
        if suppress and suppress.search(full_text):
            continue
        bounds = next(rule[2] for rule in _CN_INVEST_RULES if rule[0] == code)
        total = items[0]
        value = total.total_rmb * 100 / revenue.revenue_rmb
        if not bounds[0] <= value <= bounds[1]:
            continue
        evidence = (
            f"中文投入占比派生: {total.evidence} ({total.source_file} 第{total.source_page}页) "
            f"| 营业收入={revenue.revenue_rmb:g}元 ({revenue.source_file} 第{revenue.source_page}页)"
        )
        results.append(Observation(
            company_code=company_code, company_name=company_name, report_year=report_year,
            indicator_code=code, value=value, status=ValueStatus.PENDING,
            source_url=next(
                doc.source_url for doc in documents if doc.source_file == total.source_file
            ),
            source_file=total.source_file, source_page=total.source_page,
            evidence_text=evidence[:500], confidence=.9,
        ))
    return results
