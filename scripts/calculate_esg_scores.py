#!/usr/bin/env python3
"""
ESG评分计算引擎
基于DL/T 2971-2025标准，计算企业ESG综合得分
"""

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

# 读取方法论
with open('data/methodologies/energy_esg_2025_research_sasac.json', 'r', encoding='utf-8') as f:
    methodology = json.load(f)

print("=" * 70)
print("ESG评分计算引擎 - DL/T 2971-2025")
print("=" * 70)

# 构建指标映射
indicator_map = {}
for ind in methodology['indicators']:
    indicator_map[ind['code']] = ind

quantitative_weight_total = sum(ind['weight'] for ind in methodology['indicators'] if ind['kind'] == 'quantitative')
qualitative_weight_total = sum(ind['weight'] for ind in methodology['indicators'] if ind['kind'] == 'qualitative')

print(f"\n方法论配置:")
print(f"  定量指标总权重: {quantitative_weight_total}")
print(f"  定性指标总权重: {qualitative_weight_total}")
print(f"  定量比例: {methodology['quantitative_ratio'] * 100}%")
print(f"  定性比例: {methodology['qualitative_ratio'] * 100}%")
print(f"  缺失值策略: {methodology['missing_policy']}")

# 读取企业数据
company_data = defaultdict(lambda: defaultdict(dict))
with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        company = row['company_code']
        indicator = row['indicator_code']
        company_data[company][indicator] = {
            'value': float(row['value']),
            'source': row['source'],
            'confidence': float(row['confidence']),
            'company_name': row['company_name']
        }

print(f"\n数据加载:")
print(f"  企业数: {len(company_data)}")
print(f"  平均指标数/企业: {sum(len(d) for d in company_data.values()) / len(company_data):.1f}")

# 计算行业统计（用于归一化）
def calculate_industry_stats(data, indicator_code):
    """计算指标的行业统计信息（均值、标准差）"""
    values = []
    for company_indicators in data.values():
        if indicator_code in company_indicators:
            values.append(company_indicators[indicator_code]['value'])

    if len(values) < 3:
        return None

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance)

    return {
        'mean': mean,
        'std': std,
        'min': min(values),
        'max': max(values),
        'count': len(values)
    }

# 计算所有指标的统计信息
print("\n计算指标统计信息...")
indicator_stats = {}
for ind_code in indicator_map.keys():
    if indicator_map[ind_code]['kind'] == 'quantitative':
        stats = calculate_industry_stats(company_data, ind_code)
        if stats:
            indicator_stats[ind_code] = stats

print(f"  有效指标数: {len(indicator_stats)}/{len([i for i in indicator_map.values() if i['kind'] == 'quantitative'])}")

# 评分函数
def score_indicator(value, indicator_meta, stats):
    """
    对单个指标进行评分（0-100分）
    使用正态分布标准化方法
    """
    if stats is None or stats['std'] == 0:
        return 50.0  # 无法归一化时返回中值

    # 标准化（z-score）
    z_score = (value - stats['mean']) / stats['std']

    # 根据指标方向调整
    direction = indicator_meta.get('direction', 'positive')
    if direction == 'negative':
        z_score = -z_score  # 负向指标取反
    elif direction == 'bidirectional':
        # 双向指标：偏离最优值越远分数越低
        benchmark = indicator_meta.get('benchmark', stats['mean'])
        z_score = -abs((value - benchmark) / stats['std'])

    # 将z-score映射到0-100
    # 使用累积分布函数（CDF）
    # z=0 -> 50分, z=2 -> ~97分, z=-2 -> ~3分
    score = 50 + 20 * z_score  # 简化的线性映射

    # 限制在0-100范围内
    return max(0, min(100, score))

# 计算每个企业的得分
print("\n计算企业ESG得分...")
company_scores = []

for company_code, indicators in company_data.items():
    company_name = list(indicators.values())[0]['company_name']

    # 定量指标得分
    quantitative_score = 0
    quantitative_weight_sum = 0
    indicator_scores = {}

    for ind_code, ind_meta in indicator_map.items():
        if ind_meta['kind'] != 'quantitative':
            continue

        weight = ind_meta['weight']

        if ind_code in indicators:
            value = indicators[ind_code]['value']
            stats = indicator_stats.get(ind_code)

            if stats:
                score = score_indicator(value, ind_meta, stats)
                # 根据数据来源调整置信度权重
                confidence = indicators[ind_code]['confidence']
                weighted_score = score * weight * confidence
                quantitative_score += weighted_score
                quantitative_weight_sum += weight * confidence

                indicator_scores[ind_code] = {
                    'value': value,
                    'score': score,
                    'weight': weight,
                    'source': indicators[ind_code]['source']
                }
        else:
            # 缺失值按0分处理
            if methodology['missing_policy'] == 'zero':
                quantitative_weight_sum += weight

    # 归一化定量得分
    if quantitative_weight_sum > 0:
        quantitative_normalized = quantitative_score / quantitative_weight_sum
    else:
        quantitative_normalized = 0

    # 定性指标得分（暂时设为0，因为未提取定性数据）
    qualitative_normalized = 0

    # 计算分维度得分（E/S/G）
    dimension_scores = {}
    dimension_weights = {}

    for dimension in ['E', 'S', 'G']:
        dim_score = 0
        dim_weight_sum = 0

        for ind_code, ind_meta in indicator_map.items():
            if ind_meta['kind'] != 'quantitative':
                continue
            if ind_meta.get('dimension') != dimension:
                continue

            weight = ind_meta['weight']

            if ind_code in indicators:
                value = indicators[ind_code]['value']
                stats = indicator_stats.get(ind_code)

                if stats:
                    score = score_indicator(value, ind_meta, stats)
                    confidence = indicators[ind_code]['confidence']
                    dim_score += score * weight * confidence
                    dim_weight_sum += weight * confidence
            else:
                # 缺失值按0分处理
                if methodology['missing_policy'] == 'zero':
                    dim_weight_sum += weight

        # 归一化维度得分
        if dim_weight_sum > 0:
            dimension_scores[dimension] = dim_score / dim_weight_sum
            dimension_weights[dimension] = dim_weight_sum
        else:
            dimension_scores[dimension] = 0
            dimension_weights[dimension] = 0

    # 综合得分
    esg_score = (quantitative_normalized * methodology['quantitative_ratio'] +
                 qualitative_normalized * methodology['qualitative_ratio'])

    company_scores.append({
        'company_code': company_code,
        'company_name': company_name,
        'esg_score': esg_score,
        'quantitative_score': quantitative_normalized,
        'qualitative_score': qualitative_normalized,
        'e_score': dimension_scores.get('E', 0),
        's_score': dimension_scores.get('S', 0),
        'g_score': dimension_scores.get('G', 0),
        'indicator_count': len(indicators),
        'extracted_count': sum(1 for i in indicators.values() if i['source'] == 'extracted'),
        'calculated_count': sum(1 for i in indicators.values() if i['source'] == 'calculated'),
        'filled_count': sum(1 for i in indicators.values() if i['source'] == 'industry_filled'),
    })

# 排序
company_scores.sort(key=lambda x: x['esg_score'], reverse=True)

# 添加排名
for i, company in enumerate(company_scores, 1):
    company['rank'] = i

print(f"  已计算 {len(company_scores)} 家企业得分")

# 保存结果
output_file = 'output/audit/esg_scores_v1_2025.csv'
with open(output_file, 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['rank', 'company_code', 'company_name', 'esg_score',
                 'quantitative_score', 'qualitative_score', 'e_score', 's_score', 'g_score',
                 'indicator_count', 'extracted_count', 'calculated_count', 'filled_count']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(company_scores)

print(f"\n已保存到: {output_file}")

# 统计摘要
print("\n" + "=" * 70)
print("评分统计摘要")
print("=" * 70)

scores = [c['esg_score'] for c in company_scores]
print(f"\nESG综合得分:")
print(f"  平均分: {sum(scores) / len(scores):.2f}")
print(f"  最高分: {max(scores):.2f}")
print(f"  最低分: {min(scores):.2f}")
print(f"  中位数: {sorted(scores)[len(scores) // 2]:.2f}")

# 维度得分统计
e_scores = [c['e_score'] for c in company_scores if c['e_score'] > 0]
s_scores = [c['s_score'] for c in company_scores if c['s_score'] > 0]
g_scores = [c['g_score'] for c in company_scores if c['g_score'] > 0]

print(f"\n分维度得分统计:")
if e_scores:
    print(f"  E(环境)维度: 平均{sum(e_scores)/len(e_scores):.2f} 最高{max(e_scores):.2f} 最低{min(e_scores):.2f}")
if s_scores:
    print(f"  S(社会)维度: 平均{sum(s_scores)/len(s_scores):.2f} 最高{max(s_scores):.2f} 最低{min(s_scores):.2f}")
if g_scores:
    print(f"  G(治理)维度: 平均{sum(g_scores)/len(g_scores):.2f} 最高{max(g_scores):.2f} 最低{min(g_scores):.2f}")

print(f"\nTop 10企业:")
for company in company_scores[:10]:
    print(f"  {company['rank']:>3}. {company['company_name'][:20]:<20} {company['esg_score']:.2f}分 " +
          f"[E:{company['e_score']:.1f} S:{company['s_score']:.1f} G:{company['g_score']:.1f}] " +
          f"(提取{company['extracted_count']} 计算{company['calculated_count']} 填充{company['filled_count']})")

print("\n" + "=" * 70)
print("✅ ESG评分计算完成")
print("=" * 70)
