"""DL/T 2971—2025 工程对齐状态看板。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .benchmarks import GOVERNANCE_BENCHMARK_TARGET_VERSION, audit_governance_benchmarks
from .grade import GRADE_RULE_VERSION
from .methodology import load_methodology
from .models import IndicatorKind
from .release_guard import DLT_STANDARD_REF, RESULT_VALIDITY_DAYS


def build_dlt_alignment_status(methodology_path: str | Path) -> dict[str, Any]:
    methodology = load_methodology(methodology_path)
    by_kind_dim: dict[tuple[str, str], float] = {}
    for item in methodology.indicators:
        key = (item.kind.value, item.dimension)
        by_kind_dim[key] = by_kind_dim.get(key, 0.0) + item.weight
    quantitative = methodology.quantitative
    qualitative = methodology.qualitative
    weight_ok = True
    for kind in (IndicatorKind.QUANTITATIVE, IndicatorKind.QUALITATIVE):
        total = sum(item.weight for item in methodology.indicators if item.kind == kind)
        if abs(total - 100.0) > 0.01:
            weight_ok = False
        for dimension, expected in (("E", 45.0), ("S", 20.0), ("G", 35.0)):
            if abs(by_kind_dim.get((kind.value, dimension), 0.0) - expected) > 0.01:
                weight_ok = False
    ratio_ok = (
        abs(methodology.quantitative_ratio - 0.8) < 1e-9
        and abs(methodology.qualitative_ratio - 0.2) < 1e-9
    )
    benchmarks = audit_governance_benchmarks(methodology)
    frozen = methodology.version == GOVERNANCE_BENCHMARK_TARGET_VERSION
    checks = {
        "indicator_coverage": {
            "ready": len(quantitative) == 37 and len(qualitative) == 43,
            "evidence": f"quantitative={len(quantitative)}; qualitative={len(qualitative)}",
            "required_external_action": "保持附录A/B的37+43项编码与权重",
        },
        "weight_structure": {
            "ready": weight_ok and ratio_ok,
            "evidence": (
                f"q/x={methodology.quantitative_ratio}/{methodology.qualitative_ratio}; "
                f"E/S/G quantitative="
                f"{by_kind_dim.get(('quantitative', 'E'), 0):.2f}/"
                f"{by_kind_dim.get(('quantitative', 'S'), 0):.2f}/"
                f"{by_kind_dim.get(('quantitative', 'G'), 0):.2f}"
            ),
            "required_external_action": "勿用AHP/熵权覆盖行标固定权重",
        },
        "grade_mapping": {
            "ready": True,
            "evidence": f"rule={GRADE_RULE_VERSION}",
            "required_external_action": "事故类NA仍需人工填写GradeFlags",
        },
        "release_validity_gate": {
            "ready": True,
            "evidence": f"result_validity_days={RESULT_VALIDITY_DAYS}; standard_ref={DLT_STANDARD_REF}",
            "required_external_action": "正式发布启用--require-dlt-process并完成evaluation_lead签名",
        },
        "governance_benchmarks": {
            "ready": benchmarks["formal_ready"],
            "evidence": (
                f"filled={benchmarks['filled_count']}/{benchmarks['governance_indicator_count']}; "
                f"blocker={benchmarks['blocker']}"
            ),
            "required_external_action": (
                "填入《企业绩效评价标准值》工业领域优秀值并执行apply-governance-benchmarks"
            ),
        },
        "formal_methodology_frozen": {
            "ready": frozen and benchmarks["formal_ready"],
            "evidence": f"methodology_version={methodology.version}; target={GOVERNANCE_BENCHMARK_TARGET_VERSION}",
            "required_external_action": "优秀值齐全后冻结为DLT2971-2025-v1",
        },
    }
    ready_count = sum(1 for item in checks.values() if item["ready"])
    return {
        "alignment_version": "dlt2971-alignment-status-v1",
        "standard_ref": DLT_STANDARD_REF,
        "methodology_path": str(methodology_path),
        "methodology_version": methodology.version,
        "ready_count": ready_count,
        "check_count": len(checks),
        "aligned": ready_count == len(checks),
        "status": "aligned" if ready_count == len(checks) else "blocked_external",
        "checks": checks,
        "governance_benchmark_audit": benchmarks,
        "notice": (
            "工程侧行标结构、级别映射与发布门禁已就绪；"
            "未注入经核验的国资委工业优秀值前不得宣称正式DL/T治理打分。"
        ),
    }
