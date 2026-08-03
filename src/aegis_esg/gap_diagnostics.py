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
    "Q_E_SO2_INTENSITY": r"(?:SOx?|sulphur\s+dioxide|二氧化硫)",
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
        "policy_version": "quantitative-gap-diagnostic-v2", "task_count": len(output),
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
        if _RMB.search(text) and re.search(r"(?:revenue|营业收入)", text, re.I):
            return "possible_total_plus_rmb_revenue_derivation", excerpt
        return "related_disclosure_without_compatible_intensity", excerpt
    return "no_matching_disclosure_in_text", ""


def _classify_specialized(indicator_code: str, text: str) -> tuple[str, str] | None:
    patterns = {
        "Q_G_DEBT_ASSET_RATE": (
            r"(?:资产总计|Total\s+assets)", r"(?:负债合计|Total\s+liabilities)",
            "possible_balance_sheet_formula_closure",
        ),
        "Q_S_RD_RATE": (
            r"(?:研发(?:投入|费用)|R&D\s+(?:investment|expenses?))", r"(?:营业收入|revenue)",
            "possible_rd_revenue_formula_closure",
        ),
        "Q_S_SAFETY_INVEST_RATE": (
            r"(?:安全生产投入|work\s+safety\s+investment|safety\s+investment)", r"(?:营业收入|revenue)",
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
