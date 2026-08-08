#!/usr/bin/env python3
"""运行公式派生增强数据覆盖率

从已确认的观测数据中通过公式派生缺失指标值，生成增强的观测数据集。
派生值标注为DERIVED状态，用于研究排名，不自动进入正式排名。

使用方法：
    python3 scripts/run_formula_derivation.py \\
        data/observations/confirmed_observations_2025.csv \\
        --output output/research/2025/enhanced_observations_v1.csv \\
        --audit output/audit/derivation_audit_v1.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from aegis_esg.formula_derivation import FormulaDerivationEngine, ALL_DERIVATION_RULES
from aegis_esg.models import Observation, ValueStatus

ROOT = Path(__file__).resolve().parents[1]


def load_observations(csv_path: Path) -> list[Observation]:
    """从CSV加载观测数据"""
    observations = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 解析status
            status_str = row.get("status", "confirmed").strip()
            try:
                status = ValueStatus(status_str)
            except ValueError:
                status = ValueStatus.CONFIRMED

            # 解析value
            value_str = row.get("value", "").strip()
            value = float(value_str) if value_str and value_str != "" else None

            # 解析confidence
            conf_str = row.get("confidence", "1.0").strip()
            confidence = float(conf_str) if conf_str else 1.0

            obs = Observation(
                company_code=row["company_code"].strip(),
                company_name=row.get("company_name", "").strip(),
                report_year=int(row["report_year"]),
                indicator_code=row["indicator_code"].strip(),
                value=value,
                status=status,
                source_url=row.get("source_url", "").strip(),
                source_file=row.get("source_file", "").strip(),
                source_page=int(row["source_page"]) if row.get("source_page") and row["source_page"].strip() else None,
                evidence_text=row.get("evidence_text", "").strip(),
                confidence=confidence,
                source_type=row.get("source_type", "").strip(),
                note=row.get("note", "").strip(),
            )
            observations.append(obs)

    return observations


def save_observations(observations: list[Observation], csv_path: Path) -> None:
    """保存观测数据到CSV"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "company_code", "company_name", "report_year", "indicator_code",
            "value", "status", "source_type", "confidence", "note",
            "source_url", "source_file", "source_page", "evidence_text"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()

        for obs in observations:
            writer.writerow({
                "company_code": obs.company_code,
                "company_name": obs.company_name,
                "report_year": obs.report_year,
                "indicator_code": obs.indicator_code,
                "value": obs.value if obs.value is not None else "",
                "status": obs.status.value,
                "source_type": obs.source_type,
                "confidence": f"{obs.confidence:.3f}",
                "note": obs.note,
                "source_url": obs.source_url,
                "source_file": obs.source_file,
                "source_page": obs.source_page if obs.source_page is not None else "",
                "evidence_text": obs.evidence_text,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description="公式派生增强数据覆盖率")
    parser.add_argument("input", type=Path, help="输入观测CSV文件")
    parser.add_argument("--output", type=Path, required=True, help="输出增强观测CSV文件")
    parser.add_argument("--audit", type=Path, help="输出审计JSON文件")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="最低源数据置信度")

    args = parser.parse_args()

    # 加载观测数据
    print(f"加载观测数据: {args.input}")
    observations = load_observations(args.input)
    print(f"  已加载 {len(observations)} 条观测")

    # 统计原始覆盖
    original_by_indicator = Counter(obs.indicator_code for obs in observations if obs.status == ValueStatus.CONFIRMED)
    companies = {(obs.company_code, obs.report_year) for obs in observations}
    print(f"  公司数: {len(companies)}")
    print(f"  已确认观测: {sum(1 for obs in observations if obs.status == ValueStatus.CONFIRMED)}")

    # 运行派生引擎
    print("\n运行公式派生引擎...")
    engine = FormulaDerivationEngine(ALL_DERIVATION_RULES)
    derived_observations, all_results = engine.derive_batch(observations)

    # 统计派生结果
    success_count = sum(1 for r in all_results if r.success)
    failure_count = len(all_results) - success_count

    print(f"\n派生结果:")
    print(f"  总尝试次数: {len(all_results)}")
    print(f"  成功派生: {success_count}")
    print(f"  失败: {failure_count}")

    # 按规则统计
    results_by_rule = {}
    for result in all_results:
        rule_name = result.rule.target_indicator
        if rule_name not in results_by_rule:
            results_by_rule[rule_name] = {"success": 0, "failure": 0, "rule": result.rule}
        if result.success:
            results_by_rule[rule_name]["success"] += 1
        else:
            results_by_rule[rule_name]["failure"] += 1

    print("\n按指标统计派生结果:")
    for rule_name, stats in sorted(results_by_rule.items(), key=lambda x: -x[1]["success"]):
        rule = stats["rule"]
        original_count = original_by_indicator.get(rule_name, 0)
        derived_count = stats["success"]
        total_count = original_count + derived_count
        coverage_improvement = (derived_count / len(companies) * 100) if companies else 0

        print(f"  {rule_name} ({rule.target_name}):")
        print(f"    原始披露: {original_count}, 派生新增: {derived_count}, 合计: {total_count}")
        print(f"    覆盖提升: +{coverage_improvement:.1f}%")

    # 失败原因统计
    failure_reasons = Counter(r.failure_reason for r in all_results if not r.success and r.failure_reason)
    if failure_reasons:
        print("\n失败原因统计:")
        for reason, count in failure_reasons.most_common(10):
            print(f"  {reason}: {count}")

    # 合并原始和派生观测
    all_observations = observations + derived_observations
    print(f"\n总观测数: {len(all_observations)} (原始 {len(observations)} + 派生 {len(derived_observations)})")

    # 保存增强观测数据
    print(f"\n保存增强观测数据: {args.output}")
    save_observations(all_observations, args.output)

    # 保存审计报告
    if args.audit:
        print(f"保存审计报告: {args.audit}")

        audit_data = {
            "policy_version": "formula-derivation-v1",
            "input_file": str(args.input),
            "output_file": str(args.output),
            "original_observations": len(observations),
            "derived_observations": len(derived_observations),
            "total_observations": len(all_observations),
            "companies": len(companies),
            "derivation_attempts": len(all_results),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_count / len(all_results) if all_results else 0,
            "rules_applied": len(ALL_DERIVATION_RULES),
            "coverage_by_indicator": {
                rule_name: {
                    "target_indicator": rule_name,
                    "target_name": stats["rule"].target_name,
                    "original_count": original_by_indicator.get(rule_name, 0),
                    "derived_count": stats["success"],
                    "total_count": original_by_indicator.get(rule_name, 0) + stats["success"],
                    "original_coverage_pct": original_by_indicator.get(rule_name, 0) / len(companies) * 100 if companies else 0,
                    "derived_coverage_pct": stats["success"] / len(companies) * 100 if companies else 0,
                    "total_coverage_pct": (original_by_indicator.get(rule_name, 0) + stats["success"]) / len(companies) * 100 if companies else 0,
                    "formula": stats["rule"].formula_description,
                    "source_indicators": stats["rule"].source_indicators,
                }
                for rule_name, stats in results_by_rule.items()
            },
            "failure_reasons": dict(failure_reasons.most_common()),
            "notice": "派生值仅用于研究排名，不自动进入正式排名",
        }

        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(audit_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n✓ 派生完成")


if __name__ == "__main__":
    main()
