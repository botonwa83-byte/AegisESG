from __future__ import annotations

import csv
import json
from pathlib import Path


def prioritize_qualitative_gaps(
    gaps_path: str | Path, sensitivity_path: str | Path, coverage_path: str | Path,
    top_n: int = 200,
) -> tuple[list[dict], dict]:
    with Path(sensitivity_path).open(encoding="utf-8") as stream:
        sensitivity = json.load(stream)
    risks = {item["company_code"]: item for item in sensitivity["companies"]}
    with Path(coverage_path).open(encoding="utf-8-sig", newline="") as stream:
        coverage_rows = list(csv.DictReader(stream))
    coverage = {item["stock_code"].strip().upper(): item["esg_status"].strip() for item in coverage_rows}
    with Path(gaps_path).open(encoding="utf-8-sig", newline="") as stream:
        gaps = list(csv.DictReader(stream))
    maximum_weight = max((float(item["indicator_weight"]) for item in gaps), default=1.0)
    ranked = []
    for row in gaps:
        code = row["company_code"].strip().upper()
        if code not in risks or code not in coverage:
            raise ValueError(f"敏感性或覆盖审计缺少公司: {code}")
        risk = risks[code]
        best, worst = int(risk["best_rank"]), int(risk["worst_rank"])
        crosses = best <= top_n <= worst
        distance = 0 if crosses else min(abs(best - top_n), abs(worst - top_n))
        boundary = 1.0 if crosses else 1.0 / (1.0 + distance / 50.0)
        instability = min(float(risk["rank_span"]) / 100.0, 1.0)
        weight = float(row["indicator_weight"]) / maximum_weight
        missing_document = 1.0 if coverage[code] not in {"collected", "embedded_in_annual"} else 0.0
        impact = 100 * (.35 * boundary + .30 * instability + .25 * weight + .10 * missing_document)
        ranked.append((impact, code, row["indicator_code"], row, best, worst, crosses,
                       boundary, instability, weight, missing_document))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    output = []
    for index, item in enumerate(ranked, 1):
        impact, code, _, row, best, worst, crosses, boundary, instability, weight, missing_document = item
        output.append({
            "impact_rank": index, "impact_score": round(impact, 6),
            "best_rank": best, "worst_rank": worst, "rank_span": worst - best,
            "crosses_top_n": crosses, "boundary_risk": round(boundary, 6),
            "instability_risk": round(instability, 6), "weight_risk": round(weight, 6),
            "missing_esg_document": bool(missing_document), "esg_status": coverage[code], **row,
        })
    return output, {
        "policy_version": "qualitative-gap-rank-impact-v1", "top_n_boundary": top_n,
        "gap_count": len(output), "company_count": len({item["company_code"] for item in output}),
        "crosses_boundary_count": sum(item["crosses_top_n"] for item in output),
        "high_impact_count": sum(item["impact_score"] >= 75 for item in output),
        "applicable": True,
    }


def write_gap_priority(output_path: str | Path, summary_path: str | Path, rows: list[dict], summary: dict) -> None:
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
        if rows: writer.writeheader(); writer.writerows(rows)
    summary_output = Path(summary_path); summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
