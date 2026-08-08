#!/usr/bin/env python3
"""数据异常验证工具

分析同比趋势分析中发现的151个异常变化案例：
1. 加载异常案例列表
2. 分析异常类型（数据错误 vs 真实变化）
3. 提供修复建议
4. 生成验证报告

使用方法：
    python3 scripts/validate_data_anomalies.py \\
        output/audit/yoy_trends_2024_2025.json \\
        data/reference/2024_key_indicator_observations.csv \\
        data/review/all_markets_indicator_confirmed_v22_2025.csv \\
        --output output/audit/data_validation_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_anomalies(trends_file: Path) -> list[dict]:
    """加载异常案例"""
    with trends_file.open(encoding='utf-8') as f:
        data = json.load(f)
    return data.get('anomalies', [])


def load_raw_data(path_2024: Path, path_2025: Path) -> tuple[dict, dict]:
    """加载原始数据用于验证"""

    # 2024数据
    data_2024 = {}
    with path_2024.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            key = f"{row.get('stock_code', '').strip()}_{row.get('indicator_code', '').strip()}"
            data_2024[key] = {
                'value': row.get('raw_value', '').strip(),
                'source': row.get('source_file', '').strip(),
            }

    # 2025数据
    data_2025 = {}
    with path_2025.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            key = f"{row.get('company_code', '').strip()}_{row.get('indicator_code', '').strip()}"
            data_2025[key] = {
                'value': row.get('value', '').strip(),
                'source': row.get('source_file', '').strip(),
            }

    return data_2024, data_2025


def classify_anomaly(anomaly: dict, data_2024: dict, data_2025: dict) -> dict:
    """分类异常原因"""

    company_code = anomaly['company_code']
    indicator_code = anomaly['indicator_code']
    value_2024 = anomaly['value_2024']
    value_2025 = anomaly['value_2025']
    yoy_change = anomaly['yoy_change']

    key = f"{company_code}_{indicator_code}"

    # 获取原始数据信息
    raw_2024 = data_2024.get(key, {})
    raw_2025 = data_2025.get(key, {})

    # 分析异常类型
    classification = {
        'company_code': company_code,
        'indicator_code': indicator_code,
        'value_2024': value_2024,
        'value_2025': value_2025,
        'yoy_change': yoy_change,
        'anomaly_type': None,
        'confidence': None,
        'recommendation': None,
        'details': {},
    }

    # 类型1: 极小基数导致的高变化率
    if abs(value_2024) < 0.1 and abs(yoy_change) > 1000:
        classification['anomaly_type'] = 'small_base_effect'
        classification['confidence'] = 'high'
        classification['recommendation'] = '数据正常，小基数导致的高变化率，建议保留'
        classification['details'] = {
            'reason': f'2024年基数仅{value_2024}，微小变化产生极大变化率',
            'action': 'accept',
        }
        return classification

    # 类型2: 数量级错误（可能的单位换算问题）
    ratio = abs(value_2025 / value_2024) if value_2024 != 0 else 0
    if ratio in [10, 100, 1000, 0.1, 0.01, 0.001]:
        classification['anomaly_type'] = 'unit_conversion_error'
        classification['confidence'] = 'high'
        classification['recommendation'] = '疑似单位换算错误，需要人工复核原始数据'
        classification['details'] = {
            'reason': f'变化倍数为{ratio}倍，疑似单位问题',
            'action': 'review',
            'suggested_fix': f'检查{company_code}的{indicator_code}单位是否一致',
        }
        return classification

    # 类型3: 从零值突然有数据（可能是披露改进）
    if value_2024 == 0 and value_2025 > 0:
        classification['anomaly_type'] = 'disclosure_improvement'
        classification['confidence'] = 'medium'
        classification['recommendation'] = '可能是企业开始披露该指标，建议保留'
        classification['details'] = {
            'reason': '2024年未披露（或为0），2025年开始披露',
            'action': 'accept',
        }
        return classification

    # 类型4: R&D费用异常（已知的提取问题）
    if indicator_code == 'Q_S_RD_RATE' and abs(yoy_change) > 500:
        classification['anomaly_type'] = 'known_extraction_issue'
        classification['confidence'] = 'high'
        classification['recommendation'] = '已知的R&D提取一致性问题，需要重新提取'
        classification['details'] = {
            'reason': 'R&D费用在不同年份的提取规则不一致',
            'action': 'reextract',
            'note': '参考同比趋势分析报告',
        }
        return classification

    # 类型5: 能源强度异常（陕西煤业案例）
    if indicator_code == 'Q_E_ENERGY_INTENSITY' and ratio > 40:
        classification['anomaly_type'] = 'energy_intensity_outlier'
        classification['confidence'] = 'high'
        classification['recommendation'] = '能源强度异常增长，需要复核采集方法'
        classification['details'] = {
            'reason': f'能源强度增长{ratio}倍，不符合行业常识',
            'action': 'review',
            'note': '检查是否混淆了绝对值和强度',
        }
        return classification

    # 类型6: 合理的大幅变化（可能是真实业务变化）
    if 100 < abs(yoy_change) < 500:
        classification['anomaly_type'] = 'significant_change'
        classification['confidence'] = 'low'
        classification['recommendation'] = '大幅变化但在合理范围，建议抽查'
        classification['details'] = {
            'reason': '变化较大但可能是真实业务变化',
            'action': 'sample_check',
        }
        return classification

    # 默认: 极端异常
    classification['anomaly_type'] = 'extreme_outlier'
    classification['confidence'] = 'medium'
    classification['recommendation'] = '极端异常，优先级最高，必须人工复核'
    classification['details'] = {
        'reason': f'变化率{yoy_change}%超出正常范围',
        'action': 'urgent_review',
    }

    return classification


def generate_validation_report(classifications: list[dict]) -> dict:
    """生成验证报告"""

    # 按异常类型统计
    by_type = defaultdict(list)
    for cls in classifications:
        by_type[cls['anomaly_type']].append(cls)

    # 按推荐动作分组
    by_action = defaultdict(list)
    for cls in classifications:
        action = cls['details'].get('action', 'unknown')
        by_action[action].append(cls)

    # 优先级排序
    priority_order = [
        'urgent_review',
        'review',
        'reextract',
        'sample_check',
        'accept',
    ]

    prioritized = []
    for action in priority_order:
        items = by_action.get(action, [])
        # 按变化率绝对值排序
        items.sort(key=lambda x: abs(x['yoy_change']), reverse=True)
        prioritized.extend(items)

    # 生成建议
    recommendations = []

    if by_action['urgent_review']:
        recommendations.append(
            f"发现{len(by_action['urgent_review'])}个极端异常案例，需要立即人工复核"
        )

    if by_action['review']:
        recommendations.append(
            f"发现{len(by_action['review'])}个疑似数据质量问题，建议检查提取方法"
        )

    if by_action['reextract']:
        recommendations.append(
            f"发现{len(by_action['reextract'])}个已知提取问题，建议统一提取规则后重新运行"
        )

    if by_action['accept']:
        recommendations.append(
            f"{len(by_action['accept'])}个异常为合理变化或小基数效应，建议保留"
        )

    # 统计摘要
    summary = {
        'total_anomalies': len(classifications),
        'by_type': {
            atype: len(items) for atype, items in by_type.items()
        },
        'by_action': {
            action: len(items) for action, items in by_action.items()
        },
        'urgent_count': len(by_action['urgent_review']),
        'review_count': len(by_action['review']) + len(by_action['reextract']),
        'acceptable_count': len(by_action['accept']),
    }

    return {
        'summary': summary,
        'classifications': prioritized,
        'by_type': {
            atype: [
                {
                    'company_code': cls['company_code'],
                    'indicator_code': cls['indicator_code'],
                    'yoy_change': cls['yoy_change'],
                }
                for cls in items[:10]  # 每类最多10个示例
            ]
            for atype, items in by_type.items()
        },
        'recommendations': recommendations,
        'action_plan': generate_action_plan(by_action),
    }


def generate_action_plan(by_action: dict) -> list[dict]:
    """生成行动计划"""
    plan = []

    if by_action['urgent_review']:
        plan.append({
            'priority': 1,
            'action': '紧急复核',
            'count': len(by_action['urgent_review']),
            'description': '极端异常案例，需要人工复核原始PDF',
            'estimated_time': f"{len(by_action['urgent_review']) * 10}分钟",
            'cases': [
                f"{c['company_code']} · {c['indicator_code']} ({c['yoy_change']:+.0f}%)"
                for c in by_action['urgent_review'][:5]
            ],
        })

    if by_action['reextract']:
        plan.append({
            'priority': 2,
            'action': '重新提取',
            'count': len(by_action['reextract']),
            'description': '已知提取规则不一致，需要统一后重新运行',
            'estimated_time': '1-2天',
            'indicators': list(set(c['indicator_code'] for c in by_action['reextract'])),
        })

    if by_action['review']:
        plan.append({
            'priority': 3,
            'action': '样本复核',
            'count': len(by_action['review']),
            'description': '疑似数据质量问题，抽查10%案例',
            'estimated_time': f"{int(len(by_action['review']) * 0.1 * 5)}分钟",
        })

    return plan


def format_report(report: dict) -> str:
    """格式化报告"""
    lines = []
    lines.append("=" * 80)
    lines.append("数据异常验证报告")
    lines.append("=" * 80)
    lines.append("")

    # 摘要
    summary = report['summary']
    lines.append("## 一、异常分类统计")
    lines.append(f"  总异常数: {summary['total_anomalies']}")
    lines.append(f"  需要紧急复核: {summary['urgent_count']}")
    lines.append(f"  需要一般复核: {summary['review_count']}")
    lines.append(f"  可以接受: {summary['acceptable_count']}")
    lines.append("")

    lines.append("  按异常类型:")
    for atype, count in summary['by_type'].items():
        pct = count / summary['total_anomalies'] * 100
        lines.append(f"    {atype}: {count} ({pct:.1f}%)")
    lines.append("")

    # 行动计划
    lines.append("## 二、行动计划")
    for item in report['action_plan']:
        lines.append(f"  优先级 {item['priority']}: {item['action']}")
        lines.append(f"    数量: {item['count']}")
        lines.append(f"    说明: {item['description']}")
        lines.append(f"    预计时间: {item['estimated_time']}")
        if 'cases' in item:
            lines.append(f"    示例:")
            for case in item['cases']:
                lines.append(f"      - {case}")
        lines.append("")

    # 建议
    lines.append("## 三、处理建议")
    for i, rec in enumerate(report['recommendations'], 1):
        lines.append(f"  {i}. {rec}")
    lines.append("")

    lines.append("=" * 80)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="验证数据异常")
    parser.add_argument(
        "trends_file",
        type=Path,
        help="同比趋势分析JSON文件",
    )
    parser.add_argument(
        "data_2024",
        type=Path,
        help="2024年数据CSV",
    )
    parser.add_argument(
        "data_2025",
        type=Path,
        help="2025年数据CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/audit/data_validation_report.json",
        help="输出JSON文件",
    )

    args = parser.parse_args()

    print("加载异常案例...")
    anomalies = load_anomalies(args.trends_file)
    print(f"  已加载 {len(anomalies)} 个异常案例")

    print("\n加载原始数据...")
    data_2024, data_2025 = load_raw_data(args.data_2024, args.data_2025)
    print(f"  2024年: {len(data_2024)} 条")
    print(f"  2025年: {len(data_2025)} 条")

    print("\n分析异常类型...")
    classifications = []
    for anomaly in anomalies:
        cls = classify_anomaly(anomaly, data_2024, data_2025)
        classifications.append(cls)

    print(f"  已分类 {len(classifications)} 个异常")

    print("\n生成验证报告...")
    report = generate_validation_report(classifications)

    # 保存JSON
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✓ 已保存: {args.output}")

    # 打印报告
    print("\n")
    formatted = format_report(report)
    print(formatted)

    # 保存文本报告
    txt_output = args.output.with_suffix('.txt')
    txt_output.write_text(formatted, encoding='utf-8')
    print(f"✓ 已保存文本报告: {txt_output}")


if __name__ == '__main__':
    main()
