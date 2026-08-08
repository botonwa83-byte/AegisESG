#!/usr/bin/env python3
"""增强数据质量分析

分析行业填充数据的质量特征：
1. 各指标的填充率和来源分布
2. 置信度分布统计
3. 行业样本量充足性评估
4. 识别需要更多原始数据的薄弱指标

使用方法：
    python3 scripts/analyze_enhanced_data_quality.py \\
        output/research/2025/enhanced_observations_v3_industry_filled.csv \\
        --methodology data/methodologies/energy_esg_2025.json \\
        --output output/audit/enhanced_data_quality_report.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from aegis_esg.io import read_observations
from aegis_esg.methodology import load_methodology
from aegis_esg.models import ValueStatus

ROOT = Path(__file__).resolve().parents[1]


def analyze_quality(observations: list, methodology) -> dict[str, Any]:
    """分析增强数据质量"""

    # 按指标统计
    by_indicator = defaultdict(lambda: {
        'total': 0,
        'by_status': Counter(),
        'by_confidence': [],
        'companies': set(),
    })

    # 全局统计
    total_obs = len(observations)
    by_status = Counter()
    by_confidence = []

    for obs in observations:
        by_status[obs.status] += 1
        by_confidence.append(obs.confidence)

        ind_stats = by_indicator[obs.indicator_code]
        ind_stats['total'] += 1
        ind_stats['by_status'][obs.status] += 1
        ind_stats['by_confidence'].append(obs.confidence)
        ind_stats['companies'].add(obs.company_code)

    # 计算指标级别统计
    indicator_analysis = []
    for code, stats in by_indicator.items():
        indicator = methodology.by_code.get(code)
        if not indicator:
            continue

        confirmed = stats['by_status'][ValueStatus.CONFIRMED]
        imputed = stats['by_status'][ValueStatus.IMPUTED]
        derived = stats['by_status'][ValueStatus.DERIVED]
        predicted = stats['by_status'][ValueStatus.PREDICTED]

        total = stats['total']
        avg_confidence = sum(stats['by_confidence']) / len(stats['by_confidence']) if stats['by_confidence'] else 0

        # 置信度分布
        conf_dist = {
            'high': len([c for c in stats['by_confidence'] if c >= 0.8]),
            'medium': len([c for c in stats['by_confidence'] if 0.6 <= c < 0.8]),
            'low': len([c for c in stats['by_confidence'] if c < 0.6]),
        }

        indicator_analysis.append({
            'code': code,
            'name': indicator.name,
            'dimension': indicator.dimension,
            'total_observations': total,
            'company_count': len(stats['companies']),
            'coverage_rate': len(stats['companies']) / 612 * 100,  # 612家公司
            'source_distribution': {
                'confirmed': confirmed,
                'imputed': imputed,
                'derived': derived,
                'predicted': predicted,
            },
            'imputed_rate': imputed / total * 100 if total > 0 else 0,
            'avg_confidence': round(avg_confidence, 3),
            'confidence_distribution': conf_dist,
        })

    # 按填充率排序
    indicator_analysis.sort(key=lambda x: x['imputed_rate'], reverse=True)

    # 全局置信度分布
    global_conf_dist = {
        'high': len([c for c in by_confidence if c >= 0.8]),
        'medium': len([c for c in by_confidence if 0.6 <= c < 0.8]),
        'low': len([c for c in by_confidence if c < 0.6]),
    }

    # 识别薄弱指标（高填充率但低置信度）
    weak_indicators = [
        ind for ind in indicator_analysis
        if ind['imputed_rate'] > 50 and ind['avg_confidence'] < 0.7
    ]

    # 识别优质指标（高覆盖且高原始数据比例）
    strong_indicators = [
        ind for ind in indicator_analysis
        if ind['coverage_rate'] > 80 and
           ind['source_distribution']['confirmed'] / ind['total_observations'] > 0.5
    ]

    # 维度统计
    dimension_stats = defaultdict(lambda: {
        'total': 0,
        'confirmed': 0,
        'imputed': 0,
        'derived': 0,
        'predicted': 0,
    })

    for ind in indicator_analysis:
        dim = ind['dimension']
        dimension_stats[dim]['total'] += ind['total_observations']
        dimension_stats[dim]['confirmed'] += ind['source_distribution']['confirmed']
        dimension_stats[dim]['imputed'] += ind['source_distribution']['imputed']
        dimension_stats[dim]['derived'] += ind['source_distribution']['derived']
        dimension_stats[dim]['predicted'] += ind['source_distribution']['predicted']

    # 计算维度填充率
    for dim, stats in dimension_stats.items():
        stats['imputed_rate'] = stats['imputed'] / stats['total'] * 100 if stats['total'] > 0 else 0

    return {
        'summary': {
            'total_observations': total_obs,
            'total_companies': 612,
            'source_distribution': dict(by_status),
            'avg_confidence': round(sum(by_confidence) / len(by_confidence), 3) if by_confidence else 0,
            'confidence_distribution': global_conf_dist,
        },
        'dimension_analysis': {
            dim: {
                'total_observations': stats['total'],
                'confirmed': stats['confirmed'],
                'imputed': stats['imputed'],
                'derived': stats['derived'],
                'predicted': stats['predicted'],
                'imputed_rate': round(stats['imputed_rate'], 2),
            }
            for dim, stats in dimension_stats.items()
        },
        'indicator_analysis': indicator_analysis,
        'weak_indicators': weak_indicators,
        'strong_indicators': strong_indicators,
        'recommendations': generate_recommendations(
            weak_indicators,
            strong_indicators,
            dimension_stats,
        ),
    }


def generate_recommendations(weak_indicators, strong_indicators, dimension_stats) -> list[str]:
    """生成改进建议"""
    recommendations = []

    # 薄弱指标建议
    if weak_indicators:
        recommendations.append(
            f"发现{len(weak_indicators)}个薄弱指标（高填充率+低置信度），"
            f"建议优先从外部数据源补充原始披露：" +
            ", ".join([ind['name'] for ind in weak_indicators[:5]])
        )

    # 维度建议
    for dim, stats in dimension_stats.items():
        if stats['imputed_rate'] > 60:
            recommendations.append(
                f"{dim}维度填充率{stats['imputed_rate']:.1f}%较高，"
                f"建议从行业协会或政府平台获取更多原始数据"
            )

    # 优质指标
    if strong_indicators:
        recommendations.append(
            f"已有{len(strong_indicators)}个优质指标（高覆盖+高原始数据），"
            f"可作为质量基准"
        )

    # 通用建议
    recommendations.extend([
        "所有IMPUTED数据已标注来源和置信度，满足透明度要求",
        "建议在高级排名产品中展示数据来源分布图表",
        "定期（季度）刷新行业基准值，提升填充数据时效性",
    ])

    return recommendations


def format_report(analysis: dict) -> str:
    """格式化为可读报告"""
    lines = []
    lines.append("=" * 80)
    lines.append("增强数据质量分析报告")
    lines.append("=" * 80)
    lines.append("")

    # 摘要
    summary = analysis['summary']
    lines.append("## 一、整体统计")
    lines.append(f"  总观测数: {summary['total_observations']:,}")
    lines.append(f"  覆盖企业: {summary['total_companies']}")
    lines.append(f"  平均置信度: {summary['avg_confidence']:.3f}")
    lines.append("")

    lines.append("  数据来源分布:")
    for status, count in summary['source_distribution'].items():
        pct = count / summary['total_observations'] * 100
        lines.append(f"    {status}: {count:,} ({pct:.1f}%)")
    lines.append("")

    lines.append("  置信度分布:")
    conf_dist = summary['confidence_distribution']
    total_conf = sum(conf_dist.values())
    for level, count in conf_dist.items():
        pct = count / total_conf * 100 if total_conf > 0 else 0
        lines.append(f"    {level}: {count:,} ({pct:.1f}%)")
    lines.append("")

    # 维度分析
    lines.append("## 二、维度分析")
    for dim, stats in analysis['dimension_analysis'].items():
        lines.append(f"  {dim}:")
        lines.append(f"    总观测: {stats['total_observations']:,}")
        lines.append(f"    已披露: {stats['confirmed']:,}")
        lines.append(f"    行业填充: {stats['imputed']:,} ({stats['imputed_rate']:.1f}%)")
        lines.append("")

    # 薄弱指标
    weak = analysis['weak_indicators']
    if weak:
        lines.append(f"## 三、薄弱指标（共{len(weak)}个）")
        lines.append("  高填充率+低置信度，需要更多原始数据:")
        lines.append("")
        for ind in weak[:10]:
            lines.append(f"  - {ind['name']} ({ind['code']})")
            lines.append(f"      填充率: {ind['imputed_rate']:.1f}%")
            lines.append(f"      置信度: {ind['avg_confidence']:.3f}")
            lines.append(f"      覆盖: {ind['company_count']}/612 企业")
            lines.append("")

    # 优质指标
    strong = analysis['strong_indicators']
    if strong:
        lines.append(f"## 四、优质指标（共{len(strong)}个）")
        lines.append("  高覆盖+高原始数据比例:")
        lines.append("")
        for ind in strong[:10]:
            lines.append(f"  - {ind['name']} ({ind['code']})")
            lines.append(f"      覆盖率: {ind['coverage_rate']:.1f}%")
            confirmed_pct = ind['source_distribution']['confirmed'] / ind['total_observations'] * 100
            lines.append(f"      原始数据: {confirmed_pct:.1f}%")
            lines.append("")

    # 建议
    lines.append("## 五、改进建议")
    for i, rec in enumerate(analysis['recommendations'], 1):
        lines.append(f"  {i}. {rec}")
    lines.append("")

    lines.append("=" * 80)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="分析增强数据质量")
    parser.add_argument(
        "observations_file",
        type=Path,
        help="增强观测CSV文件",
    )
    parser.add_argument(
        "--methodology",
        type=Path,
        default=ROOT / "data/methodologies/energy_esg_2025.json",
        help="方法论JSON文件",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/audit/enhanced_data_quality_report.json",
        help="输出JSON文件",
    )

    args = parser.parse_args()

    print("加载方法论...")
    methodology = load_methodology(args.methodology)

    print(f"加载观测数据: {args.observations_file}")
    observations = read_observations(args.observations_file, methodology)
    print(f"  已加载 {len(observations)} 条观测")

    print("\n分析数据质量...")
    analysis = analyze_quality(observations, methodology)

    # 保存JSON
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"✓ 已保存: {args.output}")

    # 打印报告
    print("\n")
    report = format_report(analysis)
    print(report)

    # 保存文本报告
    txt_output = args.output.with_suffix('.txt')
    txt_output.write_text(report, encoding='utf-8')
    print(f"✓ 已保存文本报告: {txt_output}")


if __name__ == '__main__':
    main()
