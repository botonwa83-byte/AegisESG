from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from .methodology import Methodology


def prioritize_quantitative_gaps(
    task_path: str | Path, sensitivity_path: str | Path, methodology: Methodology,
    top_n: int = 200,
) -> tuple[list[dict], dict]:
    with Path(task_path).open(encoding="utf-8-sig", newline="") as stream:
        tasks = list(csv.DictReader(stream))
    with Path(sensitivity_path).open(encoding="utf-8") as stream:
        sensitivity = json.load(stream)
    risks = {item["company_code"]: item for item in sensitivity["companies"]}
    population = Counter(row["indicator_code"] for row in tasks if row["status"] == "candidate_available")
    maximum_weight = max(item.weight for item in methodology.quantitative)
    maximum_population = max(population.values(), default=1)
    excluded = set()
    ranked = []
    for row in tasks:
        if row["status"] != "missing_candidate":
            continue
        code = row["company_code"].strip().upper()
        if code not in risks:
            excluded.add(code); continue
        indicator = methodology.by_code[row["indicator_code"]]
        risk = risks[code]
        best, worst = int(risk["best_rank"]), int(risk["worst_rank"])
        crosses = best <= top_n <= worst
        distance = 0 if crosses else min(abs(best - top_n), abs(worst - top_n))
        boundary = 1.0 if crosses else 1.0 / (1.0 + distance / 50.0)
        instability = min(float(risk["rank_span"]) / 100.0, 1.0)
        weight = indicator.weight / maximum_weight
        key = 1.0 if indicator.key_indicator else 0.0
        scarcity = 1.0 - population[indicator.code] / maximum_population
        impact = 100 * (.25 * boundary + .25 * instability + .25 * weight + .15 * key + .10 * scarcity)
        ranked.append((impact, code, indicator.code, row, best, worst, crosses,
                       boundary, instability, weight, key, scarcity))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    rows = []
    for index, item in enumerate(ranked, 1):
        impact, _, _, raw, best, worst, crosses, boundary, instability, weight, key, scarcity = item
        indicator = methodology.by_code[raw["indicator_code"]]
        rows.append({
            "impact_rank": index, "impact_score": round(impact, 6),
            "best_rank": best, "worst_rank": worst, "rank_span": worst - best,
            "crosses_top_n": crosses, "boundary_risk": round(boundary, 6),
            "instability_risk": round(instability, 6), "weight_risk": round(weight, 6),
            "key_indicator_risk": key, "population_scarcity_risk": round(scarcity, 6),
            "indicator_population": population[indicator.code],
            "neutral_vs_zero_total_score_delta": round(indicator.weight * .5 * methodology.quantitative_ratio, 6),
            **raw,
        })
    return rows, {
        "policy_version": "quantitative-gap-rank-impact-v1", "top_n_boundary": top_n,
        "gap_count": len(rows), "excluded_company_codes": sorted(excluded),
        "crosses_boundary_count": sum(item["crosses_top_n"] for item in rows),
        "high_impact_count": sum(item["impact_score"] >= 75 for item in rows),
        "key_indicator_gap_count": sum(item["key_indicator"].lower() == "true" for item in rows),
        "applicable": True,
    }


def write_quantitative_gap_priority(output_path: str | Path, summary_path: str | Path,
                                    rows: list[dict], summary: dict) -> None:
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
        if rows: writer.writeheader(); writer.writerows(rows)
    summary_output = Path(summary_path); summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_quantitative_gap_batch(rows_path: str | Path, company_limit: int = 25,
                                 tasks_per_company: int = 10) -> tuple[list[dict], list[dict], dict]:
    with Path(rows_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows: grouped[row["company_code"]].append(row)
    companies = []
    for code, items in grouped.items():
        scores = sorted((float(item["impact_score"]) for item in items), reverse=True)
        companies.append({
            "company_code": code, "company_name": items[0]["company_name"],
            "company_impact_score": round(scores[0] + sum(scores[:5]) / 10, 6),
            "gap_count": len(items), "high_impact_gap_count": sum(score >= 75 for score in scores),
            "top_indicator_codes": "|".join(item["indicator_code"] for item in items[:tasks_per_company]),
        })
    companies.sort(key=lambda item: (-item["company_impact_score"], item["company_code"]))
    selected = companies[:company_limit]; selected_codes = {item["company_code"] for item in selected}
    tasks = []
    for code in selected_codes:
        for row in grouped[code][:tasks_per_company]:
            prefix = row["indicator_code"][:3]
            action = "inspect_esg_tables" if prefix == "Q_E" else (
                "rerun_financial_derivation" if prefix == "Q_G" else "inspect_social_disclosures"
            )
            tasks.append({"batch_task_rank": 0, "batch_action": action, **row})
    tasks.sort(key=lambda item: (int(item["impact_rank"]), item["company_code"], item["indicator_code"]))
    for index, item in enumerate(tasks, 1): item["batch_task_rank"] = index
    return selected, tasks, {
        "policy_version": "quantitative-gap-batch-v1", "selected_company_count": len(selected),
        "selected_task_count": len(tasks), "tasks_per_company": tasks_per_company,
        "scoring_authorized": False,
    }
