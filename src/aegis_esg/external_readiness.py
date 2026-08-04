from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"外部输入审计文件必须是JSON对象: {path}")
    return value


def audit_external_readiness(
    completion_report: str | Path,
    quantitative_manifest: str | Path,
    thin_methodology_manifest: str | Path,
    release_manifest: str | Path,
    patent_template: str | Path,
    e1_summary: str | Path | None = None,
    e2_summary: str | Path | None = None,
) -> dict[str, Any]:
    completion = _read_json(completion_report)
    quantitative = _read_json(quantitative_manifest)
    thin = _read_json(thin_methodology_manifest)
    release = _read_json(release_manifest)
    patent_path = Path(patent_template)
    checks = {
        "completion_gates": {
            "ready": completion.get("publishable") is True,
            "evidence": f"{completion.get('completed_gate_count', 0)}/{completion.get('gate_count', 6)} gates",
            "required_external_action": "完成六道门禁",
        },
        "quantitative_sampling": {
            "ready": quantitative.get("applicable") is True and int(quantitative.get("signed_count", 0)) > 0,
            "evidence": f"{quantitative.get('signed_count', 0)}/{quantitative.get('sample_count', 0)} signed",
            "required_external_action": "完成真实定量抽样签名",
        },
        "thin_methodology": {
            "ready": thin.get("applicable") is True and int(thin.get("signed_count", 0)) == int(thin.get("review_count", -1)),
            "evidence": f"{thin.get('signed_count', 0)}/{thin.get('review_count', 0)} signed",
            "required_external_action": "完成薄样本方法论裁决",
        },
        "release_authorization": {
            "ready": release.get("authorized") is True,
            "evidence": f"authorized={bool(release.get('authorized'))}",
            "required_external_action": "完成正式发布双签",
        },
        "patent_ownership": {
            "ready": False,
            "evidence": "template_present=" + str(patent_path.is_file()),
            "required_external_action": "填写申请主体、发明人和贡献权属并经代理师确认",
        },
    }
    if e1_summary is not None:
        e1 = _read_json(e1_summary)
        checks["e1_constraint_experiment"] = {
            "ready": e1.get("applicable") is True and int(e1.get("signed_count", 0)) > 0,
            "evidence": f"{e1.get('signed_count', 0)}/{e1.get('sample_count', 0)} signed",
            "required_external_action": "完成E1证据约束图真实标注",
        }
    if e2_summary is not None:
        e2 = _read_json(e2_summary)
        checks["e2_review_scheduling_experiment"] = {
            "ready": e2.get("applicable") is True,
            "evidence": f"applicable={bool(e2.get('applicable'))}; tasks={e2.get('task_count', 0)}",
            "required_external_action": "完成E2审核调度真实结果标注",
        }
    ready = all(item["ready"] for item in checks.values())
    return {
        "readiness_version": "external-input-readiness-v1",
        "status": "ready" if ready else "blocked_external",
        "ready": ready,
        "checks": checks,
        "notice": "该审计只识别真实输入状态，不代替审核或填写签名",
    }


def write_external_readiness(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
