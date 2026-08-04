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
        r"范围\s*[一1]\s*[、和+及]\s*范围\s*[二2]\s*温室气体排放总量\s*[（(]基于位置[）)]|(?<!范围一)(?<!范围二)(?<!范围三)(?<!范围1)(?<!范围2)(?<!范围3)(?<!范畴一)(?<!范畴二)(?<!范畴三)(?<!范畴1)(?<!范畴2)(?<!范畴3)(?<!每百万营收)(?<!单位营收)(?<!减少的)(?<!直接)(?<!间接)温室气体排放总量(?:\s*[（(]含?范围\s*[一1]\s*[、和+及]\s*范围\s*[二2][）)])?|(?<!范围一)(?<!范围二)(?<!范围三)(?<!范围1)(?<!范围2)(?<!范围3)(?<!范畴一)(?<!范畴二)(?<!范畴三)(?<!范畴1)(?<!范畴2)(?<!范畴3)温室气体总排放量",
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
        r"(?<!去除)(?<!削减)二氧化硫(?:排放)?总量|二氧化硫排放量|外排废气中二氧化硫量",
        (("吨", 1_000.0), ("千克", 1.0)),
        (0.001, 100_000.0),
    ),
    (
        "Q_E_NOX_INTENSITY",
        r"(?<!去除)(?<!削减)氮氧化物(?:排放)?总量|氮氧化物排放量|外排废气中氮氧化物量",
        (("吨", 1_000.0), ("千克", 1.0)),
        (0.001, 100_000.0),
    ),
    (
        "Q_E_PM_INTENSITY",
        r"(?:颗粒物(?:\s*[（(]PM[）)]\s*)?|烟尘)(?:排放)?总量|"
        r"(?:颗粒物(?:\s*[（(]PM[）)]\s*)?|烟尘)(?:年)?排放量|"
        r"悬浮粒[子⼦]与颗粒物\s*[（(]PM[）)]\s*排放量",
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
_CN_BAD_PREFIX = re.compile(r"目标|计划|规划|核定|许可|限值|上限|减少|降低|增加|减排(?!(?:标准|任务|改造|要求|措施|工作|项目|工程|责任))|预计|预测")
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
    r"范围\s*[一1]\s*温室气体排放(?:总)?量|直接温室气体排放(?:总)?量?\s*[（(]\s*范围\s*[一1]\s*[)）]",
    r"范围\s*[二2]\s*温室气体排放(?:总)?量|间接温室气体排放(?:总)?量?\s*[（(]\s*范围\s*[二2]\s*[)）]",
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
    forms: list[str] = []
    for code, label, units, _bounds in _CN_TOTAL_RULES:
        factors = dict(units)
        unit_pattern = "(?:" + "|".join(re.escape(unit) for unit, _ in units) + ")"
        row_patterns: list[tuple[str, str]] = []
        if mode == "current-first":
            row_patterns.append((
                "current-first",
                rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})(?:\s+(?:{_CN_NUMBER}|/)){{0,2}}\s*$",
            ))
            row_patterns.append((
                "current-first",
                rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?P<current>{_CN_NUMBER})(?:\s+(?:{_CN_NUMBER}|/)){{1,2}}\s*(?P<unit>{unit_pattern})\s*$",
            ))
        elif mode == "current-last":
            row_patterns.append((
                "current-last",
                rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?P<unit>{unit_pattern})\s*{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*$",
            ))
            row_patterns.append((
                "current-last",
                rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*{_CN_NUMBER}(?:\s+{_CN_NUMBER})?\s+(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})\s*$",
            ))
        # 单值行：单年表头或无表头的KPI段落均只接受恰好一个数值，避免猜列
        row_patterns.append((
            "single-value",
            rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s*$",
        ))
        row_patterns.append((
            "value-first",
            rf"(?m)^\s*(?:{label})(?:\s*注\s*\d+)?\s*(?:为|达到|：|:)?\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>{unit_pattern})(?![ \t]*(?:{_CN_NUMBER}|%))\s*[。；;，,、]?\s*$",
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
                    # 行首情形仅当value-first确实覆盖（单位后仅剩终止符到行尾）时让位，
                    # 行首胶粘行仍由statement承接
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    if not text[line_start:match.start()].strip():
                        rest = text[match.end():text.find("\n", match.end()) if "\n" in text[match.end():] else len(text)]
                        if re.fullmatch(r"\s*[。；;，,、]?\s*", rest):
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
                forms.append(form)
    # Some ESG reports use a one-year pollutant matrix whose header carries the year/unit
    # semantics while rows contain only the pollutant name, value and mass unit. Bare labels
    # are accepted only inside that exact matrix, never in free-form narrative.
    if re.search(rf"废气污染物种类\s*{report_year}\s*年度?\s*单位", text):
        pollutant_rows = (
            ("Q_E_NOX_INTENSITY", r"氮氧化物"),
            ("Q_E_SO2_INTENSITY", r"二氧化硫"),
            ("Q_E_PM_INTENSITY", r"(?:烟尘|颗粒物)"),
        )
        existing_codes = {item.indicator_code for item in results}
        for code, label in pollutant_rows:
            if code in existing_codes:
                continue
            match = re.search(
                rf"(?m)^\s*{label}\s*(?P<current>{_CN_NUMBER})\s*(?P<unit>吨|千克)\s*$",
                text,
            )
            if not match:
                continue
            factor = 1_000.0 if match.group("unit") == "吨" else 1.0
            total_kg = float(match.group("current").replace(",", "")) * factor
            if total_kg <= 0:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            results.append(_EnvTotal(
                code, total_kg, source_file, page,
                f"Chinese explicit-year pollutant matrix row: {evidence}",
            ))
            forms.append("explicit-year-pollutant-matrix")
    if mode in {"current-first", "current-last"} and "气体污染物排放" in text:
        pollutant_rows = (
            ("Q_E_NOX_INTENSITY", r"氮氧化物"),
            ("Q_E_PM_INTENSITY", r"(?:烟尘|颗粒物)"),
        )
        existing_codes = {item.indicator_code for item in results}
        for code, label in pollutant_rows:
            if code in existing_codes:
                continue
            if mode == "current-first":
                pattern = rf"(?m)^\s*{label}\s*(?P<unit>吨|千克)\s*(?P<current>{_CN_NUMBER})\s+{_CN_NUMBER}\s*$"
            else:
                pattern = rf"(?m)^\s*{label}\s*(?P<unit>吨|千克)\s*{_CN_NUMBER}\s+(?P<current>{_CN_NUMBER})\s*$"
            match = re.search(pattern, text)
            if not match:
                continue
            factor = 1_000.0 if match.group("unit") == "吨" else 1.0
            total_kg = float(match.group("current").replace(",", "")) * factor
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            results.append(_EnvTotal(
                code, total_kg, source_file, page,
                f"Chinese explicit-year gas-pollutant section row: {evidence}",
            ))
            forms.append("explicit-year-gas-pollutant-section")
    # 部分PDF把列式污染物表按“标签/单位/各年值”逐行拆开。这里只接受带显式年份表头、
    # 且以“外排废气中”开头的实际排放标签；“核定的年度…”许可上限无法命中该锚点。
    if mode in {"current-first", "current-last"}:
        split_external_rows = (
            ("Q_E_SO2_INTENSITY", r"外排废气中二氧化硫量"),
            ("Q_E_NOX_INTENSITY", r"外排废气中氮氧化物量"),
        )
        existing_codes = {item.indicator_code for item in results}
        for code, label in split_external_rows:
            if code in existing_codes:
                continue
            if mode == "current-first":
                pattern = rf"(?m)^\s*{label}\s*\n\s*(?P<unit>吨|千克)\s*\n\s*(?P<current>{_CN_NUMBER})\s*\n\s*{_CN_NUMBER}\s*$"
            else:
                pattern = rf"(?m)^\s*{label}\s*\n\s*(?P<unit>吨|千克)\s*\n\s*{_CN_NUMBER}\s*\n\s*(?P<current>{_CN_NUMBER})\s*$"
            match = re.search(pattern, text)
            if not match:
                continue
            factor = 1_000.0 if match.group("unit") == "吨" else 1.0
            total_kg = float(match.group("current").replace(",", "")) * factor
            if total_kg <= 0:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            results.append(_EnvTotal(
                code, total_kg, source_file, page,
                f"Chinese explicit-year split external-emission row: {evidence}",
            ))
            forms.append("explicit-year-split-external-emission")
    # 单年KPI表的PDF单元格拆行；只接收方法论同名NOx和明确含PM标记的颗粒物总量。
    # “硫氧化物”不在映射内，避免自动等同SO2。
    if mode == "single-year":
        split_single_year_rows = (
            ("Q_E_NOX_INTENSITY", r"氮氧化物排放量"),
            ("Q_E_PM_INTENSITY", r"悬浮粒[子⼦]与颗粒物\s*[（(]PM[）)]排放量"),
        )
        existing_codes = {item.indicator_code for item in results}
        for code, label in split_single_year_rows:
            if code in existing_codes:
                continue
            match = re.search(
                rf"(?m)^\s*{label}\s*\n\s*(?P<unit>吨|千克)\s*\n\s*(?P<current>{_CN_NUMBER})\s*$",
                text,
            )
            if not match:
                continue
            factor = 1_000.0 if match.group("unit") == "吨" else 1.0
            total_kg = float(match.group("current").replace(",", "")) * factor
            if total_kg <= 0:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            results.append(_EnvTotal(
                code, total_kg, source_file, page,
                f"Chinese explicit-single-year split pollutant row: {evidence}",
            ))
            forms.append("explicit-single-year-split-pollutant")
    # 个别横排表的标题仅写年份区间，但首个污染物行逐值重复年份，由此可证明后续三值行列序。
    # 没有“2025值/2024值/2023值”锚点时不启用，避免把区间标题当作列映射。
    if re.search(rf"{report_year - 2}\s*[-—–]\s*{report_year}\s*年[^\n]{{0,20}}废气排放量", text):
        order_anchor = re.search(
            rf"硫氧化物排放量\s*单位\s*(?:千克|吨)\s*{report_year}\s*年\s*{_CN_NUMBER}\s*"
            rf"{report_year - 1}\s*年\s*{_CN_NUMBER}\s*{report_year - 2}\s*年\s*{_CN_NUMBER}",
            text,
        )
        if order_anchor:
            existing_codes = {item.indicator_code for item in results}
            for code, label in (
                ("Q_E_NOX_INTENSITY", r"氮氧化物排放量"),
                ("Q_E_PM_INTENSITY", r"颗粒物排放量"),
            ):
                if code in existing_codes:
                    continue
                match = re.search(
                    rf"(?m)^\s*{label}\s*(?P<unit>千克|吨)\s*(?P<current>{_CN_NUMBER})\s+{_CN_NUMBER}\s+{_CN_NUMBER}\s*$",
                    text,
                )
                if not match:
                    continue
                factor = 1_000.0 if match.group("unit") == "吨" else 1.0
                total_kg = float(match.group("current").replace(",", "")) * factor
                if total_kg <= 0:
                    continue
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                results.append(_EnvTotal(
                    code, total_kg, source_file, page,
                    f"Chinese per-value-year-anchored pollutant row: {evidence}",
                ))
                forms.append("per-value-year-anchored-pollutant")
    # 年列表行有列定位锚点；同页单值/叙述/陈述行与年列值不一致时多为上年列或拼版
    # 残片（如“废水排放量 万立方米 36.28”为首年列断行），按年列值剔除，不制造假冲突
    keep = [True] * len(results)
    for code in {item.indicator_code for item in results}:
        anchored = [
            item.total_kg for item, form in zip(results, forms)
            if item.indicator_code == code and form in {"current-first", "current-last"}
        ]
        if not anchored:
            continue
        for index, (item, form) in enumerate(zip(results, forms)):
            if item.indicator_code != code or form in {"current-first", "current-last"}:
                continue
            if all(
                abs(item.total_kg - value) > max(abs(item.total_kg), abs(value), 1.0) * 1e-4
                for value in anchored
            ):
                keep[index] = False
    return [item for item, retained in zip(results, keep) if retained]


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
    r"(20\d{2})\s*(?:年)?\s+(?:Year\s+)?(20\d{2})"
    r"(?:\s*(?:年)?\s+(?:Year\s+)?(20\d{2}))?"
    r"(?:\s*(?:年)?\s+(?:Year\s+)?(20\d{2}))?(?:\s+Unit)?\s*$"
)

# 公司已按收入口径披露强度（即使版式未被直接规则解析）时抑制派生，不制造口径冲突；
# 产值/产量口径不抑制——方法论只认营业收入分母
_SUPPRESS_RULES = {
    "Q_E_GHG_INTENSITY": re.compile(
        r"(?:温室气体|碳|GHG|greenhouse\s+gas)[\s\S]{0,60}?(?:排放)?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|revenue|yuan|RMB|人民币)"
        r"|(?:单位营收|每百万营收)\s*(?:温室气体|碳|GHG)[^。\n]{0,12}(?:排放量|总量)", re.I,
    ),
    "Q_E_ENERGY_INTENSITY": re.compile(
        r"(?:能源|能耗|energy)[\s\S]{0,60}?(?:消耗|消费|consumption)?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|revenue|yuan|RMB|人民币)"
        r"|(?:单位营收|每百万营收)\s*(?:综合)?能源(?:消耗|消费)[^。\n]{0,12}(?:量|总量)", re.I,
    ),
    "Q_E_WATER_INTENSITY": re.compile(
        r"(?:水|water)[\s\S]{0,60}?(?:使用|消耗|consumption)?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|营收|revenue|yuan|RMB|人民币)"
        r"|(?:单位营收|每百万营收)\s*用水[^。\n]{0,8}量", re.I,
    ),
    "Q_E_SO2_INTENSITY": re.compile(
        r"(?:二氧化硫|SO2|sulphur\s+dioxide|sulfur\s+dioxide)[^\n]{0,60}?(?:强度|密度|intensity|density)"
        r"[^\n]{0,60}?(?:营业收入|(?<!每)百万营收|(?<!百万)营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_NOX_INTENSITY": re.compile(
        r"(?:氮氧化物|NOx|nitrogen\s+oxides?)[^\n]{0,60}?(?:强度|密度|intensity|density)"
        r"[^\n]{0,60}?(?:营业收入|(?<!每)百万营收|(?<!百万)营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_PM_INTENSITY": re.compile(
        r"(?:颗粒物|烟尘|particulate\s+matter)[^\n]{0,60}?(?:强度|密度|intensity|density)"
        r"[^\n]{0,60}?(?:营业收入|(?<!每)百万营收|(?<!百万)营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_WASTEWATER_INTENSITY": re.compile(
        r"(?:废水|wastewater)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|(?<!每)百万营收|(?<!百万)营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_SOLID_WASTE_INTENSITY": re.compile(
        r"(?:一般(?:工业)?固体废物|一般固废|无害废弃物|non-hazardous\s+waste)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|(?<!每)百万营收|(?<!百万)营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
    ),
    "Q_E_HAZ_WASTE_INTENSITY": re.compile(
        r"(?:危险废物|危废|hazardous\s+waste)[\s\S]{0,60}?(?:强度|密度|intensity|density)"
        r"[\s\S]{0,60}?(?:营业收入|(?<!每)百万营收|(?<!百万)营收|万元(?!产值)|revenue|yuan|RMB|人民币)", re.I,
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
        rows = (
            re.compile(rf"(?mi)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<values>{_EN_NUMBER}(?:\s+{_EN_NUMBER}){{0,3}})\s*$"),
            re.compile(rf"(?mi)^\s*(?:{label})\s*(?P<values>{_EN_NUMBER}(?:\s+{_EN_NUMBER}){{0,3}})\s*(?P<unit>{unit_pattern})\s*$"),
        )
        for match in (item for row in rows for item in row.finditer(text)):
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
    # ESG绩效矩阵可在“Emissions + Air Pollutant”分区使用裸污染物名。仅NOx具有与方法论相同的
    # 明确物质口径；Sulphur oxides不等同SO2，PM2.5/PM10也不猜测是否应相加。
    if (
        header and report_year in year_columns
        and re.search(r"(?mi)^\s*Emissions\s+Year\s+20\d{2}", text)
        and re.search(r"(?mi)^\s*Air\s+Pollutant\d*\s*$", text)
        and not any(item.indicator_code == "Q_E_NOX_INTENSITY" for item in results)
    ):
        match = re.search(
            rf"(?mi)^\s*Nitrogen\s+oxides\s+(?P<values>{_EN_NUMBER}(?:\s+{_EN_NUMBER}){{0,3}})\s+(?P<unit>tonnes|kg)\s*$",
            text,
        )
        if match:
            values = match.group("values").split()
            if len(values) == len(year_columns):
                factor = 1_000.0 if match.group("unit").lower() == "tonnes" else 1.0
                current = float(values[year_columns.index(report_year)].replace(",", "")) * factor
                if current > 0:
                    evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                    results.append(_EnvTotal(
                        "Q_E_NOX_INTENSITY", current, source_file, page,
                        f"English explicit-year air-pollutant matrix row: {evidence}",
                    ))
    # 集团锅炉废气叙述句：同时给出明确报告年、Group主体、化学式和实际质量。目标句位于其后，
    # 不进入匹配；“sulfur content/reduction”也无法命中该结构。
    boiler = re.search(
        rf"In\s+{report_year},[^\n]{{0,180}}?exhaust\s+gas\s+emission[^\n]{{0,120}}?by\s+the\s+Group\s+was"
        rf"[^\n]{{0,160}}?sul(?:ph|f)ur\s+dioxide\s*\(SO2\)\s+was\s+(?P<so2>{_EN_NUMBER})\s+tonnes?,\s*"
        rf"and\s+nitrogen\s+oxides?\s*\(NOx\)\s+was\s+(?P<nox>{_EN_NUMBER})\s+tonnes?",
        text, re.I,
    )
    if boiler:
        evidence = re.sub(r"\s+", " ", boiler.group(0)).strip()
        for code, name in (("Q_E_SO2_INTENSITY", "so2"), ("Q_E_NOX_INTENSITY", "nox")):
            if any(item.indicator_code == code for item in results):
                continue
            total_kg = float(boiler.group(name).replace(",", "")) * 1_000.0
            if total_kg > 0:
                results.append(_EnvTotal(
                    code, total_kg, source_file, page,
                    f"English report-year Group boiler-emission statement: {evidence[:220]}",
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
    # 摘要标签可能在分页处拆成单字；仅回退到正式合并利润表且要求显式人民币单位和年度列。
    for page in doc.pages:
        if not re.search(r"(?m)^\s*合并利润\s*表\s*$", page.text):
            continue
        if not re.search(r"20\d{2}\s*年度?\s+20\d{2}\s*年度?", page.text):
            continue
        if re.search(r"单位\s*[：:]\s*元\s*币种\s*[：:]\s*人民币", page.text):
            scale = 1.0
        elif re.search(r"单位\s*[：:]\s*千元\s*币种\s*[：:]\s*人民币", page.text):
            scale = 1_000.0
        elif re.search(r"单位\s*[：:]\s*百万元\s*币种\s*[：:]\s*人民币", page.text):
            scale = 1_000_000.0
        else:
            continue
        match = re.search(
            rf"(?m)^\s*(?:[一二三四五六七八九十]*[、.]\s*)?(?:营业总收入|营业收入)\s+"
            rf"(?:[^\s]*\D[^\s]*\s+)?(?P<current>{_CN_NUMBER})\s+(?P<previous>{_CN_NUMBER})\s*$",
            page.text,
        )
        if match:
            current = float(match.group("current").replace(",", "")) * scale
            if current > 0:
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                return _RevenueFact(current, doc.source_file, page.page, f"合并利润表营业收入: {evidence}")
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
        if scale_match:
            unit = scale_match.group(1).lower()
            scale = {"million": 1_000_000.0, "billion": 1_000_000_000.0}.get(unit, 1_000.0)
        elif re.search(r"(?:Expressed|Presented)\s+in\s+RMB", header_text, re.I):
            unit = "unit"
            scale = 1.0
        else:
            continue
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
        if not (value == 0 and code in _GRAM_CANONICAL_INDICATORS) and not bounds[0] <= value <= bounds[1]:
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


# 温室气体减排率：同一显式年份表头总量行的本期/上期两值派生（上期-本期）/上期。
# 公司直接披露同口径减排率/同比下降时抑制派生；目标/计划措辞不构成披露。
_CN_REDUCTION_SUPPRESS = re.compile(
    r"(?:温室气体|碳排放)[\s\S]{0,24}(?:排放)?(?:总量)?[\s\S]{0,12}"
    r"(?:减排率|下降率|同比下降|同比减少|较上年下降)[\s\S]{0,8}%"
)
_CN_REDUCTION_TARGET_WORDS = re.compile(r"目标|计划|规划|力争|预计|预测")

# 两期口径断裂说明（如“2023年-2024年温室气体排放量仅统计了集团本部数据，不含子公司”）
# 使上期值与本期值不可比，整页减排率拒绝派生
_CN_PERIOD_BREAK = re.compile(
    r"仅(?:统计|涵盖|包括)[^。\n]{0,20}(?:集团本部|本部|总部)|不含子公司"
)


def _cn_reduction_disclosed(text: str) -> bool:
    return any(
        not _CN_REDUCTION_TARGET_WORDS.search(match.group(0))
        for match in _CN_REDUCTION_SUPPRESS.finditer(text)
    )


@dataclass(frozen=True)
class _GhgReduction:
    rate: float
    source_file: str
    source_page: int
    evidence: str


def _scope_pair(
    text: str, label: str, units: tuple[tuple[str, float], ...], mode: str,
) -> tuple[float, float] | None:
    """Read (current, previous) of a scope row with the same column discipline as totals."""
    factors = dict(units)
    unit_pattern = "(?:" + "|".join(re.escape(unit) for unit, _ in units) + ")"
    if mode == "current-first":
        row = rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s+(?P<previous>{_CN_NUMBER})(?:\s+(?:{_CN_NUMBER}|/))?\s*$"
    else:
        row = rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?:{_CN_NUMBER}\s+)?(?P<previous>{_CN_NUMBER})\s+(?P<current>{_CN_NUMBER})\s*$"
    match = re.search(row, text)
    if not match:
        return None
    factor = factors.get(re.sub(r"\s+", "", match.group("unit")))
    if factor is None:
        return None
    return (
        float(match.group("current").replace(",", "")) * factor,
        float(match.group("previous").replace(",", "")) * factor,
    )


def _cn_ghg_reduction_rows(text: str, report_year: int, source_file: str, page: int) -> list[_GhgReduction]:
    """Derive GHG reduction rates from two-period explicit-year-header total rows.

    Both values come from the same row/unit so the caliber is closed by construction;
    when scope rows parse with two periods, closure is verified for both periods,
    otherwise the current-period total must pass the standard scope acceptance.
    """
    text = _normalize_kangxi(text)
    mode = _chinese_year_table_mode(text, report_year)
    if mode not in {"current-first", "current-last"}:
        return []
    if _CN_PERIOD_BREAK.search(text):
        return []
    _code, label, units, _bounds = _CN_TOTAL_RULES[0]
    factors = dict(units)
    unit_pattern = "(?:" + "|".join(re.escape(unit) for unit, _ in units) + ")"
    if mode == "current-first":
        row = rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?P<current>{_CN_NUMBER})\s+(?P<previous>{_CN_NUMBER})(?:\s+{_CN_NUMBER})?\s*$"
    else:
        row = rf"(?m)^\s*(?:{label})\s*(?P<unit>{unit_pattern})\s*(?:{_CN_NUMBER}\s+)?(?P<previous>{_CN_NUMBER})\s+(?P<current>{_CN_NUMBER})\s*$"
    results: list[_GhgReduction] = []
    for match in re.finditer(row, text):
        prefix = text[max(0, match.start() - 24):match.start()]
        if _CN_BAD_PREFIX.search(prefix):
            continue
        factor = factors.get(re.sub(r"\s+", "", match.group("unit")))
        if factor is None:
            continue
        current = float(match.group("current").replace(",", "")) * factor
        previous = float(match.group("previous").replace(",", "")) * factor
        if current < 0 or previous <= 0:
            continue
        scope1 = _scope_pair(text, _CN_SCOPE12_LABELS[0], units, mode)
        scope2 = _scope_pair(text, _CN_SCOPE12_LABELS[1], units, mode)
        if scope1 is not None and scope2 is not None:
            if abs(current - scope1[0] - scope2[0]) > max(abs(current), 1.0) * 0.01:
                continue
            if abs(previous - scope1[1] - scope2[1]) > max(abs(previous), 1.0) * 0.01:
                continue
        elif not _ghg_total_acceptable(match.group(0), text, mode, units, current, english=False):
            continue
        rate = (previous - current) / previous * 100
        if not -1000 <= rate <= 100:
            continue
        evidence = re.sub(r"\s+", " ", match.group(0)).strip()
        results.append(_GhgReduction(
            rate, source_file, page,
            f"Chinese two-period GHG table row: {evidence[:220]}",
        ))
    return results


def derive_ghg_reduction_candidates(
    company_code: str,
    company_name: str,
    report_year: int,
    documents: list[CompanyDocument],
    skip_indicators: frozenset[str] = frozenset(),
) -> list[Observation]:
    """Derive 温室气体减排率 from same-table two-period totals for one company."""
    code = "Q_E_GHG_REDUCTION_RATE"
    if code in skip_indicators:
        return []
    full_text = "\n".join(page.text for doc in documents for page in doc.pages)
    if _cn_reduction_disclosed(full_text):
        return []
    # A same-row year mapping is not enough when the issuer explicitly changed
    # the inventory boundary.  In particular, adding Scope 3 for the first time
    # makes the two totals arithmetically comparable but methodologically
    # incomparable, so a year-on-year reduction must not be inferred.
    if re.search(
        r"(?:本年|本年度|报告期|\d{4}\s*年)?\s*(?:首次|新(?:增|纳入)|开始)"
        r"[^。；\n]{0,40}(?:范围|范畴)\s*[三3]"
        r"|(?:范围|范畴)\s*[三3][^。；\n]{0,40}(?:首次|新(?:增|纳入)|开始)(?:纳入|计入|核算|披露)?",
        full_text,
    ):
        return []
    rows: list[_GhgReduction] = []
    for doc in documents:
        for page in doc.pages:
            rows.extend(_cn_ghg_reduction_rows(page.text, report_year, doc.source_file, page.page))
    if not rows or _distinct([item.rate for item in rows]):
        return []
    item = rows[0]
    evidence = f"中文两期总量表派生: {item.evidence} ({item.source_file} 第{item.source_page}页)"
    return [Observation(
        company_code=company_code, company_name=company_name, report_year=report_year,
        indicator_code=code, value=item.rate, status=ValueStatus.PENDING,
        source_url=next(
            doc.source_url for doc in documents if doc.source_file == item.source_file
        ),
        source_file=item.source_file, source_page=item.source_page,
        evidence_text=evidence[:500], confidence=.9,
    )]
