"""交易所官方公告标题的严格分类与优先级策略。

发现适配器共享同一套规则，避免把业绩说明会、更正公告、英文版或H股版
误认为中文正式年报。任何版本的选择都只改变同一公司同类文档的优先级，
不会把非报告类公告纳入正式文档索引。
"""
from __future__ import annotations

import re

# 标题中出现这些词时，该公告只是引用年报/ESG报告，本身不是报告全文。
NON_REPORT_TERMS = (
    "摘要",
    "提示性公告",
    "关于披露",
    "取消",
    "问询函",
    "问询",
    "回复",
    "业绩说明会",
    "业绩说明",
    "说明会",
    "网上说明",
    "简版",
    "半年度",
    "季度报告",
)

# 修订/更正类标题只有括号版全文才保留；“关于……更正/修订的公告”一律拒绝。
_REVISION_KEEP_MARKERS = (
    "(修订版)",
    "(修订稿)",
    "(更新后)",
    "(更新版)",
    "(更正后)",
)

_ENGLISH_PATTERN = re.compile(r"英文|英语|英文版|english", re.I)


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", title).replace("（", "(").replace("）", ")")


def is_non_report_title(compact: str, report_year: str) -> bool:
    if report_year not in compact:
        return True
    if any(term in compact for term in NON_REPORT_TERMS):
        return True
    if ("更正" in compact or "修订" in compact) and not any(
        marker in compact for marker in _REVISION_KEEP_MARKERS
    ):
        return True
    return False


def classify_report_title(compact: str, report_year: str, esg_terms: tuple[str, ...]) -> str | None:
    """Return annual_report/esg_report for genuine report full texts, else None."""
    if is_non_report_title(compact, report_year):
        return None
    if any(
        term in compact
        for term in (f"{report_year}年年度报告", f"{report_year}年度报告", f"{report_year}年年报")
    ):
        return "annual_report"
    return "esg_report" if any(term in compact for term in esg_terms) else None


def title_preference(compact: str, kind: str) -> int:
    """Lower is better: Chinese A-share full text always beats alternate versions."""
    if _ENGLISH_PATTERN.search(compact):
        return 3
    if kind == "annual_report" and ("H股" in compact or "同步披露" in compact):
        return 2
    return 0


def select_preferred(disclosures: list, kind: str):
    """Pick the best document of one kind: preference first, then latest date."""
    candidates = [item for item in disclosures if item.document_type == kind]
    if not candidates:
        return None
    ordered = sorted(
        candidates,
        key=lambda item: (item.published_date, item.title, item.source_url),
        reverse=True,
    )
    ordered.sort(key=lambda item: title_preference(normalize_title(item.title), kind))
    return ordered[0]
