from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


_SUBJECTS = {
    "Q_E_GHG_INTENSITY": r"(?:GHG|greenhouse\s+gas|温室气体|碳排放)",
    "Q_E_ENERGY_INTENSITY": r"(?:energy|能源|综合能耗)",
    "Q_E_SOLID_WASTE_INTENSITY": r"(?:non[- ]hazardous\s+waste|solid\s+waste|一般固体废物|固体废物)",
    # The fixed methodology names SO2, not the broader SOx family.
    "Q_E_SO2_INTENSITY": r"(?:SO2|sulphur\s+dioxide|sulfur\s+dioxide|二氧化硫)",
    "Q_E_NOX_INTENSITY": r"(?:NOx|nitrogen\s+oxides?|氮氧化物)",
    "Q_E_WATER_INTENSITY": r"(?:water\s+(?:consumption|withdrawal)|耗水|用水)",
}
_INTENSITY = r"(?:intensit(?:y|ies)|强度|密度)"
_FOREIGN = re.compile(r"(?:HK\s*\$|HKD|US\s*\$|USD|港元|美元)", re.I)
_RMB = re.compile(r"(?:RMB|人民币|万元|million\s+RMB|RMB\s*['’]?000)", re.I)
_RMB_REVENUE_DENOMINATOR = re.compile(
    r"(?:每|单位|/|per\s+)(?:营业收入|营收|revenue)?[^。；;\n]{0,20}"
    r"(?:万元|百万元|亿元|RMB|人民币|million\s+RMB)"
    r"|(?:万元|百万元|亿元|million\s+RMB)[^。；;\n]{0,20}(?:营业收入|营收|revenue)",
    re.I,
)
_NON_REVENUE = re.compile(r"(?:production|output|product|MWh|kWh|GJ|tonne\s+product|产量|发电量|产品)", re.I)
_PHYSICAL_TOTALS = {
    "Q_E_GHG_INTENSITY": re.compile(
        r"(?:温室气体(?:排放)?总量|碳排放总量|total\s+(?:GHG|greenhouse\s+gas)\s+emissions?)"
        r"[^。；;\n]{0,120}?[\d,]+(?:\.\d+)?\s*(?:吨|千克|公斤|kg|tonnes?|tCO2e)", re.I,
    ),
    "Q_E_ENERGY_INTENSITY": re.compile(
        r"(?:能源|能耗)(?:消耗|消费)?总量[^。；;\n]{0,120}?[\d,]+(?:\.\d+)?\s*"
        r"(?:吨标准煤|tce|千瓦时|兆瓦时|kWh|MWh|吉焦|GJ)", re.I,
    ),
    "Q_E_SOLID_WASTE_INTENSITY": re.compile(
        r"(?:一般固体废物|固体废物|non[- ]hazardous\s+waste|solid\s+waste)(?:产生|排放|处置)?(?:总)?量?"
        r"[^。；;\n]{0,100}?[\d,]+(?:\.\d+)?\s*(?:吨|千克|公斤|kg|tonnes?)", re.I,
    ),
    "Q_E_SO2_INTENSITY": re.compile(
        r"(?:SO2|sulphur\s+dioxide|sulfur\s+dioxide|二氧化硫)(?:排放)?(?:总)?量?[^。；;\n]{0,100}?"
        r"[\d,]+(?:\.\d+)?\s*(?:吨|千克|公斤|kg|tonnes?)", re.I,
    ),
    "Q_E_NOX_INTENSITY": re.compile(
        r"(?:NOx|nitrogen\s+oxides?|氮氧化物)(?:排放)?(?:总)?量?[^。；;\n]{0,100}?"
        r"[\d,]+(?:\.\d+)?\s*(?:吨|千克|公斤|kg|tonnes?)", re.I,
    ),
    "Q_E_WATER_INTENSITY": re.compile(
        r"(?:耗水|用水|water\s+(?:consumption|withdrawal))(?:总)?量?[^。；;\n]{0,100}?"
        r"[\d,]+(?:\.\d+)?\s*(?:立方米|吨|m[³3]|tonnes?)", re.I,
    ),
}


def diagnose_quantitative_gap_batch(
    task_path: str | Path, document_index_path: str | Path, text_root: str | Path,
) -> tuple[list[dict], dict]:
    with Path(task_path).open(encoding="utf-8-sig", newline="") as stream:
        tasks = list(csv.DictReader(stream))
    with Path(document_index_path).open(encoding="utf-8-sig", newline="") as stream:
        documents = list(csv.DictReader(stream))
    by_company: dict[str, list[dict]] = defaultdict(list)
    for row in documents:
        by_company[row["company_code"].strip().upper()].append(row)
    cache: dict[str, str] = {}
    output = []
    counts = Counter()
    for task in tasks:
        code = task["company_code"].strip().upper()
        texts = []
        files = []
        for document in by_company.get(code, []):
            if int(document["report_year"]) != 2025:
                continue
            source = Path(document["local_path"])
            text_path = Path(text_root) / source.relative_to("data/raw")
            text_path = text_path.with_suffix(".txt")
            if text_path.is_file():
                key = str(text_path)
                cache.setdefault(key, text_path.read_text(encoding="utf-8", errors="replace"))
                texts.append(cache[key]); files.append(key)
        category, excerpt = _classify(task["indicator_code"], "\n".join(texts)) if texts else ("missing_text", "")
        counts[category] += 1
        output.append({
            **task, "diagnostic_category": category, "diagnostic_excerpt": excerpt,
            "text_file_count": len(files), "diagnostic_text_files": "|".join(files),
            "scoring_authorized": False,
        })
    return output, {
        "policy_version": "quantitative-gap-diagnostic-v6", "task_count": len(output),
        "category_counts": dict(sorted(counts.items())), "scoring_authorized": False,
        "complete": True,
    }


def _classify(indicator_code: str, text: str) -> tuple[str, str]:
    specialized = _classify_specialized(indicator_code, text)
    if specialized is not None:
        return specialized
    if not indicator_code.startswith("Q_E_"):
        return "no_closed_formula_detected", ""
    subject = _SUBJECTS.get(indicator_code)
    if not subject:
        return "requires_specialized_environmental_diagnostic", ""
    direct = re.compile(rf"(?:{subject}[\s\S]{{0,160}}{_INTENSITY}|{_INTENSITY}[\s\S]{{0,160}}{subject})", re.I)
    match = direct.search(text)
    if match:
        context = text[max(0, match.start() - 250):match.end() + 250]
        excerpt = re.sub(r"\s+", " ", context).strip()[:500]
        matched = match.group(0)
        metric_context = text[match.start():match.end() + 180]
        if _FOREIGN.search(metric_context): return "disclosed_foreign_currency_denominator", excerpt
        if _RMB_REVENUE_DENOMINATOR.search(metric_context): return "likely_methodology_compatible_rule_gap", excerpt
        if _NON_REVENUE.search(metric_context): return "disclosed_non_revenue_denominator", excerpt
        return "ambiguous_intensity_disclosure", excerpt
    total = re.search(subject, text, re.I)
    if total:
        context = text[max(0, total.start() - 150):total.end() + 350]
        excerpt = re.sub(r"\s+", " ", context).strip()[:500]
        physical = _PHYSICAL_TOTALS.get(indicator_code)
        physical_match = physical.search(text) if physical else None
        rmb_revenue = (
            _RMB.search(text) and re.search(r"(?:revenue|营业收入)", text, re.I)
        ) or re.search(r"营业收入[^。；;\n]{0,16}(?:人民币)?元", text)
        if physical_match and rmb_revenue:
            physical_context = text[max(0, physical_match.start() - 120):physical_match.end() + 180]
            if re.search(
                r"(?:核算|统计|披露|报告)(?:边界|范围)[^。；;\n]{0,80}(?:基地|子公司|场所|sites?|facilit(?:y|ies))",
                physical_context, re.I,
            ):
                excerpt = re.sub(r"\s+", " ", physical_context).strip()[:500]
                return "disclosed_scope_mismatch_requires_review", excerpt
            if not re.search(
                r"(?:累计|减少|减排|避免|交易|配额|目标|计划|预计|reduction|saving|avoided|capacity)",
                physical_context, re.I,
            ):
                excerpt = re.sub(r"\s+", " ", physical_context).strip()[:500]
                return "possible_total_plus_rmb_revenue_derivation", excerpt
        return "related_disclosure_without_compatible_intensity", excerpt
    return "no_matching_disclosure_in_text", ""


def _classify_specialized(indicator_code: str, text: str) -> tuple[str, str] | None:
    if indicator_code == "Q_E_ALTERNATIVE_WATER_RATE":
        subject = r"(?:再生水|回用水|中水|循环水|替代水源|recycled\s+water|reused\s+water|alternative\s+water)"
        direct = re.search(
            rf"(?:{subject})[^。；;\n]{{0,100}}?(?:占比|比例|rate|percentage)"
            rf"[^。；;\n]{{0,60}}?[\d,]+(?:\.\d+)?\s*%"
            rf"|(?:占比|比例|rate|percentage)[^。；;\n]{{0,80}}?(?:{subject})"
            rf"[^。；;\n]{{0,60}}?[\d,]+(?:\.\d+)?\s*%",
            text, re.I,
        )
        if direct:
            return "possible_direct_alternative_water_rate", re.sub(r"\s+", " ", direct.group(0)).strip()[:500]
        numerator = re.search(
            rf"(?:{subject})(?:使用|用|消耗|取用|量|consumption|used|use)?"
            rf"[^。；;\n]{{0,100}}?[\d,]+(?:\.\d+)?\s*(?:立方米|吨|m[³3]|tonnes?)",
            text, re.I,
        )
        denominator = re.search(
            r"(?:总用水量|用水总量|总耗水量|total\s+water\s+(?:consumption|use|withdrawal))"
            r"[^。；;\n]{0,100}?[\d,]+(?:\.\d+)?\s*(?:立方米|吨|m[³3]|tonnes?)",
            text, re.I,
        )
        if numerator and denominator:
            start = min(numerator.start(), denominator.start())
            return "possible_alternative_water_formula_closure", re.sub(r"\s+", " ", text[start:start + 500]).strip()
        return "related_fields_incomplete", ""
    patterns = {
        "Q_G_DEBT_ASSET_RATE": (
            r"(?:资产总计|Total\s+assets)", r"(?:负债合计|Total\s+liabilities)",
            "possible_balance_sheet_formula_closure",
        ),
        "Q_S_RD_RATE": (
            r"(?:研发(?:投入|费用)|R&D\s+(?:investment|expenses?))"
            r"[^。；;\n]{0,160}[\d,]+(?:\.\d+)?\s*(?:元|万元|百万元|RMB|CNY|HKD|HK\$|US\$)",
            r"(?:营业收入|revenue)[^。；;\n]{0,160}[\d,]+(?:\.\d+)?",
            "possible_rd_revenue_formula_closure",
        ),
        "Q_S_SAFETY_INVEST_RATE": (
            r"(?:安全生产投入|work\s+safety\s+investment|safety\s+investment)"
            r"[^。；;\n]{0,160}[\d,]+(?:\.\d+)?\s*(?:元|万元|百万元|RMB|CNY|HKD|HK\$|US\$)",
            r"(?:营业收入|revenue)[^。；;\n]{0,160}[\d,]+(?:\.\d+)?",
            "possible_safety_revenue_formula_closure",
        ),
        "Q_E_GHG_REDUCTION_RATE": (
            r"(?:温室气体(?:排放)?总量|(?:total\s+)?(?:GHG|greenhouse\s+gas)\s+emissions?)"
            r"(?=[^。；;\n]{0,140}(?:吨|千克|kg|tonnes?|tCO2e))"
            r"[^。；;\n]{0,180}[\d,]+(?:\.\d+)?[^。；;\n]{0,80}[\d,]+(?:\.\d+)?",
            r"(?:2025[\s\S]{0,120}2024|2024[\s\S]{0,120}2025)",
            "possible_two_year_ghg_formula_closure",
        ),
        "Q_E_HAZ_WASTE_INTENSITY": (
            r"(?:危险废物|危废|hazardous\s+waste)"
            r"[^。；;\n]{0,100}[\d,]+(?:\.\d+)?\s*(?:吨|千克|公斤|kg|tonnes?)",
            r"(?:营业收入|revenue|百万元|万元)",
            "possible_hazardous_waste_revenue_closure",
        ),
        "Q_E_CLEAN_ENERGY_INTENSITY": (
            r"(?:"
            r"(?:清洁能源|可再生能源)(?:使用|消耗|消费|采购)(?:总)?量"
            r"|(?:绿色电力|绿电)(?:使用|消耗|消费|采购)(?:总)?量"
            r"|(?:renewable|clean)\s+energy\s+(?:consumption|used|purchased)"
            r")[^。；;\n]{0,100}[\d,]+(?:\.\d+)?\s*"
            r"(?:千瓦时|兆瓦时|吉焦|kWh|MWh|GJ)",
            r"(?:营业收入|revenue|百万元|万元)",
            "possible_clean_energy_revenue_closure",
        ),
    }
    if indicator_code == "Q_S_DIVIDEND_PER_SHARE":
        match = re.search(r"(?:每股(?:现金)?分红|股息每股|dividend\s+per\s+share)[\s\S]{0,100}", text, re.I)
        if not match: return "no_dividend_per_share_disclosure", ""
        excerpt = re.sub(r"\s+", " ", match.group(0)).strip()[:500]
        if re.search(r"(?:HKD|HK\$|港元|cents?)", match.group(0), re.I):
            return "dividend_disclosed_foreign_currency", excerpt
        if re.search(r"(?:RMB|人民币|元)", match.group(0), re.I):
            return "possible_rmb_dividend_rule_gap", excerpt
        return "ambiguous_dividend_per_share", excerpt
    if indicator_code not in patterns:
        return None
    left, right, category = patterns[indicator_code]
    left_match = re.search(left, text, re.I)
    right_match = re.search(right, text, re.I)
    if not left_match or not right_match:
        return ("related_fields_incomplete", "")
    start = min(left_match.start(), right_match.start())
    excerpt = re.sub(r"\s+", " ", text[start:start + 500]).strip()
    return category, excerpt


def write_gap_diagnostics(output_path: str | Path, summary_path: str | Path,
                          rows: list[dict], summary: dict) -> None:
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
        if rows: writer.writeheader(); writer.writerows(rows)
    summary_output = Path(summary_path); summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
