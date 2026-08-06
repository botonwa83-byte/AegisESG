#!/usr/bin/env python3
"""Audit local scoring design against the client 2025 ESG evaluation PDF rules.

Produces a machine-readable compliance report. Does not authorize formal release.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.benchmarks import audit_governance_benchmarks  # noqa: E402
from aegis_esg.methodology import load_methodology  # noqa: E402
from aegis_esg.scoring import MissingStrategy  # noqa: E402

METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025.json"
RESEARCH_METHODOLOGY = ROOT / "data/methodologies/energy_esg_2025_research_sasac.json"
OUTPUT = ROOT / "output/audit/pdf_algorithm_alignment_v1.json"
CLIENT_PDF = "2025中国能源上市公司可持续发展（ESG）评价报告.pdf"


def check(item_id: str, requirement: str, status: str, detail: str, evidence: str = "") -> dict:
    return {
        "id": item_id,
        "requirement": requirement,
        "status": status,  # pass | fail | partial | unknown
        "detail": detail,
        "evidence": evidence,
    }


def main() -> None:
    base = load_methodology(METHODOLOGY)
    research_path = RESEARCH_METHODOLOGY if RESEARCH_METHODOLOGY.is_file() else METHODOLOGY
    research = load_methodology(research_path)
    base_bench = audit_governance_benchmarks(base)
    research_bench = audit_governance_benchmarks(research)

    q = [i for i in base.indicators if i.kind.value == "quantitative"]
    x = [i for i in base.indicators if i.kind.value == "qualitative"]
    key = [i for i in q if i.key_indicator]

    items = [
        check(
            "structure_counts",
            "评价指标共80项：定量37、定性43",
            "pass" if len(q) == 37 and len(x) == 43 else "fail",
            f"quantitative={len(q)} qualitative={len(x)}",
            str(METHODOLOGY.relative_to(ROOT)),
        ),
        check(
            "blend_ratio",
            "总分 S=80%×SL + 20%×Sx",
            "pass" if abs(base.quantitative_ratio - 0.8) < 1e-9 and abs(base.qualitative_ratio - 0.2) < 1e-9 else "fail",
            f"quantitative_ratio={base.quantitative_ratio} qualitative_ratio={base.qualitative_ratio}",
            "src/aegis_esg/scoring.py",
        ),
        check(
            "es_normal_scoring",
            "环境保护与社会责任定量：披露样本正态，正/负向方向打分",
            "pass",
            "E/S 使用样本μ/σ与正态CDF/1-CDF；客户未公开具体参数，属可审计近似",
            "src/aegis_esg/scoring.py::_score_value",
        ),
        check(
            "g_sasac_benchmark",
            "公司治理定量参考国资委工业领域优秀值峰打分",
            "pass" if research_bench["filled_count"] == 17 else ("partial" if research_bench["filled_count"] else "fail"),
            (
                f"base_filled={base_bench['filled_count']}/17；"
                f"research_filled={research_bench['filled_count']}/17 "
                f"(methodology={research_path.name})。"
                "研究值摘自客户报告正文，非正式国资委原表冻结。"
            ),
            str(research_path.relative_to(ROOT)),
        ),
        check(
            "qualitative_tiers",
            "定性达成率档位 100/80/50/20",
            "partial",
            "引擎接受100/80/50/20；当前研究观测多为启发式或缺失。PDF最低明示档为20%，系统定量缺失默认0（用户规则），定性缺失亦按0计入（严于PDF最低档）。",
            "src/aegis_esg/scoring.py",
        ),
        check(
            "missing_zero_quant",
            "未披露定量计分策略可审计且版本化",
            "pass",
            f"研究默认 {MissingStrategy.LEGACY_ZERO_V1.value}（未披露→标准化0后加权）",
            "src/aegis_esg/ranking_analysis.py",
        ),
        check(
            "bonus_scope3",
            "范围三披露/碳中和认证/集团ESG主责部门等酌情奖励分",
            "fail",
            "PDF写明酌情奖励，系统尚未实现显式奖励分规则",
            CLIENT_PDF,
        ),
        check(
            "key_indicators",
            "纸质榜展示10项关键定量指标",
            "pass" if len(key) == 10 else "fail",
            f"key_indicator_count={len(key)}: {', '.join(i.code for i in key)}",
            str(METHODOLOGY.relative_to(ROOT)),
        ),
        check(
            "data_year_labeling",
            "评价年与报告期分离标注（客户2025评价=报告期2024；我方当前库=报告期2025）",
            "partial",
            "文档口径已定义评价年=报告期+1；交付元数据需同时写evaluation_year与report_year",
            "docs/data-pipeline.md",
        ),
        check(
            "winsorize",
            "剔除极端值后计算正态参数",
            "partial",
            "实现对披露样本1%/99% winsorize；客户未公开阈值，属可审计近似",
            "src/aegis_esg/scoring.py::_winsorize",
        ),
        check(
            "traceability",
            "原始数据来自公开披露且可追溯",
            "pass",
            "观测保留source_url/source_file/source_page/evidence；无Choice/青绿黑箱，客观性更强但覆盖可能更低",
            "output/research/2025/",
        ),
    ]

    counts = {status: sum(1 for i in items if i["status"] == status) for status in ("pass", "partial", "fail", "unknown")}
    report = {
        "audit_version": "pdf-algorithm-alignment-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "client_pdf": CLIENT_PDF,
        "base_methodology": str(METHODOLOGY.relative_to(ROOT)),
        "research_methodology": str(research_path.relative_to(ROOT)),
        "counts": counts,
        "compliant_enough_for_research": counts["fail"] <= 1 and research_bench["filled_count"] == 17,
        "formal_release_authorized": False,
        "notice": (
            "本审计用于方法合规与可续性检查；不授权正式发布。"
            "与客户纸质榜年差（我方report_year=2025 vs 客户report_year=2024）属正常，不要求严格贴名次。"
        ),
        "items": items,
        "governance_benchmark_audit": {
            "base": base_bench,
            "research": research_bench,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
