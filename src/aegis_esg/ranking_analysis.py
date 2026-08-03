from __future__ import annotations

import json
import math
from collections import Counter
from itertools import combinations
from pathlib import Path

from .methodology import Methodology
from .models import Observation
from .scoring import MissingStrategy, ScoringEngine


SENSITIVITY_STRATEGIES = tuple(MissingStrategy)


def validate_ranking_mode(
    mode: str, observations: list[Observation], missing_strategy: str | None,
) -> MissingStrategy:
    if mode not in {"preview", "research", "release"}:
        raise ValueError(f"未知排名模式: {mode}")
    if mode == "release" and not missing_strategy:
        raise ValueError("正式排名必须显式指定已冻结的缺失策略版本")
    if mode == "release":
        pending = [item for item in observations if item.status.value == "pending"]
        if pending:
            raise ValueError(f"正式排名输入包含{len(pending)}项pending观测")
        research_only = [item for item in observations if "[research-only:" in item.evidence_text]
        if research_only:
            raise ValueError(f"正式排名输入包含{len(research_only)}项研究域机器观测")
    selected = missing_strategy or (
        MissingStrategy.INDICATOR_NEUTRAL_V1.value
        if mode == "research" else MissingStrategy.LEGACY_ZERO_V1.value
    )
    return MissingStrategy(selected)


def analyze_missing_sensitivity(observations: list[Observation], methodology: Methodology) -> dict:
    rankings = {
        strategy.value: ScoringEngine(methodology).evaluate(observations, strategy)
        for strategy in SENSITIVITY_STRATEGIES
    }
    by_strategy = {
        name: {item.company_code: item for item in rows}
        for name, rows in rankings.items()
    }
    company_codes = sorted(set().union(*(set(rows) for rows in by_strategy.values())))
    companies = []
    for code in company_codes:
        available = {
            name: rows[code] for name, rows in by_strategy.items() if code in rows
        }
        ranks = {name: item.rank for name, item in available.items()}
        scores = {name: item.total_score for name, item in available.items()}
        rank_values = [int(value) for value in ranks.values() if value is not None]
        score_values = list(scores.values())
        sample = next(iter(available.values()))
        rank_span = max(rank_values) - min(rank_values)
        credibility = _credibility_grade(sample.disclosure_rate, rank_span)
        companies.append({
            "company_code": code,
            "company_name": sample.company_name,
            "disclosure_rate": sample.disclosure_rate,
            "ranks": ranks,
            "scores": scores,
            "best_rank": min(rank_values),
            "worst_rank": max(rank_values),
            "rank_span": rank_span,
            "score_span": round(max(score_values) - min(score_values), 4),
            "credibility_grade": credibility,
        })
    companies.sort(key=lambda item: (-item["rank_span"], item["company_code"]))
    comparisons = []
    for left, right in combinations(by_strategy, 2):
        shared = sorted(set(by_strategy[left]) & set(by_strategy[right]))
        left_ranks = [int(by_strategy[left][code].rank or 0) for code in shared]
        right_ranks = [int(by_strategy[right][code].rank or 0) for code in shared]
        comparisons.append({
            "left": left,
            "right": right,
            "spearman_rank_correlation": round(_pearson(left_ranks, right_ranks), 6),
            "top_50_overlap_rate": _top_overlap(by_strategy[left], by_strategy[right], 50),
            "top_100_overlap_rate": _top_overlap(by_strategy[left], by_strategy[right], 100),
            "top_200_overlap_rate": _top_overlap(by_strategy[left], by_strategy[right], 200),
        })
    grades = Counter(item["credibility_grade"] for item in companies)
    return {
        "strategy_versions": [item.value for item in SENSITIVITY_STRATEGIES],
        "company_count": len(companies),
        "unstable_company_count": sum(item["rank_span"] > 10 for item in companies),
        "max_rank_span": max((item["rank_span"] for item in companies), default=0),
        "credibility_grade_counts": {grade: grades[grade] for grade in "ABCD"},
        "strategy_comparisons": comparisons,
        "companies": companies,
    }


def write_sensitivity_report(path: str | Path, report: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _credibility_grade(disclosure_rate: float, rank_span: int) -> str:
    if disclosure_rate >= 80 and rank_span <= 10:
        return "A"
    if disclosure_rate >= 60 and rank_span <= 25:
        return "B"
    if disclosure_rate >= 40 and rank_span <= 50:
        return "C"
    return "D"


def _top_overlap(left: dict, right: dict, limit: int) -> float:
    left_codes = {code for code, item in left.items() if item.rank is not None and item.rank <= limit}
    right_codes = {code for code, item in right.items() if item.rank is not None and item.rank <= limit}
    denominator = max(len(left_codes), len(right_codes), 1)
    return round(len(left_codes & right_codes) / denominator, 6)


def _pearson(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    return numerator / (left_scale * right_scale) if left_scale and right_scale else 0.0
