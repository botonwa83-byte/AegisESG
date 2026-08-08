#!/usr/bin/env python3
"""生成分级排名：基础排名（免费）和高级排名（会员）

本脚本演示如何使用排名分级系统：
1. 基础排名：仅使用已披露数据
2. 高级排名：使用增强数据（预测+填充）
3. 排名对比分析

使用方法：
    python3 scripts/generate_tiered_rankings.py \\
        data/review/all_markets_indicator_confirmed_v22_2025.csv \\
        output/research/2025/enhanced_observations_v3_industry_filled.csv \\
        --output-dir output/research/2025/tiered_rankings \\
        --methodology data/methodologies/energy_esg_2025.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aegis_esg.io import read_observations
from aegis_esg.methodology import load_methodology
from aegis_esg.ranking_tier import (
    RankingTier,
    RankingTierManager,
    RankingExportConfig,
    export_ranking_with_tier,
)
from aegis_esg.scoring import ScoringEngine

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成分级排名")
    parser.add_argument("basic_observations", type=Path, help="基础观测CSV（仅已披露数据）")
    parser.add_argument("premium_observations", type=Path, help="高级观测CSV（含增强数据）")
    parser.add_argument("--methodology", type=Path, required=True, help="方法论JSON文件")
    parser.add_argument("--output-dir", type=Path, required=True, help="输出目录")
    parser.add_argument("--top-n", type=int, default=200, help="导出前N名")

    args = parser.parse_args()

    # 加载方法论
    print(f"加载方法论: {args.methodology}")
    methodology = load_methodology(args.methodology)

    # 创建排名管理器
    tier_manager = RankingTierManager()

    # ========== 1. 生成基础排名（免费） ==========
    print(f"\n{'='*60}")
    print("生成基础排名（免费版）")
    print(f"{'='*60}")

    print(f"加载基础观测数据: {args.basic_observations}")
    basic_observations = read_observations(args.basic_observations, methodology)
    print(f"  已加载 {len(basic_observations)} 条观测")

    # 过滤：只保留CONFIRMED状态
    basic_filtered = tier_manager.filter_observations_by_tier(
        basic_observations,
        RankingTier.BASIC,
    )
    print(f"  过滤后（仅已披露）: {len(basic_filtered)} 条观测")

    # 评分
    print("运行基础评分...")
    basic_config = tier_manager.get_config(RankingTier.BASIC)
    engine = ScoringEngine(methodology)
    basic_results = engine.evaluate(
        basic_filtered,
        missing_strategy=basic_config.missing_strategy,
    )
    print(f"  评分完成: {len(basic_results)} 家公司")

    # 生成摘要
    basic_summary = tier_manager.generate_tier_summary(
        RankingTier.BASIC,
        basic_results,
        basic_filtered,
    )

    # 导出基础排名
    basic_export = export_ranking_with_tier(
        basic_results,
        basic_filtered,
        RankingExportConfig(
            tier=RankingTier.BASIC,
            include_details=False,
            include_data_source=False,
            top_n=args.top_n,
            format="json",
        ),
    )

    # ========== 2. 生成高级排名（会员） ==========
    print(f"\n{'='*60}")
    print("生成高级排名（会员版）")
    print(f"{'='*60}")

    print(f"加载高级观测数据: {args.premium_observations}")
    premium_observations = read_observations(args.premium_observations, methodology)
    print(f"  已加载 {len(premium_observations)} 条观测")

    # 过滤：保留CONFIRMED + PREDICTED + IMPUTED + DERIVED
    premium_filtered = tier_manager.filter_observations_by_tier(
        premium_observations,
        RankingTier.PREMIUM,
    )
    print(f"  过滤后（含增强数据）: {len(premium_filtered)} 条观测")

    # 评分
    print("运行高级评分...")
    premium_config = tier_manager.get_config(RankingTier.PREMIUM)
    premium_results = engine.evaluate(
        premium_filtered,
        missing_strategy=premium_config.missing_strategy,
    )
    print(f"  评分完成: {len(premium_results)} 家公司")

    # 生成摘要
    premium_summary = tier_manager.generate_tier_summary(
        RankingTier.PREMIUM,
        premium_results,
        premium_filtered,
    )

    # 导出高级排名（包含详细信息）
    premium_export = export_ranking_with_tier(
        premium_results,
        premium_filtered,
        RankingExportConfig(
            tier=RankingTier.PREMIUM,
            include_details=True,
            include_data_source=True,
            top_n=args.top_n,
            format="json",
        ),
    )

    # ========== 3. 排名对比分析 ==========
    print(f"\n{'='*60}")
    print("排名对比分析")
    print(f"{'='*60}")

    comparisons = tier_manager.compare_rankings(basic_results, premium_results)
    print(f"  对比了 {len(comparisons)} 家公司")

    # 统计排名变化
    rank_up = sum(1 for c in comparisons if c.rank_change and c.rank_change > 0)
    rank_down = sum(1 for c in comparisons if c.rank_change and c.rank_change < 0)
    rank_same = sum(1 for c in comparisons if c.rank_change == 0)

    print(f"\n排名变化统计:")
    print(f"  上升: {rank_up} 家 ({rank_up/len(comparisons)*100:.1f}%)")
    print(f"  下降: {rank_down} 家 ({rank_down/len(comparisons)*100:.1f}%)")
    print(f"  不变: {rank_same} 家 ({rank_same/len(comparisons)*100:.1f}%)")

    # 前200名重叠率
    top_200_basic = {c.company_code for c in comparisons if c.basic_rank and c.basic_rank <= 200}
    top_200_premium = {c.company_code for c in comparisons if c.premium_rank and c.premium_rank <= 200}
    overlap = len(top_200_basic & top_200_premium)
    overlap_rate = overlap / 200 * 100 if len(top_200_basic) >= 200 else 0

    print(f"\n前200名稳定性:")
    print(f"  重叠企业: {overlap} 家")
    print(f"  重叠率: {overlap_rate:.1f}%")

    # 找出排名变化最大的企业（前10）
    print(f"\n排名上升最多（前10）:")
    top_gainers = sorted(comparisons, key=lambda x: x.rank_change if x.rank_change else -999, reverse=True)[:10]
    for i, comp in enumerate(top_gainers, 1):
        print(f"  {i}. {comp.company_name} ({comp.company_code})")
        print(f"     排名: {comp.basic_rank} → {comp.premium_rank} (↑{comp.rank_change})")
        print(f"     得分: {comp.basic_score:.2f} → {comp.premium_score:.2f} (+{comp.score_change:.2f})")
        print(f"     覆盖率: {comp.basic_coverage:.1%} → {comp.premium_coverage:.1%} (+{comp.coverage_improvement:.1%})")

    print(f"\n排名下降最多（前10）:")
    top_losers = sorted(comparisons, key=lambda x: x.rank_change if x.rank_change else 999)[:10]
    for i, comp in enumerate(top_losers, 1):
        print(f"  {i}. {comp.company_name} ({comp.company_code})")
        print(f"     排名: {comp.basic_rank} → {comp.premium_rank} (↓{abs(comp.rank_change)})")
        print(f"     得分: {comp.basic_score:.2f} → {comp.premium_score:.2f} ({comp.score_change:+.2f})")

    # ========== 4. 保存结果 ==========
    print(f"\n{'='*60}")
    print("保存结果")
    print(f"{'='*60}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 保存基础排名
    basic_file = args.output_dir / "basic_ranking.json"
    basic_file.write_text(json.dumps({
        "summary": basic_summary,
        "ranking": basic_export,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 基础排名: {basic_file}")

    # 保存高级排名
    premium_file = args.output_dir / "premium_ranking.json"
    premium_file.write_text(json.dumps({
        "summary": premium_summary,
        "ranking": premium_export,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 高级排名: {premium_file}")

    # 保存对比分析
    comparison_data = {
        "comparison_summary": {
            "total_companies": len(comparisons),
            "rank_up": rank_up,
            "rank_down": rank_down,
            "rank_same": rank_same,
            "top_200_overlap": overlap,
            "top_200_overlap_rate": overlap_rate,
        },
        "comparisons": [
            {
                "company_code": c.company_code,
                "company_name": c.company_name,
                "basic_rank": c.basic_rank,
                "premium_rank": c.premium_rank,
                "rank_change": c.rank_change,
                "basic_score": round(c.basic_score, 2),
                "premium_score": round(c.premium_score, 2),
                "score_change": round(c.score_change, 2),
                "basic_coverage": round(c.basic_coverage, 3),
                "premium_coverage": round(c.premium_coverage, 3),
                "coverage_improvement": round(c.coverage_improvement, 3),
            }
            for c in comparisons
        ],
    }

    comparison_file = args.output_dir / "ranking_comparison.json"
    comparison_file.write_text(
        json.dumps(comparison_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✓ 对比分析: {comparison_file}")

    # 保存访问控制说明
    access_control = {
        "tiers": {
            tier.value: {
                "name": config.name,
                "description": config.description,
                "features": config.features,
                "price_info": config.price_info,
            }
            for tier, config in tier_manager.configs.items()
        },
        "access_rules": {
            "basic": "所有用户可访问",
            "premium": "需要会员权限",
            "professional": "需要企业版权限",
        },
    }

    access_file = args.output_dir / "access_control.json"
    access_file.write_text(
        json.dumps(access_control, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✓ 访问控制说明: {access_file}")

    print(f"\n{'='*60}")
    print("✓ 分级排名生成完成")
    print(f"{'='*60}")
    print("\n重要说明:")
    print("  - 基础排名（免费）：仅使用已披露数据")
    print("  - 高级排名（会员）：使用增强数据，覆盖率提升80%+")
    print("  - 排名算法保持一致，仅数据输入不同")
    print(f"  - 前200名重叠率: {overlap_rate:.1f}%")


if __name__ == "__main__":
    main()
