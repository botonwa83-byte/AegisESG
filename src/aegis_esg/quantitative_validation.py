from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


_REVIEW_FIELDS = ("ground_truth_valid", "ground_truth_value", "reviewer", "reviewed_at", "review_note")


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _method(evidence: str) -> str:
    text = evidence.strip()
    if "跨表派生" in text or "cross-document derived" in text.lower():
        return "cross_document_derived"
    if "派生" in text or "derived" in text.lower():
        return "formula_derived"
    if "table row" in text.lower() or "表" in text[:80]:
        return "structured_table"
    return "direct_disclosure"


def prepare_quantitative_validation_sample(
    confirmed_path: str | Path, per_stratum: int = 3,
) -> tuple[list[dict], dict]:
    if per_stratum <= 0:
        raise ValueError("每层样本数必须大于0")
    with Path(confirmed_path).open(encoding="utf-8-sig", newline="") as stream:
        population = list(csv.DictReader(stream))
    if not population:
        raise ValueError("自动确认观测为空")
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in population:
        evidence = row.get("evidence_text", "")
        stratum = (row["indicator_code"], _method(evidence))
        identity = "\x1f".join(row.get(key, "") for key in (
            "company_code", "report_year", "indicator_code", "value", "source_file", "source_page", "evidence_text",
        ))
        item = dict(row)
        item["candidate_id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        item["validation_stratum"] = "|".join(stratum)
        strata[stratum].append(item)
    selected = []
    for stratum in sorted(strata):
        rows = sorted(strata[stratum], key=lambda item: item["candidate_id"])
        selected.extend(rows[:per_stratum])
    output_rows = []
    fields = (
        "candidate_id", "validation_stratum", "company_code", "company_name", "report_year",
        "indicator_code", "value", "source_file", "source_page", "evidence_text", "confidence",
    )
    for row in sorted(selected, key=lambda item: item["candidate_id"]):
        output = {field: row.get(field, "") for field in fields}
        output.update({field: "" for field in _REVIEW_FIELDS})
        output_rows.append(output)
    return output_rows, {
        "validation_version": "quantitative-auto-decision-validation-v1",
        "confirmed_input_sha256": _sha256(confirmed_path),
        "population_count": len(population),
        "sample_count": len(output_rows),
        "indicator_count": len({row["indicator_code"] for row in output_rows}),
        "indicator_codes": sorted({row["indicator_code"] for row in output_rows}),
        "stratum_count": len(strata),
        "per_stratum": per_stratum,
        "signed_count": 0,
        "sample_candidate_ids": sorted(row["candidate_id"] for row in output_rows),
        "applicable": False,
    }


def write_quantitative_validation_sample(output_path: str | Path, summary_path: str | Path, rows: list[dict], summary: dict) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate_quantitative_validation(
    path: str | Path, minimum_accuracy: float = .98, relative_tolerance: float = .001,
    manifest_path: str | Path | None = None,
) -> dict:
    if not 0 < minimum_accuracy <= 1 or not 0 <= relative_tolerance <= 1:
        raise ValueError("准确率阈值或数值容差无效")
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("定量抽样标注文件为空")
    manifest = None
    if manifest_path is not None:
        with Path(manifest_path).open(encoding="utf-8") as stream:
            manifest = json.load(stream)
        expected_ids = manifest.get("sample_candidate_ids", [])
        actual_ids = [row.get("candidate_id", "") for row in rows]
        if len(actual_ids) != len(set(actual_ids)) or sorted(actual_ids) != sorted(expected_ids):
            raise ValueError("定量抽样行与冻结抽样清单不一致")
    correct = 0
    indicator_counts: dict[str, int] = defaultdict(int)
    errors = []
    reviewers = set()
    for number, row in enumerate(rows, 2):
        truth = row.get("ground_truth_valid", "").strip().lower()
        if truth not in {"true", "false"}:
            raise ValueError(f"定量抽样第{number}行缺少true/false真值")
        reviewer, reviewed_at, note = (row.get(key, "").strip() for key in ("reviewer", "reviewed_at", "review_note"))
        if not reviewer or not reviewed_at or not note:
            raise ValueError(f"定量抽样第{number}行审核字段不完整")
        try:
            timestamp = datetime.fromisoformat(reviewed_at)
        except ValueError as exc:
            raise ValueError(f"定量抽样第{number}行时间格式无效") from exc
        if timestamp.tzinfo is None:
            raise ValueError(f"定量抽样第{number}行时间必须带时区")
        reviewers.add(reviewer)
        indicator_counts[row["indicator_code"]] += 1
        row_correct = truth == "true"
        if row_correct:
            try:
                predicted = float(row["value"])
                actual = float(row.get("ground_truth_value", ""))
            except ValueError as exc:
                raise ValueError(f"定量抽样第{number}行有效真值必须填写数值") from exc
            row_correct = abs(predicted - actual) <= max(abs(predicted), abs(actual), 1.0) * relative_tolerance
        if row_correct:
            correct += 1
        else:
            errors.append(row["candidate_id"])
    accuracy = correct / len(rows)
    return {
        "validation_version": "quantitative-auto-decision-validation-v1",
        "validation_input_sha256": _sha256(path),
        "labeled_count": len(rows),
        "indicator_count": len(indicator_counts),
        "indicator_codes": sorted(indicator_counts),
        "reviewer_count": len(reviewers),
        "correct_count": correct,
        "error_count": len(errors),
        "accuracy": round(accuracy, 6),
        "minimum_accuracy": minimum_accuracy,
        "relative_tolerance": relative_tolerance,
        "sampling_accuracy_passed": accuracy >= minimum_accuracy,
        "sample_complete": manifest is not None,
        "confirmed_input_sha256": "" if manifest is None else manifest.get("confirmed_input_sha256", ""),
        "error_candidate_ids": errors,
        "applicable": True,
    }


def apply_quantitative_validation(
    summary_path: str | Path, evaluation_path: str | Path, confirmed_path: str | Path,
) -> dict:
    with Path(summary_path).open(encoding="utf-8") as stream:
        summary = json.load(stream)
    with Path(evaluation_path).open(encoding="utf-8") as stream:
        evaluation = json.load(stream)
    if evaluation.get("validation_version") != "quantitative-auto-decision-validation-v1" or evaluation.get("applicable") is not True:
        raise ValueError("定量抽样评估不可应用")
    if evaluation.get("sample_complete") is not True:
        raise ValueError("定量抽样未绑定冻结抽样清单")
    if evaluation.get("confirmed_input_sha256") != _sha256(confirmed_path):
        raise ValueError("定量抽样评估与自动确认输入Hash不一致")
    if int(evaluation.get("indicator_count", 0)) <= 0:
        raise ValueError("定量抽样未覆盖自动决定指标")
    result = dict(summary)
    result["sampling_validation"] = evaluation
    result["sampling_validation_confirmed_path"] = str(confirmed_path)
    result["sampling_accuracy_passed"] = evaluation.get("sampling_accuracy_passed") is True
    return result


def write_json(path: str | Path, value: dict) -> None:
    output = Path(path); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
