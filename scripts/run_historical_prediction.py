#!/usr/bin/env python3
"""运行时间序列预测增强数据覆盖率

从历史观测数据（2022-2024）预测2025年缺失指标值。
预测值标注为PREDICTED状态，仅用于研究排名。

使用方法：
    python3 scripts/run_historical_prediction.py \\
        data/review/all_markets_indicator_confirmed_v22_2025.csv \\
        --historical-years 2022 2023 2024 \\
        --target-year 2025 \\
        --output output/research/2025/enhanced_observations_v2_with_prediction.csv \\
        --audit output/audit/time_series_prediction_v1_2025.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from aegis_esg.time_series_predictor import TimeSeriesPredictor, PredictionMethod
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
    parser = argparse.ArgumentParser(description="时间序列预测增强数据覆盖率")
    parser.add_argument("input", type=Path, help="输入观测CSV文件（包含历史和当年数据）")
    parser.add_argument("--historical-years", type=int, nargs="+", default=[2022, 2023, 2024], help="历史年份")
    parser.add_argument("--target-year", type=int, default=2025, help="目标预测年份")
    parser.add_argument("--output", type=Path, required=True, help="输出增强观测CSV文件")
    parser.add_argument("--audit", type=Path, help="输出审计JSON文件")
    parser.add_argument("--min-points", type=int, default=2, help="最少历史数据点")
    parser.add_argument("--max-cv", type=float, default=0.5, help="最大变异系数")
    parser.add_argument("--min-confidence", type=float, default=0.4, help="最低预测置信度")

    args = parser.parse_args()

    # 加载观测数据
    print(f"加载观测数据: {args.input}")
    all_observations = load_observations(args.input)
    print(f"  已加载 {len(all_observations)} 条观测")

    # 分离历史和当年数据
    historical_obs = [obs for obs in all_observations if obs.report_year in args.historical_years]
    target_year_obs = [obs for obs in all_observations if obs.report_year == args.target_year]

    print(f"  历史年份观测: {len(historical_obs)} ({args.historical_years})")
    print(f"  目标年份观测: {len(target_year_obs)} ({args.target_year})")

    # 统计当年已有覆盖
    target_companies = {obs.company_code for obs in target_year_obs}
    target_by_indicator = Counter(
        obs.indicator_code
        for obs in target_year_obs
        if obs.status == ValueStatus.CONFIRMED and obs.value is not None
    )
    target_coverage = {
        (obs.company_code, obs.indicator_code)
        for obs in target_year_obs
        if obs.status == ValueStatus.CONFIRMED and obs.value is not None
    }

    print(f"  目标年份公司数: {len(target_companies)}")
    print(f"  目标年份已确认观测: {len(target_coverage)}")

    # 创建预测器
    print(f"\n创建时间序列预测器（min_points={args.min_points}, max_cv={args.max_cv}）...")
    predictor = TimeSeriesPredictor(
        min_historical_points=args.min_points,
        max_cv=args.max_cv,
        enable_auto_method_selection=True,
    )

    # 运行预测
    print(f"\n运行预测...")
    predicted_observations, all_results = predictor.predict_batch(
        historical_observations=historical_obs,
        target_year=args.target_year,
        target_companies=target_companies,  # 只预测目标年份存在的公司
    )

    # 过滤已有覆盖（不重复预测已披露的指标）
    filtered_predictions = []
    for obs in predicted_observations:
        if (obs.company_code, obs.indicator_code) not in target_coverage:
            if obs.confidence >= args.min_confidence:
                filtered_predictions.append(obs)

    # 统计预测结果
    success_count = sum(1 for r in all_results if r.success)
    failure_count = len(all_results) - success_count
    filtered_count = len(filtered_predictions)

    print(f"\n预测结果:")
    print(f"  总尝试次数: {len(all_results)}")
    print(f"  成功预测: {success_count}")
    print(f"  失败: {failure_count}")
    print(f"  过滤后新增: {filtered_count} (排除已有覆盖 + 低置信度)")

    # 按指标统计
    results_by_indicator = {}
    for result in all_results:
        indicator = result.historical_series.indicator_code
        if indicator not in results_by_indicator:
            results_by_indicator[indicator] = {
                "success": 0, "failure": 0, "methods": Counter()
            }
        if result.success:
            results_by_indicator[indicator]["success"] += 1
            if result.method:
                results_by_indicator[indicator]["methods"][result.method.value] += 1
        else:
            results_by_indicator[indicator]["failure"] += 1

    # 计算新增覆盖
    predicted_by_indicator = Counter(obs.indicator_code for obs in filtered_predictions)

    print("\n按指标统计预测结果（前20）:")
    sorted_indicators = sorted(
        results_by_indicator.items(),
        key=lambda x: -x[1]["success"]
    )[:20]

    for indicator, stats in sorted_indicators:
        original = target_by_indicator.get(indicator, 0)
        predicted = predicted_by_indicator.get(indicator, 0)
        total = original + predicted
        coverage_improvement = (predicted / len(target_companies) * 100) if target_companies else 0

        methods_str = ", ".join(f"{m}:{c}" for m, c in stats["methods"].most_common(3))

        print(f"  {indicator}:")
        print(f"    原始: {original}, 预测新增: {predicted}, 合计: {total}")
        print(f"    覆盖提升: +{coverage_improvement:.1f}%")
        print(f"    预测方法: {methods_str}")

    # 失败原因统计
    failure_reasons = Counter(r.failure_reason for r in all_results if not r.success and r.failure_reason)
    if failure_reasons:
        print("\n失败原因统计:")
        for reason, count in failure_reasons.most_common(10):
            print(f"  {reason}: {count}")

    # 合并原始和预测观测
    all_enhanced = all_observations + filtered_predictions
    print(f"\n总观测数: {len(all_enhanced)} (原始 {len(all_observations)} + 预测 {len(filtered_predictions)})")

    # 保存增强观测数据
    print(f"\n保存增强观测数据: {args.output}")
    save_observations(all_enhanced, args.output)

    # 保存审计报告
    if args.audit:
        print(f"保存审计报告: {args.audit}")

        audit_data = {
            "policy_version": "time-series-prediction-v1",
            "input_file": str(args.input),
            "output_file": str(args.output),
            "historical_years": args.historical_years,
            "target_year": args.target_year,
            "min_historical_points": args.min_points,
            "max_cv": args.max_cv,
            "min_confidence": args.min_confidence,
            "original_observations": len(all_observations),
            "predicted_observations": len(filtered_predictions),
            "total_observations": len(all_enhanced),
            "target_companies": len(target_companies),
            "prediction_attempts": len(all_results),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_count / len(all_results) if all_results else 0,
            "filtered_by_existing_coverage": success_count - filtered_count,
            "coverage_by_indicator": {
                indicator: {
                    "indicator_code": indicator,
                    "original_count": target_by_indicator.get(indicator, 0),
                    "predicted_count": predicted_by_indicator.get(indicator, 0),
                    "total_count": target_by_indicator.get(indicator, 0) + predicted_by_indicator.get(indicator, 0),
                    "original_coverage_pct": target_by_indicator.get(indicator, 0) / len(target_companies) * 100 if target_companies else 0,
                    "predicted_coverage_pct": predicted_by_indicator.get(indicator, 0) / len(target_companies) * 100 if target_companies else 0,
                    "total_coverage_pct": (target_by_indicator.get(indicator, 0) + predicted_by_indicator.get(indicator, 0)) / len(target_companies) * 100 if target_companies else 0,
                    "prediction_methods": dict(stats["methods"]),
                    "success": stats["success"],
                    "failure": stats["failure"],
                }
                for indicator, stats in results_by_indicator.items()
            },
            "failure_reasons": dict(failure_reasons.most_common()),
            "notice": "预测值仅用于研究排名，不进入正式排名",
        }

        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(audit_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n✓ 预测完成")


if __name__ == "__main__":
    main()
