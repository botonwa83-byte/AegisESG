"""跨表环境强度派生：同公司、同报告期、同集团口径的总量 ÷ 年报合并营业收入。

纪律（与MEMORY.md一致）：
- 分母只取年报合并口径营业收入（中文主要会计数据摘要或英文合并损益表RMB口径）；
- 分子只取集团层面环境总量（GHG/综合能源/用水），拒绝范围一/二单口径、直接/间接
  分段、人均、强度、产值、产量、发电量及股权比例（equity basis）口径；
- 同指标出现不一致总量或多个不一致营收时放弃派生，不静默选值；
- 公司已有该指标候选时抑制派生，不制造口径冲突组；
- 派生值必须通过量级防护区间，拦截单位错配与宏观叙事误配。
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .extraction import (
    PageText,
    _chinese_year_table_mode,
    _extract_summary_revenue,
    _find_english_statement_fact,
    _is_summary_section_page,
    _normalize_kangxi,
    _repair_wrapped_numbers,
)
from .models import Observation, ValueStatus


@dataclass(frozen=True)
class CompanyDocument:
    document_type: str
    pages: list[PageText]
    source_url: str
    source_file: str


@dataclass(frozen=True)
class _EnvTotal:
    indicator_code: str
    total_kg: float
    source_file: str
    source_page: int
    evidence: str


@dataclass(frozen=True)
class _RevenueFact:
    revenue_rmb: float
    source_file: str
    source_page: int
    evidence: str


_CN_NUMBER = r"[\d,]+(?:\.\d+)?"

# 指标 -> (中文总量标签, 单位->千克换算, 派生强度合理区间千克/万元)
_CN_TOTAL_RULES: tuple[tuple[str, str, tuple[tuple[str, float], ...], tuple[float, float]], ...] = (
    (
        "Q_E_GHG_INTENSITY",
        r"(?<!范围一)(?<!范围二)(?<!减少的)(?<!直接)(?<!间接)温室气体排放总量(?:\s*[（(]含?范围\s*[一1]\s*[、和+及]\s*范围\s*[二2][）)])?|温室气体总排放量",
        (("百万吨二氧化碳当量", 1_000_000_000.0), ("万吨二氧化碳当量", 10_000_000.0), ("吨二氧化碳当量", 1_000.0), ("万吨", 10_000_000.0), ("吨", 1_000.0)),
        (0.001, 200_000.0),
    ),
    (
        "Q_E_ENERGY_INTENSITY",
        r"综合能源(?:消耗|消费)总量|综合能耗总量|(?<!每百万营收)(?<!直接)(?<!间接)(?<!清洁)(?<!可再生)能源(?:消耗|消费)总量",
        (("万吨标准煤", 10_000_000.0), ("吨标准煤", 1_000.0), ("千克标准煤", 1.0)),
        (0.0001, 100_000.0),
    ),
    (
        "Q_E_WATER_INTENSITY",
        r"(?<!循环)(?<!回用)(?<!重复利用)用水总量|(?<!循环)总用水量|耗水总量|新鲜水用水总量|新鲜水总量",
        (("万立方米", 10_000_000.0), ("立方米", 1_000.0), ("万吨", 10_000_000.0), ("吨", 1_000.0)),
        (0.001, 5_000_000.0),
    ),
    # 污染物/废弃物：SO2/NOx/PM方法论口径为克/万元，其余为千克/万元
    (
        "Q_E_SO2_INTENSITY",
        r"(?<!去除)(?<!削减)二氧化硫(?:排放)?总量|二氧化硫排放量",
        (("吨", 1_000.0), ("千克", 1.0)),
        (0.001, 100_000.0),
    ),
    (
        "Q_E_NOX_INTENSITY",
        r"(?<!去除)(?<!削减)氮氧化物(?:排放)?总量|氮氧化物排放量",
        (("吨", 1_000.0), ("千克", 1.0)),
        (0.001, 100_000.0),
    ),
    (
        "Q_E_PM_INTENSITY",
        r"(?:颗粒物|烟尘)(?:排放)?总量|(?:颗粒物|烟尘)排放量",
        (("吨", 1_000.0), ("千克", 1.0)),
        (0.0001, 20_000.0),
    ),
    (
        "Q_E_WASTEWATER_INTENSITY",
        r"(?<!循环)(?<!回用)(?<!再生)(?<!脱硫)(?<!减少)(?<!削减)(?:工业)?废水(?:排放)?总量|(?<!循环)(?<!回用)(?<!再生)(?<!脱硫)(?<!减少)(?<!削减)废水排放量",
        (("万立方米", 10_000_000.0), ("立方米", 1_000.0), ("万吨", 10_000_000.0), ("吨", 1_000.0)),
        (0.001, 5_000_000.0),
    ),
    (
        "Q_E_SOLID_WASTE_INTENSITY",
        r"一般(?:工业)?固体废物(?:产生|排放)?总?量|一般固废(?:产生|排放)?总?量|无害废弃物(?:产生|排放)?总?量",
        (("万吨", 10_000_000.0), ("吨", 1_000.0), ("千克", 1.0)),
        (0.001, 5_000_000.0),
    ),
    (
        "Q_E_HAZ_WASTE_INTENSITY",
        r"危险废物(?:产生|排放)?总?量|危废(?:产生|排放)?总?量",
        (("万吨", 10_000_000.0), ("吨", 1_000.0), ("千克", 1.0)),
        (0.0001, 100_000.0),
    ),
)

# 标签与数值之间/标签之前出现这些措辞时，该数值不是报告期实际总量
_CN_BAD_BETWEEN = re.compile(r"约|大约|增加|减少|降至|降低|下降|增长|同比|目标|计划|规划|控制在|以内|超|超过|近")
_CN_BAD_PREFIX = re.compile(r"目标|计划|规划|减少|降低|增加|减排(?!(?:标准|任务|改造|要求|措施|工作|项目|工程|责任))|预计|预测")
# 叙述式/陈述式句型前缀出现部分主体时，该总量不是集团合并口径
_CN_PARTIAL_SCOPE = re.compile(
    r"\d+\s*家[^。；\n]{0,8}(?:企业|电厂|子公司|公司|项目|基地|工厂)|所属[^。；\n]{0,8}(?:企业|电厂|子公司|项目|基地|工厂)|子公司|分公司|项目公司|生产基地"
)

# 温室气体总量口径核验：方法论口径为范围一+范围二。总量行未显式标注范围时，
# 同页出现范围三正值即拒绝；范围一/二行可解析时要求 总量≈范围一+范围二 闭环
_CN_SCOPE3_POSITIVE = re.compile(
    r"范围三[\s\S]{0,60}?(?:百万吨二氧化碳当量|万吨二氧化碳当量|吨二氧化碳当量|万吨|吨)\s*(?:[-—/]\s*)*([\d,]+(?:\.\d+)?)",
)
_EN_SCOPE3_POSITIVE = re.compile(
    r"Scope\s*3[\s\S]{0,60}?(?:kilotonnes|tCO2e|tCO₂e|tonnes|kt)\s*(?:[-—/]\s*)*([\d,]+(?:\.\d+)?)",
    re.I,
)
_CN_SCOPE12_LABELS = (
    r"范围\s*一\s*温室气体排放(?:总)?量|直接温室气体排放(?:总)?量?\s*[（(]\s*范围\s*[一1]\s*[)）]",
    r"范围\s*二\s*温室气体排放(?:总)?量|间接温室气体排放(?:总)?量?\s*[（(]\s*范围\s*[二2]\s*[)）]",
)
_EN_SCOPE12_LABELS = (
    r"Scope\s*1\s+(?:Greenhouse\s+Gas|GHG)\s+[Ee]missions?|Direct\s+(?:GHG\s+)?[Ee]missions?\s*\(?\s*Scope\s*1\s*\)?",
    r"Scope\s*2\s+(?:Greenhouse\s+Gas|GHG)\s+[Ee]missions?|Indirect\s+(?:GHG\s+)?[Ee]missions?\s*\(?\s*Scope\s*2\s*\)?",
)
_GHG_TOTAL_ANNOTATED = re.compile(r"范围\s*[一1]\s*[、和+及]\s*范围\s*[二2]|Scope\s*1\s*(?:\+|and|&)\s*Scope\s*2", re.I)


def _scope_value(text: str, label: str, units: tuple[tuple[str, float], ...], mode: str | None) -> float | None:
    """Read the current-year value of a scope row with the same column discipline as totals."""
    factors = dict(units)
    unit_pattern = "(?:" + "|".join(re.escape(unit) for unit, _ in units) + ")"
    patterns = []
    if mode == "current-first":
        patterns.append(rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})(?:\s+(?:{_CN_NUMBER}|/)){{0,2}}\s*$")
    elif mode == "current-last":
        patterns.append(rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*$")
    patterns.append(rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s*$")
    for row in patterns:
        match = re.search(row, text)
        if not match:
            continue
        factor = factors.get(re.sub(r"\s+", "", match.group("unit")))
        if factor is None:
            continue
        return float(match.group("current").replace(",", "")) * factor
    return None


def _ghg_total_acceptable(
    row_evidence: str, text: str, mode: str | None, units: tuple[tuple[str, float], ...],
    total_kg: float, english: bool,
) -> bool:
    """Verify a GHG total is scope-1+2, not scope-3-contaminated."""
    if _GHG_TOTAL_ANNOTATED.search(row_evidence):
        return True
    scope3 = (_EN_SCOPE3_POSITIVE if english else _CN_SCOPE3_POSITIVE).search(text)
    if scope3 and float(scope3.group(1).replace(",", "")) > 0:
        return False
    labels = _EN_SCOPE12_LABELS if english else _CN_SCOPE12_LABELS
    scope1 = _scope_value(text, labels[0], units, mode)
    scope2 = _scope_value(text, labels[1], units, mode)
    if scope1 is not None and scope2 is not None:
        return abs(total_kg - scope1 - scope2) <= max(total_kg, 1.0) * 0.01
    return True


def _cn_total_rows(text: str, report_year: int, source_file: str, page: int) -> list[_EnvTotal]:
    """Parse group-level environmental totals from Chinese KPI rows.

    Supported forms: explicit-year-header table rows (label unit values) and
    single-value free-form rows (label unit value or label value unit).
    """
    text = _normalize_kangxi(text)
    mode = _chinese_year_table_mode(text, report_year)
    results: list[_EnvTotal] = []
    for code, label, units, _bounds in _CN_TOTAL_RULES:
        factors = dict(units)
        unit_pattern = "(?:" + "|".join(re.escape(unit) for unit, _ in units) + ")"
        row_patterns: list[tuple[str, str]] = []
        if mode == "current-first":
            row_patterns.append((
                "current-first",
                rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})(?:\s+(?:{_CN_NUMBER}|/)){{0,2}}\s*$",
            ))
        elif mode == "current-last":
            row_patterns.append((
                "current-last",
                rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?P<unit>{unit_pattern})\s*{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*$",
            ))
        # 单值行：单年表头或无表头的KPI段落均只接受恰好一个数值，避免猜列
        row_patterns.append((
            "single-value",
            rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s*$",
        ))
        row_patterns.append((
            "value-first",
            rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?:为|：|:)?\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})(?![ \t]*(?:{_CN_NUMBER}|%))\s*$",
        ))
        # 叙述式：报告主体锚定的句中总量（如“2025年，公司温室气体排放总量5532.27吨”）。
        # 锚词与前后措辞防护保证这是报告期实际总量而非目标/宏观叙述
        row_patterns.append((
            "narrative",
            rf"(?m)(?:公司|本集团|集团)\s*(?:{label})\s*(?:为|达到|：|:)?\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})(?![ \t]*(?:{_CN_NUMBER}|%))(?=\s*(?:$|[，。；,、]))",
        ))
        # 陈述式：法定环境信息披露的分号/句号终止总量句（如“氮氧化物排放总量 4,697.8 吨；”）。
        # 终止符与部分口径前缀防护保证这不是子公司/项目口径或流水账片段
        row_patterns.append((
            "statement",
            rf"(?m)(?:{label})\s*(?:为|达到|：|:)?\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})(?![ \t]*(?:{_CN_NUMBER}|%))(?=\s*(?:$|[；;，,。、]))",
        ))
        for form, row in row_patterns:
            if form in {"current-first", "current-last"} and mode is None:
                continue
            for match in re.finditer(row, text):
                if form in {"narrative", "statement"}:
                    # PDF换行不是句边界；防护窗口以上一句末标点为界、上限120字符，
                    # 覆盖句首的部分口径锚点（如“4家火电企业二氧化硫…氮氧化物…”）
                    sentence_start = max(text.rfind(mark, 0, match.start()) for mark in ("。", "；", ";")) + 1
                    window = text[max(sentence_start, match.start() - 120):match.start()]
                    if _CN_BAD_PREFIX.search(window) or _CN_PARTIAL_SCOPE.search(window):
                        continue
                else:
                    prefix = text[max(0, match.start() - 24):match.start()]
                    if _CN_BAD_PREFIX.search(prefix):
                        continue
                if form == "statement":
                    # 行首情形已由value-first覆盖，避免同值双证据
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    if not text[line_start:match.start()].strip():
                        continue
                between = text[match.start():match.start("current")]
                if _CN_BAD_BETWEEN.search(between):
                    continue
                unit_key = re.sub(r"\s+", "", match.group("unit"))
                factor = factors.get(unit_key)
                if factor is None:
                    continue
                total_kg = float(match.group("current").replace(",", "")) * factor
                if total_kg <= 0:
                    continue
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                if code == "Q_E_GHG_INTENSITY" and not _ghg_total_acceptable(
                    evidence, text, mode, units, total_kg, english=False,
                ):
                    continue
                results.append(_EnvTotal(
                    code, total_kg, source_file, page,
                    f"Chinese {form} environmental total row: {evidence[:220]}",
                ))
    return results


_EN_BAD_CONTEXT = re.compile(
    r"equity\s+(?:basis|share)|per\s+(?:employee|unit|tonne|production|kwh|mwh)|"
    r"intensity|target|baseline|produced", re.I,
)

_EN_TOTAL_RULES: tuple[tuple[str, str, tuple[tuple[str, float], ...], tuple[float, float]], ...] = (
    (
        "Q_E_GHG_INTENSITY",
        r"Total\s+(?:GHG|greenhouse\s+gas)\s+emissions?\s*(?:\(?\s*Scope\s*1\s*(?:\+|and|&)\s*Scope\s*2\s*\)?)?(?!\s*[:：]?\s*Scope)(?!\s*[:-]?\s*(?:Direct|Indirect))",
        (("kilotonnes", 1_000_000.0), ("kt", 1_000_000.0), ("tCO2e", 1_000.0), ("tCO₂e", 1_000.0),
         ("tonnes of carbon dioxide equivalent", 1_000.0), ("tonnes CO2e", 1_000.0), ("tonnes CO₂e", 1_000.0),
         ("tonnes", 1_000.0)),
        (0.001, 200_000.0),
    ),
    (
        "Q_E_ENERGY_INTENSITY",
        r"Total\s+(?:comprehensive\s+)?energy\s+consumption(?!\s+intensity)(?!\s+density)",
        (("tonnes of standard coal equivalent", 1_000.0), ("tonnes of standard coal", 1_000.0),
         ("tce", 1_000.0), ("kgce", 1.0)),
        (0.0001, 100_000.0),
    ),
    (
        "Q_E_WATER_INTENSITY",
        r"Total\s+water\s+consumption(?!\s+intensity)(?!\s+density)",
        (("kilotonnes", 1_000_000.0), ("cubic metres", 1_000.0), ("m3", 1_000.0), ("m³", 1_000.0),
         ("tonnes", 1_000.0)),
        (0.001, 5_000_000.0),
    ),
    (
        "Q_E_SO2_INTENSITY",
        r"(?:Total\s+)?(?:SO2|sulphur\s+dioxide|sulfur\s+dioxide)\s+emissions?(?!\s+intensity)(?!\s+density)",
        (("tonnes", 1_000.0), ("kg", 1.0)),
        (0.001, 100_000.0),
    ),
    (
        "Q_E_NOX_INTENSITY",
        r"(?:Total\s+)?(?:NOx|nitrogen\s+oxides?)\s+emissions?(?!\s+intensity)(?!\s+density)",
        (("tonnes", 1_000.0), ("kg", 1.0)),
        (0.001, 100_000.0),
    ),
    (
        "Q_E_PM_INTENSITY",
        r"(?:Total\s+)?particulate\s+matter\s+emissions?(?!\s+intensity)(?!\s+density)",
        (("tonnes", 1_000.0), ("kg", 1.0)),
        (0.0001, 20_000.0),
    ),
    (
        "Q_E_WASTEWATER_INTENSITY",
        r"Total\s+wastewater\s+discharge(?!\s+intensity)(?!\s+density)",
        (("tonnes", 1_000.0), ("cubic metres", 1_000.0), ("m3", 1_000.0), ("m³", 1_000.0)),
        (0.001, 5_000_000.0),
    ),
    (
        "Q_E_SOLID_WASTE_INTENSITY",
        r"Total\s+non-hazardous\s+waste(?:\s+generation)?(?!\s+intensity)(?!\s+density)",
        (("tonnes", 1_000.0), ("kg", 1.0)),
        (0.001, 5_000_000.0),
    ),
    (
        "Q_E_HAZ_WASTE_INTENSITY",
        r"Total\s+hazardous\s+waste(?:\s+generation)?(?!\s+intensity)(?!\s+density)",
        (("tonnes", 1_000.0), ("kg", 1.0)),
        (0.0001, 100_000.0),
    ),
)

_EN_NUMBER = r"[\d,]+(?:\.\d+)?"
# 年份表头必须是独立行（可带Unit/Year/Indicator等词），避免把正文叙述年份当表头
_EN_YEAR_HEADER = re.compile(
    r"(?mi)^\s*(?:[^\n]{0,40}?\b(?:Unit|Year|Indicator|指标|單位|单位)\b[^\n]{0,20}?)?"
    r"(20\d{2})\s*(?:年)?\s+(20\d{2})(?:\s*(?:年)?\s+(20\d{2}))?\s*$"
)

# 公司已按收入口径披露强度（即使版式未被直接规则解析）时抑制派生，不制造口径冲突；
# 产值/产量口径不抑制——方法论只认营业收入分母
_SUPPRESS_RULES = {
    "Q_E_GHG_INTENSITY": re.compile(
        r"(?:温室气体|碳|GHG|greenhouse\s+gas)[\s\S]{0,60}?(?:排放)?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_ENERGY_INTENSITY": re.compile(
        r"(?:能源|能耗|energy)[\s\S]{0,60}?(?:消耗|消费|consumption)?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_WATER_INTENSITY": re.compile(
        r"(?:水|water)[\s\S]{0,60}?(?:使用|消耗|consumption)?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_SO2_INTENSITY": re.compile(
        r"(?:二氧化硫|SO2|sulphur\s+dioxide|sulfur\s+dioxide)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|(?<!每)百万营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_NOX_INTENSITY": re.compile(
        r"(?:氮氧化物|NOx|nitrogen\s+oxides?)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|(?<!每)百万营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_PM_INTENSITY": re.compile(
        r"(?:颗粒物|烟尘|particulate\s+matter)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|(?<!每)百万营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_WASTEWATER_INTENSITY": re.compile(
        r"(?:废水|wastewater)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|(?<!每)百万营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_SOLID_WASTE_INTENSITY": re.compile(
        r"(?:一般(?:工业)?固体废物|一般固废|无害废弃物|non-hazardous\s+waste)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|(?<!每)百万营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_HAZ_WASTE_INTENSITY": re.compile(
        r"(?:危险废物|危废|hazardous\s+waste)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|(?<!每)百万营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
}


def _en_total_rows(text: str, report_year: int, source_file: str, page: int) -> list[_EnvTotal]:
    """Parse group-level environmental totals from English ESG disclosures.

    Free-form sentences require an explicit Group anchor; table rows require an
    explicit year header on the same page to fix the current-year column.
    """
    results: list[_EnvTotal] = []
    year_columns: list[int] = []
    header = _EN_YEAR_HEADER.search(text)
    if header:
        year_columns = [int(group) for group in header.groups() if group]
    for code, label, units, _bounds in _EN_TOTAL_RULES:
        factors = {unit.lower(): factor for unit, factor in units}
        unit_pattern = "(?:" + "|".join(re.escape(unit) for unit, _ in units) + ")"
        # 表格行：label unit values（需页内明确年份表头定位本期列）
        row = re.compile(
            rf"(?mi)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<values>{_EN_NUMBER}(?:\s+{_EN_NUMBER}){{0,2}})\s*$",
        )
        for match in row.finditer(text):
            if not year_columns or report_year not in year_columns:
                continue
            values = match.group("values").split()
            if len(values) != len(year_columns):
                continue
            context = text[max(0, match.start() - 80):match.end() + 40]
            if _EN_BAD_CONTEXT.search(context):
                continue
            factor = factors.get(match.group("unit").lower())
            if factor is None:
                continue
            current = float(values[year_columns.index(report_year)].replace(",", "")) * factor
            if current <= 0:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            if code == "Q_E_GHG_INTENSITY" and not _ghg_total_acceptable(
                evidence, text, None, units, current, english=True,
            ):
                continue
            results.append(_EnvTotal(
                code, current, source_file, page,
                f"English year-header environmental total row: {evidence[:220]}",
            ))
        # 自由文本：the Group's total GHG emissions were 154,166.64 tonnes of ...
        free = re.compile(
            rf"(?:Group|集团)(?:'s|’s)?\s+total\s+(?:GHG|greenhouse\s+gas)\s+emissions?"
            rf"(?:\s*\(?\s*Scope\s*1\s*(?:\+|and|&)\s*Scope\s*2\s*\)?)?"
            rf"\s*(?:were|was|reached|amounted\s+to|of)?\s*(?P<current>{_EN_NUMBER})\s*"
            rf"(?P<unit>kilotonnes|tonnes)(?:\s+of\s+(?:carbon\s+dioxide\s+equivalent|CO2e|CO₂e))?",
            re.I,
        ) if code == "Q_E_GHG_INTENSITY" else None
        if free is None:
            continue
        for match in free.finditer(text):
            context = text[max(0, match.start() - 120):match.end() + 120]
            if _EN_BAD_CONTEXT.search(context):
                continue
            factor = factors.get(match.group("unit").lower())
            if factor is None:
                continue
            current = float(match.group("current").replace(",", "")) * factor
            if current <= 0:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            if not _ghg_total_acceptable(evidence, text, None, units, current, english=True):
                continue
            results.append(_EnvTotal(
                code, current, source_file, page,
                f"English group-scope environmental total: {evidence[:220]}",
            ))
    return results


def _chinese_consolidated_revenue(doc: CompanyDocument) -> _RevenueFact | None:
    for index, page in enumerate(doc.pages):
        in_summary = _is_summary_section_page(page.text) or (
            index > 0
            and _is_summary_section_page(doc.pages[index - 1].text)
            and "营业收入" not in doc.pages[index - 1].text
        )
        parsed = _extract_summary_revenue(page.text, in_summary)
        if parsed:
            current, _previous, evidence = parsed
            if current > 0:
                return _RevenueFact(current, doc.source_file, page.page, evidence[:220])
    return None


_EN_INCOME_TITLE = re.compile(
    r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+"
    r"(?:profit\s+or\s+loss|profit\s+and\s+loss|income|comprehensive\s+income)(?:\s|$)"
    r"|^\s*consolidated\s+(?:income|profit)\s+statement\s*$",
)
_EN_INCOME_END = re.compile(
    r"(?mi)^\s*(?:[^\n]{0,40}?\s+)?(?:consolidated\s+)?statement\s+of\s+(?:financial\s+position|changes|cash\s+flows?)"
    r"|^\s*parent\s+(?:company\s+)?(?:income|profit)\s+statement\s*$",
)
_EN_RMB_SCALE = re.compile(
    r"RMB\s*['’]?\s*(million|billion|thousand|000)", re.I,
)
_EN_FOREIGN_UNIT = re.compile(r"HK\s*\$|HKD|US\s*\$|USD|HK\s*['’]\s*000", re.I)


def _english_consolidated_revenue(doc: CompanyDocument) -> _RevenueFact | None:
    """Read consolidated revenue from an English income statement in explicit RMB units."""
    for start in (index for index, page in enumerate(doc.pages) if _EN_INCOME_TITLE.search(page.text)):
        statement_pages = []
        for page in doc.pages[start:start + 5]:
            if statement_pages and _EN_INCOME_END.search(page.text):
                break
            statement_pages.append(page)
        header_text = "\n".join(page.text for page in statement_pages[:2])
        if _EN_FOREIGN_UNIT.search(header_text):
            continue
        scale_match = _EN_RMB_SCALE.search(header_text)
        if not scale_match:
            continue
        unit = scale_match.group(1).lower()
        scale = {"million": 1_000_000.0, "billion": 1_000_000_000.0}.get(unit, 1_000.0)
        revenue = _find_english_statement_fact(
            statement_pages, r"(?:I\.\s*)?(?:Total\s+revenue\s+from\s+operations|(?:(?:Total\s+)?Operating\s+)?Revenue)",
        )
        if not revenue or revenue.values[0] <= 0:
            continue
        return _RevenueFact(
            revenue.values[0] * scale, doc.source_file, revenue.page,
            f"English consolidated revenue (RMB {unit}): {revenue.evidence[:180]}",
        )
    return None


_GRAM_CANONICAL_INDICATORS = {"Q_E_SO2_INTENSITY", "Q_E_NOX_INTENSITY", "Q_E_PM_INTENSITY"}


def _distinct(values: list[float], rel_tol: float = 1e-4) -> bool:
    if len(values) < 2:
        return False
    low, high = min(values), max(values)
    return high - low > max(abs(low), abs(high), 1.0) * rel_tol


def derive_env_intensity_candidates(
    company_code: str,
    company_name: str,
    report_year: int,
    documents: list[CompanyDocument],
    skip_indicators: frozenset[str] = frozenset(),
) -> list[Observation]:
    """Derive 总量/营收 environmental intensities for one company and report year."""
    revenues: list[_RevenueFact] = []
    totals: dict[str, list[_EnvTotal]] = {}
    for doc in documents:
        if doc.document_type == "annual_report":
            revenue = _chinese_consolidated_revenue(doc) or _english_consolidated_revenue(doc)
            if revenue:
                revenues.append(revenue)
        for page in doc.pages:
            page_totals = _cn_total_rows(page.text, report_year, doc.source_file, page.page)
            page_totals += _en_total_rows(page.text, report_year, doc.source_file, page.page)
            for total in page_totals:
                totals.setdefault(total.indicator_code, []).append(total)
    if not revenues or _distinct([item.revenue_rmb for item in revenues]):
        return []
    revenue = revenues[0]
    full_text = "\n".join(page.text for doc in documents for page in doc.pages)
    results: list[Observation] = []
    for code, items in sorted(totals.items()):
        if code in skip_indicators:
            continue
        if _distinct([item.total_kg for item in items]):
            continue
        suppress = _SUPPRESS_RULES.get(code)
        if suppress and suppress.search(full_text):
            continue
        bounds = next(rule[3] for rule in _CN_TOTAL_RULES + _EN_TOTAL_RULES if rule[0] == code)
        total = items[0]
        # SO2/NOx/PM方法论口径为克/万元，其余指标为千克/万元
        canonical_per_kg = 1_000.0 if code in _GRAM_CANONICAL_INDICATORS else 1.0
        value = total.total_kg * canonical_per_kg * 10_000 / revenue.revenue_rmb
        if not bounds[0] <= value <= bounds[1]:
            continue
        if total.evidence.startswith("Chinese"):
            evidence = (
                f"中文跨表派生: {total.evidence} ({total.source_file} 第{total.source_page}页) "
                f"| 营业收入={revenue.revenue_rmb:g}元 ({revenue.source_file} 第{revenue.source_page}页)"
            )
        else:
            evidence = (
                f"English cross-document derived: {total.evidence} ({total.source_file} p{total.source_page}) "
                f"| Revenue=RMB{revenue.revenue_rmb:g} ({revenue.source_file} p{revenue.source_page})"
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
