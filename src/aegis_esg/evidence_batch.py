from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


def build_evidence_collection_batch(
    impact_path: str | Path, company_limit: int = 25,
) -> tuple[list[dict], list[dict], dict]:
    if company_limit <= 0:
        raise ValueError("批次公司数必须大于0")
    with Path(impact_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["company_code"].strip().upper()].append(row)
    companies = []
    for code, gaps in grouped.items():
        scores = [float(item["impact_score"]) for item in gaps]
        companies.append({
            "company_code": code, "company_name": gaps[0]["company_name"],
            "company_impact_score": round(max(scores) + sum(sorted(scores, reverse=True)[:5]) / 10, 6),
            "maximum_gap_impact": max(scores), "gap_count": len(gaps),
            "crosses_top_n_count": sum((item["crosses_top_n"].lower() == "true") for item in gaps),
            "high_impact_gap_count": sum(float(item["impact_score"]) >= 75 for item in gaps),
            "missing_esg_document": any(item["missing_esg_document"].lower() == "true" for item in gaps),
            "top_indicator_codes": "|".join(item["indicator_code"] for item in gaps[:5]),
            "next_action": (
                "discover_esg_report" if gaps[0]["esg_status"] not in {"collected", "embedded_in_annual"}
                else "rescan_collected_reports"
            ),
        })
    companies.sort(key=lambda item: (-item["company_impact_score"], item["company_code"]))
    selected = companies[:company_limit]
    selected_codes = {item["company_code"] for item in selected}
    tasks = []
    for row in rows:
        if row["company_code"].strip().upper() in selected_codes:
            tasks.append({"batch_task_rank": len(tasks) + 1, **row})
    return selected, tasks, {
        "policy_version": "evidence-collection-batch-v1", "company_limit": company_limit,
        "selected_company_count": len(selected), "selected_gap_count": len(tasks),
        "selected_high_impact_gap_count": sum(float(item["impact_score"]) >= 75 for item in tasks),
        "requires_human_scoring": False, "scoring_authorized": False,
    }


def write_evidence_collection_batch(company_path: str | Path, task_path: str | Path,
                                    summary_path: str | Path, companies: list[dict],
                                    tasks: list[dict], summary: dict) -> None:
    for path, rows in ((company_path, companies), (task_path, tasks)):
        output = Path(path); output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
            if rows: writer.writeheader(); writer.writerows(rows)
    output = Path(summary_path); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
