from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .methodology import Methodology
from .resolution import ReviewTier


@dataclass(frozen=True)
class ImpactReviewTask:
    priority: int
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    indicator_weight: float
    tier: str
    candidate_count: int
    distinct_values: str
    max_confidence: float
    current_rank: int
    best_rank: int
    worst_rank: int
    rank_span: int
    crosses_top_200: bool
    conflict_risk: float
    boundary_risk: float
    instability_risk: float
    weight_risk: float
    confidence_risk: float
    impact_score: float
    baseline_confidence_rank: int
    baseline_weight_rank: int
    next_action: str


def prioritize_review_by_impact(
    tiers: list[ReviewTier], sensitivity_path: str | Path, methodology: Methodology,
    top_n: int = 200,
) -> tuple[list[ImpactReviewTask], dict]:
    if top_n <= 0:
        raise ValueError("排名边界必须大于0")
    with Path(sensitivity_path).open(encoding="utf-8") as stream:
        sensitivity = json.load(stream)
    company_risk = {item["company_code"]: item for item in sensitivity.get("companies", [])}
    manual = [item for item in tiers if item.tier != "auto_policy_eligible"]
    if not manual:
        return [], _summary([], top_n)
    unknown = sorted({item.company_code for item in manual} - set(company_risk))
    if unknown:
        raise ValueError(f"敏感性报告缺少审核公司: {unknown[0]}")
    maximum_weight = max(item.weight for item in methodology.indicators)
    confidence_order = {
        key: rank for rank, key in enumerate(sorted(
            ((item.company_code, item.report_year, item.indicator_code) for item in manual),
            key=lambda key: next(
                row.max_confidence for row in manual
                if (row.company_code, row.report_year, row.indicator_code) == key
            ),
        ), 1)
    }
    weight_order = {
        key: rank for rank, key in enumerate(sorted(
            ((item.company_code, item.report_year, item.indicator_code) for item in manual),
            key=lambda key: -methodology.by_code[key[2]].weight,
        ), 1)
    }
    draft = []
    tier_risk = {
        "manual_signature_required": 1.0,
        "consistent_multi_review": 0.55,
        "single_candidate_review": 0.4,
    }
    for item in manual:
        risk = company_risk[item.company_code]
        ranks = risk.get("ranks", {})
        current_rank = int(ranks.get("indicator_neutral_v1") or risk["best_rank"])
        best_rank = int(risk["best_rank"])
        worst_rank = int(risk["worst_rank"])
        crosses = best_rank <= top_n <= worst_rank
        distance = 0 if crosses else min(abs(best_rank - top_n), abs(worst_rank - top_n))
        boundary_risk = 1.0 if crosses else 1.0 / (1.0 + distance / 50.0)
        instability_risk = min(float(risk["rank_span"]) / 100.0, 1.0)
        weight_risk = methodology.by_code[item.indicator_code].weight / maximum_weight
        confidence_risk = max(0.0, min(1.0, 1.0 - item.max_confidence))
        conflict_risk = tier_risk.get(item.tier, 0.5)
        impact = 100 * (
            0.35 * conflict_risk + 0.25 * boundary_risk + 0.20 * instability_risk
            + 0.15 * weight_risk + 0.05 * confidence_risk
        )
        key = (item.company_code, item.report_year, item.indicator_code)
        draft.append((impact, item, current_rank, best_rank, worst_rank, crosses,
                      conflict_risk, boundary_risk, instability_risk, weight_risk,
                      confidence_risk, confidence_order[key], weight_order[key]))
    draft.sort(key=lambda row: (-row[0], row[1].company_code, row[1].indicator_code))
    tasks = [
        ImpactReviewTask(
            priority=index, company_code=item.company_code, company_name=item.company_name,
            report_year=item.report_year, indicator_code=item.indicator_code,
            indicator_weight=methodology.by_code[item.indicator_code].weight,
            tier=item.tier, candidate_count=item.candidate_count,
            distinct_values=item.distinct_values, max_confidence=item.max_confidence,
            current_rank=current, best_rank=best, worst_rank=worst,
            rank_span=worst - best, crosses_top_200=crosses,
            conflict_risk=round(conflict, 6), boundary_risk=round(boundary, 6),
            instability_risk=round(instability, 6), weight_risk=round(weight, 6),
            confidence_risk=round(confidence, 6), impact_score=round(impact, 6),
            baseline_confidence_rank=confidence_rank, baseline_weight_rank=weight_rank,
            next_action=item.next_action,
        )
        for index, (impact, item, current, best, worst, crosses, conflict, boundary,
                    instability, weight, confidence, confidence_rank, weight_rank)
        in enumerate(draft, 1)
    ]
    return tasks, _summary(tasks, top_n)


def write_impact_review_plan(
    output_path: str | Path, summary_path: str | Path,
    tasks: list[ImpactReviewTask], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(ImpactReviewTask.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(item) for item in tasks)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _summary(tasks: list[ImpactReviewTask], top_n: int) -> dict:
    return {
        "policy_version": "rank-impact-v1",
        "top_n_boundary": top_n,
        "task_count": len(tasks),
        "conflict_task_count": sum(item.tier == "manual_signature_required" for item in tasks),
        "crosses_boundary_count": sum(item.crosses_top_200 for item in tasks),
        "high_impact_count": sum(item.impact_score >= 75 for item in tasks),
        "maximum_impact_score": max((item.impact_score for item in tasks), default=0),
        "applicable": False,
    }
