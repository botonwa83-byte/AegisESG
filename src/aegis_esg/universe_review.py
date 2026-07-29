from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .universe import UniverseCompany, _is_unclassified
from .universe_builder import read_exchange_snapshot


@dataclass(frozen=True)
class UniverseEvidenceTask:
    stock_code: str
    company_name: str
    exchange: str
    current_sub_industry: str
    snapshot_industry: str
    entity_id: str
    industry_status: str
    entity_status: str
    priority: int
    next_action: str
    snapshot_source_url: str
    snapshot_as_of_date: str


def plan_universe_evidence(
    universe: Iterable[UniverseCompany], snapshot_path: str | Path,
) -> tuple[list[UniverseEvidenceTask], dict]:
    snapshot_rows = read_exchange_snapshot(snapshot_path)
    snapshot = {item.stock_code: item for item in snapshot_rows}
    if len(snapshot) != len(snapshot_rows):
        raise ValueError("官方快照存在重复证券代码")
    tasks = []
    for company in universe:
        if not company.included:
            continue
        security = snapshot.get(company.stock_code)
        if security is None:
            industry_status = "snapshot_unmatched"
            snapshot_industry = ""
            source_url = ""
            as_of_date = ""
        else:
            snapshot_industry = security.industry
            source_url = security.source_url
            as_of_date = security.as_of_date
            industry_status = "pending_evidence" if _is_unclassified(company.sub_industry) else "classified"
        entity_status = "security_id_only" if company.entity_id == company.stock_code else "explicit_entity"
        if industry_status == "snapshot_unmatched":
            priority, action = 0, "resolve_snapshot_match"
        elif industry_status == "pending_evidence" and company.exchange == "HKEX":
            priority, action = 1, "collect_hkex_industry_and_chinese_name_evidence"
        elif industry_status == "pending_evidence":
            priority, action = 2, "review_energy_sub_industry_evidence"
        elif entity_status == "security_id_only":
            priority, action = 3, "review_entity_and_ah_relationship"
        else:
            priority, action = 9, "complete"
        tasks.append(UniverseEvidenceTask(
            company.stock_code, company.company_name, company.exchange,
            company.sub_industry, snapshot_industry, company.entity_id,
            industry_status, entity_status, priority, action, source_url, as_of_date,
        ))
    tasks.sort(key=lambda item: (item.priority, item.exchange, item.stock_code))
    industry_counts = Counter(item.industry_status for item in tasks)
    entity_counts = Counter(item.entity_status for item in tasks)
    action_counts = Counter(item.next_action for item in tasks)
    summary = {
        "included_company_count": len(tasks),
        "industry_status_counts": dict(sorted(industry_counts.items())),
        "entity_status_counts": dict(sorted(entity_counts.items())),
        "next_action_counts": dict(sorted(action_counts.items())),
        "pending_industry_count": industry_counts["pending_evidence"],
        "snapshot_unmatched_count": industry_counts["snapshot_unmatched"],
        "publishable": not industry_counts["pending_evidence"] and not industry_counts["snapshot_unmatched"],
    }
    return tasks, summary


def write_universe_evidence_plan(
    output_path: str | Path, summary_path: str | Path,
    tasks: Iterable[UniverseEvidenceTask], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(UniverseEvidenceTask.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in tasks)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
