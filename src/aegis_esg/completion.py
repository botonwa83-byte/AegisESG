from __future__ import annotations

import json
from pathlib import Path


def _read(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"完成度审计输入必须是JSON对象: {path}")
    return value


def audit_project_completion(
    document_summary_path: str | Path,
    quantitative_summary_path: str | Path,
    qualitative_summary_path: str | Path,
    resolution_summary_path: str | Path,
    expected_companies: int = 632,
) -> dict:
    if expected_companies <= 0:
        raise ValueError("目标公司数必须大于0")
    documents = _read(document_summary_path)
    quantitative = _read(quantitative_summary_path)
    qualitative = _read(qualitative_summary_path)
    resolution = _read(resolution_summary_path)

    universe_count = int(quantitative.get("company_count", 0))
    annual_count = int(documents.get("annual_coverage_count", 0))
    quantitative_total = expected_companies * int(quantitative.get("quantitative_indicator_count", 0))
    quantitative_candidate = int(quantitative.get("candidate_task_count", 0))
    qualitative_total = expected_companies * int(qualitative.get("qualitative_indicator_count", 0))
    qualitative_candidates = int(qualitative.get("review_packet_count", 0))
    qualitative_confirmed = int(qualitative.get("auto_confirmed_count", 0))
    quantitative_manual = int(resolution.get("manual_required_group_count", 0))

    gates = {
        "universe": {
            "complete": universe_count == expected_companies,
            "current": universe_count, "target": expected_companies,
            "blocker": "冻结公司主体、行业证据及A/H映射",
        },
        "documents": {
            "complete": annual_count == expected_companies,
            "current": annual_count, "target": expected_companies,
            "blocker": "闭环每家公司的目标年度年报状态",
        },
        "quantitative": {
            "complete": quantitative_total > 0 and quantitative_candidate == quantitative_total,
            "current": quantitative_candidate, "target": quantitative_total,
            "blocker": "补齐候选或将真实空窗签名为缺失/不适用",
        },
        "qualitative": {
            "complete": qualitative_total > 0 and qualitative_confirmed == qualitative_total,
            "current": qualitative_confirmed, "candidate": qualitative_candidates,
            "target": qualitative_total,
            "blocker": "完成定性证据判断、双签与必要仲裁",
        },
        "review": {
            "complete": quantitative_manual == 0 and qualitative_confirmed == qualitative_total,
            "quantitative_manual_groups": quantitative_manual,
            "qualitative_unconfirmed_groups": max(qualitative_total - qualitative_confirmed, 0),
            "blocker": "由真实审核人完成签名，系统不得代签",
        },
        "release": {
            "complete": bool(resolution.get("freeze_ready")) and bool(resolution.get("applicable")),
            "freeze_ready": bool(resolution.get("freeze_ready")),
            "applicable": bool(resolution.get("applicable")),
            "blocker": "冻结正式观测并通过score --release质量门禁",
        },
    }
    completed = sum(item["complete"] for item in gates.values())
    return {
        "expected_company_count": expected_companies,
        "completed_gate_count": completed,
        "gate_count": len(gates),
        "completion_rate": completed / len(gates),
        "publishable": completed == len(gates),
        "gates": gates,
        "next_gate": next((name for name, item in gates.items() if not item["complete"]), "complete"),
    }


def write_completion_report(path: str | Path, report: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
