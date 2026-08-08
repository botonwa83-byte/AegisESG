#!/usr/bin/env python3
"""2024-2025同比趋势分析

分析相同公司在2024年（基于2023年报）和2025年（基于2024年报）的指标变化：
1. 识别稳定指标（同比变化小）- 适合线性预测
2. 识别高波动指标（同比变化大）- 需要谨慎预测
3. 计算平均同比增长率
4. 发现异常变化企业（需要复核）

使用方法：
    python3 scripts/analyze_yoy_trends.py \\
        data/reference/2024_key_indicator_observations.csv \\
        data/review/all_markets_indicator_confirmed_v22_2025.csv \\
        --output output/audit/yoy_trends_2024_2025.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_2024_data(path: Path) -> dict:
    """加载2024年数据（基于2023年报）"""
    data = defaultdict(dict)  # {company_code: {indicator_code: value}}

    with path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            company_code = row.get('stock_code', '').strip()
            indicator_code = row.get('indicator_code', '').strip()
            raw_value = row.get('raw_value', '').strip()

            if not company_code or not indicator_code or not raw_value:
                continue

            try:
                value = float(raw_value)
                data[company_code][indicator_code] = value
            except ValueError:
                continue

    return data


def load_2025_data(path: Path) -> dict:
    """加载2025年数据（基于2024年报）"""
    data = defaultdict(dict)  # {company_code: {indicator_code: value}}

    with path.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            company_code = row.get('company_code', '').strip()
            indicator_code = row.get('indicator_code', '').strip()
            value_str = row.get('value', '').strip()
            status = row.get('status', 'confirmed').strip()

            # 仅使用已确认的原始披露数据
            if status != 'confirmed' or not company_code or not indicator_code or not value_str:
                continue

            try:
                value = float(value_str)
                data[company_code][indicator_code] = value
            except ValueError:
                continue

    return data


def analyze_yoy_trends(data_2024: dict, data_2025: dict) -> dict[str, Any]:
    """分析同比趋势"""

    # 按指标统计
    indicator_trends = defaultdict(lambda: {
        'matched_pairs': 0,
        'yoy_changes': [],
        'stable_count': 0,  # 变化<10%
        'moderate_count': 0,  # 变化10-30%
        'high_volatility_count': 0,  # 变化>30%
    })

    # 按企业统计
    company_trends = defaultdict(lambda: {
        'matched_indicators': 0,
        'avg_yoy_change': 0,
        'max_change_indicator': None,
        'max_change_value': 0,
    })

    # 异常变化案例
    anomalies = []

    # 匹配2024-2025数据
    matched_companies = set(data_2024.keys()) & set(data_2025.keys())

    for company_code in matched_companies:
        indicators_2024 = data_2024[company_code]
        indicators_2025 = data_2025[company_code]

        matched_indicators = set(indicators_2024.keys()) & set(indicators_2025.keys())
        company_changes = []

        for indicator_code in matched_indicators:
            value_2024 = indicators_2024[indicator_code]
            value_2025 = indicators_2025[indicator_code]

            # 跳过零值或接近零的值
            if abs(value_2024) < 0.001 or abs(value_2025) < 0.001:
                continue

            # 计算同比变化率
            yoy_change = (value_2025 - value_2024) / abs(value_2024) * 100

            # 记录指标级统计
            ind_stats = indicator_trends[indicator_code]
            ind_stats['matched_pairs'] += 1
            ind_stats['yoy_changes'].append(yoy_change)

            # 分类稳定性
            abs_change = abs(yoy_change)
            if abs_change < 10:
                ind_stats['stable_count'] += 1
            elif abs_change < 30:
                ind_stats['moderate_count'] += 1
            else:
                ind_stats['high_volatility_count'] += 1

            # 记录企业级统计
            company_changes.append(abs(yoy_change))

            # 识别异常变化（>100%或<-80%）
            if abs_change > 100:
                anomalies.append({
                    'company_code': company_code,
                    'indicator_code': indicator_code,
                    'value_2024': round(value_2024, 3),
                    'value_2025': round(value_2025, 3),
                    'yoy_change': round(yoy_change, 1),
                })

            # 更新企业最大变化
            comp_stats = company_trends[company_code]
            if abs_change > comp_stats['max_change_value']:
                comp_stats['max_change_value'] = abs_change
                comp_stats['max_change_indicator'] = indicator_code

        # 企业平均变化
        if company_changes:
            company_trends[company_code]['matched_indicators'] = len(company_changes)
            company_trends[company_code]['avg_yoy_change'] = sum(company_changes) / len(company_changes)

    # 计算指标级汇总统计
    indicator_summary = []
    for code, stats in indicator_trends.items():
        if stats['matched_pairs'] == 0:
            continue

        changes = stats['yoy_changes']
        avg_change = sum(changes) / len(changes)
        abs_changes = [abs(c) for c in changes]
        avg_abs_change = sum(abs_changes) / len(abs_changes)

        # 计算标准差
        variance = sum((c - avg_change) ** 2 for c in changes) / len(changes)
        stddev = variance ** 0.5

        indicator_summary.append({
            'indicator_code': code,
            'matched_pairs': stats['matched_pairs'],
            'avg_yoy_change': round(avg_change, 2),
            'avg_abs_change': round(avg_abs_change, 2),
            'stddev': round(stddev, 2),
            'stable_rate': round(stats['stable_count'] / stats['matched_pairs'] * 100, 1),
            'moderate_rate': round(stats['moderate_count'] / stats['matched_pairs'] * 100, 1),
            'high_volatility_rate': round(stats['high_volatility_count'] / stats['matched_pairs'] * 100, 1),
        })

    # 按稳定性排序
    indicator_summary.sort(key=lambda x: x['stable_rate'], reverse=True)

    # 识别最稳定指标（适合预测）
    stable_indicators = [
        ind for ind in indicator_summary
        if ind['stable_rate'] > 70 and ind['matched_pairs'] >= 30
    ]

    # 识别高波动指标（不适合预测）
    volatile_indicators = [
        ind for ind in indicator_summary
        if ind['high_volatility_rate'] > 40 and ind['matched_pairs'] >= 30
    ]

    # 企业排名（按平均变化率）
    company_ranking = [
        {
            'company_code': code,
            'matched_indicators': stats['matched_indicators'],
            'avg_yoy_change': round(stats['avg_yoy_change'], 2),
            'max_change_indicator': stats['max_change_indicator'],
            'max_change_value': round(stats['max_change_value'], 1),
        }
        for code, stats in company_trends.items()
        if stats['matched_indicators'] > 0
    ]
    company_ranking.sort(key=lambda x: x['avg_yoy_change'])

    return {
        'summary': {
            'matched_companies': len(matched_companies),
            'total_companies_2024': len(data_2024),
            'total_companies_2025': len(data_2025),
            'total_indicators_analyzed': len(indicator_summary),
            'stable_indicators_count': len(stable_indicators),
            'volatile_indicators_count': len(volatile_indicators),
            'anomalies_count': len(anomalies),
        },
        'indicator_summary': indicator_summary,
        'stable_indicators': stable_indicators,
        'volatile_indicators': volatile_indicators,
        'anomalies': sorted(anomalies, key=lambda x: abs(x['yoy_change']), reverse=True)[:50],
        'most_stable_companies': company_ranking[:20],
        'most_volatile_companies': company_ranking[-20:],
        'recommendations': generate_recommendations(
            stable_indicators,
            volatile_indicators,
            len(matched_companies),
        ),
    }


def generate_recommendations(stable_indicators, volatile_indicators, matched_companies) -> list[str]:
    """生成建议"""
    recommendations = []

    if stable_indicators:
        recommendations.append(
            f"发现{len(stable_indicators)}个稳定指标（70%+样本变化<10%），"
            f"适合用于时间序列预测"
        )

    if volatile_indicators:
        recommendations.append(
            f"发现{len(volatile_indicators)}个高波动指标（40%+样本变化>30%），"
            f"预测时需要更宽的置信区间"
        )

    if matched_companies < 100:
        recommendations.append(
            f"仅匹配{matched_companies}家公司的历史数据，"
            f"建议扩大历史数据采集范围"
        )

    recommendations.extend([
        "稳定指标可使用线性趋势或移动平均预测",
        "高波动指标建议使用行业均值填充而非预测",
        "异常变化案例需要人工复核，可能是数据质量问题或重大事件",
    ])

    return recommendations


def format_report(analysis: dict) -> str:
    """格式化报告"""
    lines = []
    lines.append("=" * 80)
    lines.append("2024-2025同比趋势分析报告")
    lines.append("=" * 80)
    lines.append("")

    # 摘要
    summary = analysis['summary']
    lines.append("## 一、数据匹配情况")
    lines.append(f"  2024年企业数: {summary['total_companies_2024']}")
    lines.append(f"  2025年企业数: {summary['total_companies_2025']}")
    lines.append(f"  匹配企业数: {summary['matched_companies']}")
    lines.append(f"  分析指标数: {summary['total_indicators_analyzed']}")
    lines.append("")

    lines.append("## 二、指标稳定性分类")
    lines.append(f"  稳定指标: {summary['stable_indicators_count']} (变化<10%占比>70%)")
    lines.append(f"  高波动指标: {summary['volatile_indicators_count']} (变化>30%占比>40%)")
    lines.append(f"  异常变化案例: {summary['anomalies_count']}")
    lines.append("")

    # 稳定指标
    stable = analysis['stable_indicators']
    if stable:
        lines.append(f"## 三、最稳定指标（共{len(stable)}个）")
        lines.append("  适合用于时间序列预测:")
        lines.append("")
        for ind in stable[:15]:
            lines.append(f"  - {ind['indicator_code']}")
            lines.append(f"      匹配样本: {ind['matched_pairs']}")
            lines.append(f"      平均变化: {ind['avg_yoy_change']:+.1f}%")
            lines.append(f"      稳定率: {ind['stable_rate']:.1f}%")
            lines.append("")

    # 高波动指标
    volatile = analysis['volatile_indicators']
    if volatile:
        lines.append(f"## 四、高波动指标（共{len(volatile)}个）")
        lines.append("  不适合预测，建议使用行业均值:")
        lines.append("")
        for ind in volatile[:10]:
            lines.append(f"  - {ind['indicator_code']}")
            lines.append(f"      匹配样本: {ind['matched_pairs']}")
            lines.append(f"      平均变化: {ind['avg_abs_change']:.1f}%")
            lines.append(f"      高波动率: {ind['high_volatility_rate']:.1f}%")
            lines.append("")

    # 异常案例
    anomalies = analysis['anomalies']
    if anomalies:
        lines.append(f"## 五、异常变化案例（前10）")
        lines.append("  需要人工复核的极端变化:")
        lines.append("")
        for anom in anomalies[:10]:
            lines.append(f"  - {anom['company_code']} · {anom['indicator_code']}")
            lines.append(f"      2024: {anom['value_2024']}")
            lines.append(f"      2025: {anom['value_2025']}")
            lines.append(f"      变化: {anom['yoy_change']:+.1f}%")
            lines.append("")

    # 建议
    lines.append("## 六、预测策略建议")
    for i, rec in enumerate(analysis['recommendations'], 1):
        lines.append(f"  {i}. {rec}")
    lines.append("")

    lines.append("=" * 80)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="2024-2025同比趋势分析")
    parser.add_argument(
        "data_2024",
        type=Path,
        help="2024年观测数据CSV",
    )
    parser.add_argument(
        "data_2025",
        type=Path,
        help="2025年观测数据CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/audit/yoy_trends_2024_2025.json",
        help="输出JSON文件",
    )

    args = parser.parse_args()

    print("加载2024年数据...")
    data_2024 = load_2024_data(args.data_2024)
    print(f"  已加载 {len(data_2024)} 家企业")

    print("加载2025年数据...")
    data_2025 = load_2025_data(args.data_2025)
    print(f"  已加载 {len(data_2025)} 家企业")

    print("\n分析同比趋势...")
    analysis = analyze_yoy_trends(data_2024, data_2025)

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
