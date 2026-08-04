from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


FIELDS = (
    "task_id", "priority", "company_code", "indicator_code", "impact_score",
    "crosses_top_200", "baseline_confidence_rank", "baseline_weight_rank",
    "reviewer", "reviewed_at", "review_outcome", "rank_after", "review_note",
)


def prepare_e2_validation_sample(impact_csv: str | Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    source = Path(impact_csv)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("E2审核调度输入为空")
    result = []
    for row in rows:
        task_id = hashlib.sha256(
            f"{row.get('company_code','')}|{row.get('report_year','')}|{row.get('indicator_code','')}|{row.get('priority','')}".encode()
        ).hexdigest()
        result.append({
            "task_id": task_id,
            "priority": row.get("priority", ""),
            "company_code": row.get("company_code", ""),
            "indicator_code": row.get("indicator_code", ""),
            "impact_score": row.get("impact_score", ""),
            "crosses_top_200": row.get("crosses_top_200", ""),
            "baseline_confidence_rank": row.get("baseline_confidence_rank", ""),
            "baseline_weight_rank": row.get("baseline_weight_rank", ""),
            "reviewer": "", "reviewed_at": "", "review_outcome": "",
            "rank_after": "", "review_note": "",
        })
    summary = {
        "experiment_version": "e2-review-scheduling-validation-v1",
        "input_path": str(source),
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "task_count": len(result),
        "crossing_task_count": sum(item["crosses_top_200"].lower() == "true" for item in result),
        "signed_count": 0,
        "applicable": False,
    }
    return result, summary


def write_e2_validation_sample(path: str | Path, summary_path: str | Path, rows: list[dict[str, str]], summary: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate_e2_validation(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("E2标注文件为空")
    for number, row in enumerate(rows, 2):
        if not row.get("reviewer", "").strip() or not row.get("review_note", "").strip():
            raise ValueError(f"E2标注第{number}行审核字段不完整")
        try:
            timestamp = datetime.fromisoformat(row.get("reviewed_at", ""))
            rank_after = int(row.get("rank_after", ""))
        except (ValueError, TypeError) as error:
            raise ValueError(f"E2标注第{number}行时间或名次无效") from error
        if timestamp.tzinfo is None or rank_after <= 0:
            raise ValueError(f"E2标注第{number}行时间必须带时区且名次必须为正数")
        if row.get("review_outcome", "").strip() not in {"confirm", "reject"}:
            raise ValueError(f"E2标注第{number}行结果必须为confirm或reject")
    return {
        "experiment_version": "e2-review-scheduling-validation-v1",
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "task_count": len(rows),
        "signed_count": len(rows),
        "applicable": True,
        "notice": "该结果评估审核调度样本完整性；效率和稳定性结论仍需按预先冻结的计时与边界口径计算",
    }
