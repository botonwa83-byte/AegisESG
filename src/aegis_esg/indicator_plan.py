from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .methodology import Methodology
from .models import IndicatorKind, Observation, ValueStatus
from .universe import UniverseCompany


@dataclass(frozen=True)
class IndicatorTask:
    company_code: str
    company_name: str
    exchange: str
    report_year: int
    indicator_code: str
    indicator_name: str
    dimension: str
    kind: str
    key_indicator: bool
    weight: float
    status: str
    next_action: str
    priority: int
    source_file: str
    source_page: str


def plan_indicator_tasks(
    companies: Iterable[UniverseCompany], observations: Iterable[Observation],
    methodology: Methodology, report_year: int,
) -> tuple[list[IndicatorTask], dict]:
    selected = [item for item in companies if item.included]
    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for item in observations:
        if item.report_year == report_year:
            grouped[(item.company_code, item.indicator_code)].append(item)
    tasks = []
    for company in selected:
        for indicator in methodology.indicators:
            candidates = grouped.get((company.stock_code, indicator.code), [])
            chosen = _best(candidates)
            status = chosen.status.value if chosen else ValueStatus.MISSING.value
            action, priority = _action(status, indicator.kind, indicator.key_indicator)
            tasks.append(IndicatorTask(
                company.stock_code, company.company_name, company.exchange, report_year,
                indicator.code, indicator.name, indicator.dimension, indicator.kind.value,
                indicator.key_indicator, indicator.weight, status, action, priority,
                chosen.source_file if chosen else "",
                str(chosen.source_page) if chosen and chosen.source_page is not None else "",
            ))
    status_counts = Counter(item.status for item in tasks)
    action_counts = Counter(item.next_action for item in tasks)
    dimension_total = Counter(item.dimension for item in tasks)
    dimension_confirmed = Counter(item.dimension for item in tasks if item.status == "confirmed")
    company_confirmed = Counter(item.company_code for item in tasks if item.status == "confirmed")
    indicator_confirmed = Counter(item.indicator_code for item in tasks if item.status == "confirmed")
    total = len(tasks)
    summary = {
        "report_year": report_year,
        "company_count": len(selected),
        "indicator_count": len(methodology.indicators),
        "task_count": total,
        "confirmed_count": status_counts["confirmed"],
        "completion_rate": status_counts["confirmed"] / total if total else 0,
        "status_counts": dict(sorted(status_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "dimension_completion": {
            key: {
                "confirmed": dimension_confirmed[key], "total": dimension_total[key],
                "rate": dimension_confirmed[key] / dimension_total[key],
            } for key in sorted(dimension_total)
        },
        "fully_complete_companies": sum(value == len(methodology.indicators) for value in company_confirmed.values()),
        "empty_companies": len(selected) - len(company_confirmed),
        "indicator_population": {
            indicator.code: indicator_confirmed[indicator.code] for indicator in methodology.indicators
        },
        "publishable": bool(total) and status_counts["confirmed"] == total,
    }
    tasks.sort(key=lambda item: (item.priority, item.company_code, item.indicator_code))
    return tasks, summary


def write_indicator_plan(path: str | Path, summary_path: str | Path, tasks, summary: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(IndicatorTask.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in tasks)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _best(rows: list[Observation]) -> Observation | None:
    order = {
        ValueStatus.CONFIRMED: 0, ValueStatus.PENDING: 1,
        ValueStatus.NOT_APPLICABLE: 2, ValueStatus.MISSING: 3,
    }
    return min(rows, key=lambda item: (order[item.status], -item.confidence)) if rows else None


def _action(status: str, kind: IndicatorKind, key: bool) -> tuple[str, int]:
    if status == "confirmed":
        return "complete", 9
    if status == "pending":
        return "review_pending", 1 if key else 3
    if status == "not_applicable":
        return "verify_not_applicable", 2 if key else 4
    if kind == IndicatorKind.QUANTITATIVE:
        return "extract_or_derive", 0 if key else 2
    return "collect_qualitative_evidence", 5
