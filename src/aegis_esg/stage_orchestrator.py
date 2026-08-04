"""无人工指令的阶段推进判定。

该模块只根据机器门禁和已登记材料决定下一阶段，不代替任何真实审核或签名。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("阶段推进输入必须是JSON对象")
    return value


def assess_next_stage(completion_report: str | Path) -> dict[str, Any]:
    """返回可自动推进的下一阶段或不可替代外部输入清单。

    该函数不修改数据、不填写签名，也不把研究结果提升为正式结果。
    """
    report = _load(completion_report)
    gates = report.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("完成度报告缺少gates对象")
    ordered = (
        ("M3", "universe", "完整632主体表、行业证据和A/H审核"),
        ("M4", "documents", "目标年度文档状态及缺失终态审核"),
        ("M5", "quantitative", "定量抽样真值、薄样本裁决和冲突审核"),
        ("M6", "qualitative", "定性真实基准集、双审和仲裁"),
        ("M6", "review", "真实审核签名闭合"),
        ("M7", "release", "正式输入冻结和双人发布授权"),
    )
    for stage, gate_name, external_need in ordered:
        gate = gates.get(gate_name)
        if not isinstance(gate, dict):
            raise ValueError(f"完成度报告缺少{gate_name}门禁")
        if not bool(gate.get("complete")):
            return {
                "orchestrator_version": "stage-orchestrator-v1",
                "status": "blocked_external",
                "next_stage": stage,
                "gate": gate_name,
                "external_input_required": external_need,
                "blocker": gate.get("blocker", "未通过门禁"),
                "automatic_actions": [
                    "等待登记的真实外部输入",
                    "输入到达后重新运行本命令并执行该阶段校验",
                ],
                "publishable": False,
            }
    return {
        "orchestrator_version": "stage-orchestrator-v1",
        "status": "complete",
        "next_stage": "complete",
        "gate": None,
        "external_input_required": None,
        "automatic_actions": ["运行正式发布回归并保存发布审计包"],
        "publishable": bool(report.get("publishable")),
    }


def write_stage_assessment(path: str | Path, assessment: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(assessment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
