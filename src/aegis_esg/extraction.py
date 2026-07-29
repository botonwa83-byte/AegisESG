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
    return candidates


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("（", "(").replace("）", ")")


def _canonical_unit(unit: str) -> str:
    compact = unit.replace("二氧化碳当量", "").replace("CO2e", "")
    return compact


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
    percentage_codes = {"Q_S_SAFETY_INVEST_RATE", "Q_S_RD_RATE", "Q_G_DEBT_ASSET_RATE", "Q_G_ROE"}
    if code in percentage_codes and value > 100:
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
    for start in starts:
        statement_pages = []
        for page in pages[start:start + 6]:
            if statement_pages and end.search(page.text):
                break
            statement_pages.append(page)
        assets = _find_english_statement_fact(statement_pages, r"Total assets(?!\s+less)")
        liabilities = _find_english_statement_fact(statement_pages, r"Total liabilities(?!\s+and)")
        if assets and liabilities and assets.values[0] > 0:
            value = liabilities.values[0] / assets.values[0] * 100
            if 0 <= value <= 1000:
                evidence = "English consolidated statement derived: " + liabilities.evidence + " | " + assets.evidence
                return [("Q_G_DEBT_ASSET_RATE", value, max(assets.page, liabilities.page), evidence)]
    return []


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
            if values:
                evidence = re.sub(r"\s+", " ", match.group(0)).strip()
                return StatementFact(tuple(values[:2]), page.page, evidence[:220])
    return None


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
