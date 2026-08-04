from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .external_readiness import audit_external_readiness
from .stage_orchestrator import assess_next_stage


def run_auto_stage(
    completion_report: str | Path,
    quantitative_manifest: str | Path,
    thin_methodology_manifest: str | Path,
    release_manifest: str | Path,
    patent_template: str | Path,
    e1_summary: str | Path | None = None,
    e2_summary: str | Path | None = None,
) -> dict[str, Any]:
    stage = assess_next_stage(completion_report)
    readiness = audit_external_readiness(
        completion_report, quantitative_manifest, thin_methodology_manifest,
        release_manifest, patent_template, e1_summary, e2_summary,
    )
    return {
        "auto_stage_version": "auto-stage-v1",
        "next_stage": stage["next_stage"],
        "stage_assessment": stage,
        "external_readiness": readiness,
        "continue_automatically": stage["status"] == "complete" and readiness["ready"],
    }


def write_auto_stage(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
