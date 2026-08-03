from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class EvidenceValidationRow:
    candidate_id: str
    company_code: str
    report_year: int
    indicator_code: str
    value: str
    source_file: str
    source_page: str
    evidence_text: str
    confidence: float
    candidate_constraints_passed: bool
    group_consistent: bool
    constraint_prediction: bool
    ground_truth_valid: str
    reviewer: str
    reviewed_at: str
    review_note: str


def prepare_e1_validation_sample(
    graph_path: str | Path, per_indicator_passed: int = 3,
) -> tuple[list[EvidenceValidationRow], dict]:
    if per_indicator_passed <= 0:
        raise ValueError("每指标通过样本数必须大于0")
    graph = _read_graph(graph_path)
    nodes = {item["id"]: item for item in graph["nodes"]}
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["from"]].append(edge)
    candidate_checks: dict[str, list[bool]] = defaultdict(list)
    group_consistency = {}
    for item in graph["constraints"]:
        if item["scope"] == "candidate":
            candidate_checks[item["target_id"]].append(bool(item["passed"]))
        elif item["constraint"] == "value_consistency":
            group_consistency[item["target_id"]] = bool(item["passed"])

    rows = []
    for node in nodes.values():
        if node["kind"] != "candidate":
            continue
        relations = {edge["relation"]: edge["to"] for edge in outgoing[node["id"]]}
        company = nodes[relations["observed_for"]]["natural_key"]
        indicator = nodes[relations["measures"]]["natural_key"]
        report_year = int(nodes[relations["for_period"]]["natural_key"])
        page = nodes[relations["sourced_from"]]
        document = nodes[next(
            edge["to"] for edge in outgoing[page["id"]] if edge["relation"] == "part_of"
        )]
        group_id = relations["member_of"]
        candidate_passed = all(candidate_checks[node["id"]])
        consistent = group_consistency[group_id]
        rows.append(EvidenceValidationRow(
            candidate_id=node["id"], company_code=company, report_year=report_year,
            indicator_code=indicator,
            value="" if node.get("value") is None else format(float(node["value"]), ".12g"),
            source_file=document["natural_key"],
            source_page="" if page.get("page") is None else str(page["page"]),
            evidence_text=node.get("evidence_text", ""), confidence=float(node.get("confidence", 0)),
            candidate_constraints_passed=candidate_passed, group_consistent=consistent,
            constraint_prediction=candidate_passed and consistent,
            ground_truth_valid="", reviewer="", reviewed_at="", review_note="",
        ))
    failed = [item for item in rows if not item.constraint_prediction]
    passed_by_indicator: dict[str, list[EvidenceValidationRow]] = defaultdict(list)
    for item in rows:
        if item.constraint_prediction:
            passed_by_indicator[item.indicator_code].append(item)
    selected = list(failed)
    for indicator in sorted(passed_by_indicator):
        candidates = sorted(passed_by_indicator[indicator], key=lambda item: item.candidate_id)
        selected.extend(candidates[:per_indicator_passed])
    unique = {item.candidate_id: item for item in selected}
    selected = [unique[key] for key in sorted(unique)]
    summary = {
        "experiment_version": "e1-evidence-constraint-validation-v1",
        "graph_version": graph.get("graph_version", ""),
        "population_candidate_count": len(rows),
        "sample_count": len(selected),
        "constraint_failed_sample_count": sum(not item.constraint_prediction for item in selected),
        "constraint_passed_sample_count": sum(item.constraint_prediction for item in selected),
        "indicator_count": len({item.indicator_code for item in selected}),
        "signed_count": 0,
        "applicable": False,
    }
    return selected, summary


def write_e1_validation_sample(
    output_path: str | Path, summary_path: str | Path,
    rows: list[EvidenceValidationRow], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(EvidenceValidationRow.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(vars(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate_e1_validation(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("E1标注文件为空")
    labels = []
    for number, row in enumerate(rows, 2):
        truth = row.get("ground_truth_valid", "").strip().lower()
        if truth not in {"true", "false"}:
            raise ValueError(f"E1标注第{number}行缺少true/false真值")
        reviewer = row.get("reviewer", "").strip()
        reviewed_at = row.get("reviewed_at", "").strip()
        note = row.get("review_note", "").strip()
        if not reviewer or not reviewed_at or not note:
            raise ValueError(f"E1标注第{number}行审核字段不完整")
        try:
            timestamp = datetime.fromisoformat(reviewed_at)
        except ValueError as exc:
            raise ValueError(f"E1标注第{number}行时间格式无效") from exc
        if timestamp.tzinfo is None:
            raise ValueError(f"E1标注第{number}行时间必须带时区")
        labels.append((truth == "true", row.get("constraint_prediction", "").strip().lower() == "true"))
    baseline = _metrics([(truth, True) for truth, _ in labels])
    constrained = _metrics(labels)
    return {
        "experiment_version": "e1-evidence-constraint-validation-v1",
        "labeled_count": len(labels),
        "direct_extraction_baseline": baseline,
        "constraint_graph_filter": constrained,
        "precision_improvement": round(constrained["precision"] - baseline["precision"], 6),
        "recall_change": round(constrained["recall"] - baseline["recall"], 6),
        "applicable": True,
    }


def write_e1_evaluation(path: str | Path, report: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _metrics(labels: list[tuple[bool, bool]]) -> dict:
    tp = sum(truth and predicted for truth, predicted in labels)
    fp = sum(not truth and predicted for truth, predicted in labels)
    fn = sum(truth and not predicted for truth, predicted in labels)
    tn = sum(not truth and not predicted for truth, predicted in labels)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6),
    }


def _read_graph(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        graph = json.load(stream)
    if not isinstance(graph, dict) or not {"nodes", "edges", "constraints"}.issubset(graph):
        raise ValueError("无效的证据约束图")
    return graph
