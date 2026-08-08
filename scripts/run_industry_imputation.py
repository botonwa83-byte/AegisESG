#!/usr/bin/env python3
"""运行行业均值填充增强数据覆盖率

使用行业基准参数填充缺失指标值。适用于行业特征明显的指标。
填充值标注为IMPUTED状态，仅用于研究排名。

使用方法：
    # 步骤1: 构建行业基准
    python3 scripts/build_industry_benchmarks.py \\
        data/review/all_markets_indicator_confirmed_v22_2025.csv \\
        data/universe/energy_company_industry_mapping.csv \\
        --output output/audit/industry_benchmarks_2025.csv \\
        --summary output/audit/industry_benchmarks_summary_2025.json

    # 步骤2: 应用填充
    python3 scripts/run_industry_imputation.py \\
        data/review/all_markets_indicator_confirmed_v22_2025.csv \\
        data/universe/energy_company_industry_mapping.csv \\
        --output output/research/2025/enhanced_observations_v3_industry_filled.csv \\
        --audit output/audit/industry_imputation_v1_2025.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from aegis_esg.industry_imputation import IndustryImputationEngine, IMPUTATION_WHITELIST
from aegis_esg.models import Observation, ValueStatus

ROOT = Path(__file__).resolve().parents[1]


def load_observations(csv_path: Path) -> list[Observation]:
    """从CSV加载观测数据"""
    observations = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            status_str = row.get("status", "confirmed").strip()
            try:
                status = ValueStatus(status_str)
            except ValueError:
                status = ValueStatus.CONFIRMED

            value_str = row.get("value", "").strip()
            value = float(value_str) if value_str and value_str != "" else None

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


def load_industry_mapping(csv_path: Path) -> dict[str, str]:
    """加载公司行业映射

    CSV格式: company_code, company_name, industry_level1, industry_level2
    优先使用industry_level2，如无则用industry_level1
    """
    mapping = {}

    if not csv_path.exists():
        print(f"⚠️  行业映射文件不存在: {csv_path}")
        print("将尝试从观测数据中推断行业分类...")
        return mapping

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 跳过注释行和空行
            if not row or not row.get("company_code"):
                continue

            company_code = row["company_code"].strip()
            industry_level2 = (row.get("industry_level2") or "").strip()
            industry_level1 = (row.get("industry_level1") or "").strip()

            # 优先使用二级分类
            industry = industry_level2 if industry_level2 else industry_level1
            if industry:
                mapping[company_code] = industry

    return mapping


def infer_industry_from_name(company_name: str) -> str:
    """从公司名称推断行业（简单规则）"""
    name = company_name.lower()

    # 煤炭
    if any(keyword in name for keyword in ["煤", "焦", "矿"]):
        return "煤炭"

    # 油气
    if any(keyword in name for keyword in ["油", "石化", "燃气", "天然气"]):
        return "油气"

    # 新能源
    if any(keyword in name for keyword in ["风电", "风能", "太阳能", "光伏", "新能源"]):
        return "新能源"

    # 电力
    if any(keyword in name for keyword in ["电力", "电站", "发电", "水电", "核电"]):
        return "电力"

    # 默认
    return "能源综合"


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
    parser = argparse.ArgumentParser(description="行业均值填充增强数据覆盖率")
    parser.add_argument("input", type=Path, help="输入观测CSV文件")
    parser.add_argument("industry_mapping", type=Path, help="行业映射CSV文件")
    parser.add_argument("--target-year", type=int, default=2025, help="目标年份")
    parser.add_argument("--output", type=Path, required=True, help="输出增强观测CSV文件")
    parser.add_argument("--audit", type=Path, help="输出审计JSON文件")
    parser.add_argument("--min-sample", type=int, default=10, help="最小行业样本量")
    parser.add_argument("--use-median", action="store_true", help="使用中位数而非均值")

    args = parser.parse_args()

    # 加载观测数据
    print(f"加载观测数据: {args.input}")
    observations = load_observations(args.input)
    print(f"  已加载 {len(observations)} 条观测")

    # 加载行业映射
    print(f"\n加载行业映射: {args.industry_mapping}")
    industry_mapping = load_industry_mapping(args.industry_mapping)

    # 如果映射文件不存在或为空，尝试从公司名称推断
    if not industry_mapping:
        print("  使用公司名称推断行业分类...")
        target_year_obs = [obs for obs in observations if obs.report_year == args.target_year]
        unique_companies = {obs.company_code: obs.company_name for obs in target_year_obs}
        industry_mapping = {
            code: infer_industry_from_name(name)
            for code, name in unique_companies.items()
        }
        print(f"  推断了 {len(industry_mapping)} 家公司的行业分类")
    else:
        print(f"  已加载 {len(industry_mapping)} 家公司的行业映射")

    # 统计行业分布
    industry_counts = Counter(industry_mapping.values())
    print("\n行业分布:")
    for industry, count in sorted(industry_counts.items(), key=lambda x: -x[1]):
        print(f"  {industry}: {count}家")

    # 统计当前覆盖
    target_year_obs = [obs for obs in observations if obs.report_year == args.target_year]
    target_companies = {obs.company_code for obs in target_year_obs}
    target_by_indicator = Counter(
        obs.indicator_code
        for obs in target_year_obs
        if obs.status == ValueStatus.CONFIRMED and obs.value is not None
    )
    existing_coverage = {
        (obs.company_code, obs.indicator_code)
        for obs in target_year_obs
        if obs.status == ValueStatus.CONFIRMED and obs.value is not None
    }

    print(f"\n目标年份 {args.target_year}:")
    print(f"  公司数: {len(target_companies)}")
    print(f"  已确认观测: {len(existing_coverage)}")

    # 创建填充引擎
    print(f"\n创建行业填充引擎（min_sample={args.min_sample}, use_median={args.use_median}）...")
    engine = IndustryImputationEngine(
        min_industry_sample=args.min_sample,
        use_median=args.use_median,
        imputation_whitelist=IMPUTATION_WHITELIST,
    )

    # 运行填充
    print(f"\n运行填充...")
    imputed_observations, all_results, benchmarks = engine.impute_batch(
        observations=observations,
        industry_mapping=industry_mapping,
        target_year=args.target_year,
    )

    # 统计填充结果
    success_count = sum(1 for r in all_results if r.success)
    failure_count = len(all_results) - success_count

    print(f"\n填充结果:")
    print(f"  总尝试次数: {len(all_results)}")
    print(f"  成功填充: {success_count}")
    print(f"  失败: {failure_count}")

    # 按指标统计
    imputed_by_indicator = Counter(obs.indicator_code for obs in imputed_observations)

    print("\n按指标统计填充结果:")
    for indicator in sorted(IMPUTATION_WHITELIST):
        original = target_by_indicator.get(indicator, 0)
        imputed = imputed_by_indicator.get(indicator, 0)
        total = original + imputed
        coverage_improvement = (imputed / len(target_companies) * 100) if target_companies else 0

        if imputed > 0:
            print(f"  {indicator}:")
            print(f"    原始: {original} ({original/len(target_companies)*100:.1f}%), 填充: {imputed}, 合计: {total} ({total/len(target_companies)*100:.1f}%)")
            print(f"    覆盖提升: +{coverage_improvement:.1f}%")

    # 失败原因统计
    failure_reasons = Counter(r.failure_reason for r in all_results if not r.success and r.failure_reason)
    if failure_reasons:
        print("\n失败原因统计:")
        for reason, count in failure_reasons.most_common(5):
            print(f"  {reason}: {count}")

    # 合并原始和填充观测
    all_enhanced = observations + imputed_observations
    print(f"\n总观测数: {len(all_enhanced)} (原始 {len(observations)} + 填充 {len(imputed_observations)})")

    # 保存增强观测数据
    print(f"\n保存增强观测数据: {args.output}")
    save_observations(all_enhanced, args.output)

    # 保存审计报告
    if args.audit:
        print(f"保存审计报告: {args.audit}")

        audit_data = {
            "policy_version": "industry-imputation-v1",
            "input_file": str(args.input),
            "output_file": str(args.output),
            "industry_mapping_file": str(args.industry_mapping),
            "target_year": args.target_year,
            "min_industry_sample": args.min_sample,
            "use_median": args.use_median,
            "original_observations": len(observations),
            "imputed_observations": len(imputed_observations),
            "total_observations": len(all_enhanced),
            "target_companies": len(target_companies),
            "imputation_attempts": len(all_results),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_count / len(all_results) if all_results else 0,
            "industry_distribution": dict(industry_counts),
            "benchmarks_count": len(benchmarks),
            "coverage_by_indicator": {
                indicator: {
                    "indicator_code": indicator,
                    "original_count": target_by_indicator.get(indicator, 0),
                    "imputed_count": imputed_by_indicator.get(indicator, 0),
                    "total_count": target_by_indicator.get(indicator, 0) + imputed_by_indicator.get(indicator, 0),
                    "original_coverage_pct": target_by_indicator.get(indicator, 0) / len(target_companies) * 100 if target_companies else 0,
                    "imputed_coverage_pct": imputed_by_indicator.get(indicator, 0) / len(target_companies) * 100 if target_companies else 0,
                    "total_coverage_pct": (target_by_indicator.get(indicator, 0) + imputed_by_indicator.get(indicator, 0)) / len(target_companies) * 100 if target_companies else 0,
                }
                for indicator in IMPUTATION_WHITELIST
            },
            "failure_reasons": dict(failure_reasons.most_common()),
            "notice": "填充值仅用于研究排名，不进入正式排名。不修改总分计算算法。",
        }

        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(audit_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n✓ 填充完成")
    print("\n重要提醒:")
    print("  - 填充值仅用于研究排名")
    print("  - 正式排名仍使用disclosed_weight_v1策略")
    print("  - 不修改总分计算算法")


if __name__ == "__main__":
    main()
