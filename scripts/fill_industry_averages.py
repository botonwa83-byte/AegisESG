#!/usr/bin/env python3
"""
行业平均值填充引擎
根据企业所属行业，用行业平均值填充缺失的指标数据
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

# 读取方法论
with open('data/methodologies/energy_esg_2025_research_sasac.json', 'r', encoding='utf-8') as f:
    methodology = json.load(f)

# 提取定量指标列表
quantitative_indicators = [ind['code'] for ind in methodology['indicators'] if ind['kind'] == 'quantitative']
print(f"定量指标总数: {len(quantitative_indicators)}")

# 读取企业注册表（获取行业信息）
company_registry = {}
registry_file = Path('data/reference/2024_energy_company_registry.csv')
if registry_file.exists():
    with open(registry_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('code', row.get('company_code', ''))
            if code:
                company_registry[code] = {
                    'name': row.get('name', row.get('company_name', '')),
                    'industry': row.get('industry_l2', row.get('industry', 'Unknown'))
                }

print(f"企业注册表: {len(company_registry)} 家企业")

# 读取提取数据
data = defaultdict(lambda: defaultdict(dict))
with open('output/audit/ci_incremental_candidates_v1_2025.csv', 'rb') as f:
    f.readline()
    for line in f:
        try:
            line_str = line.decode('utf-8', errors='ignore').strip()
            if not line_str:
                continue
            parts = line_str.split(',')
            if len(parts) >= 5:
                company_code = parts[0].strip()
                company_name = parts[1].strip()
                indicator = parts[3].strip()
                value_str = parts[4].strip()
                if value_str and indicator in quantitative_indicators:
                    data[company_code][indicator] = float(value_str)
                    if company_code not in company_registry:
                        company_registry[company_code] = {'name': company_name, 'industry': 'Unknown'}
        except:
            continue

print(f"已加载 {len(data)} 家企业的提取数据")

# 按行业分组计算平均值
industry_averages = defaultdict(lambda: defaultdict(list))

for company_code, indicators in data.items():
    industry = company_registry.get(company_code, {}).get('industry', 'Unknown')
    for indicator, value in indicators.items():
        # 过滤异常值（简单的3-sigma规则）
        if 0 <= value <= 1e10:  # 合理范围
            industry_averages[industry][indicator].append(value)

# 计算每个行业每个指标的均值和中位数
industry_stats = defaultdict(lambda: defaultdict(dict))

for industry, indicators in industry_averages.items():
    for indicator, values in indicators.items():
        if len(values) >= 3:  # 至少3个样本才计算平均
            sorted_values = sorted(values)
            n = len(sorted_values)
            mean = sum(sorted_values) / n
            median = sorted_values[n // 2]
            industry_stats[industry][indicator] = {
                'mean': mean,
                'median': median,
                'count': n,
                'min': sorted_values[0],
                'max': sorted_values[-1]
            }

print(f"\n行业统计覆盖:")
for industry, indicators in industry_stats.items():
    print(f"  {industry}: {len(indicators)} 个指标")

# 使用行业平均值填充缺失数据
filled_data = []

for company_code in company_registry.keys():
    company_name = company_registry[company_code]['name']
    industry = company_registry[company_code]['industry']

    if industry not in industry_stats:
        continue

    existing_indicators = data.get(company_code, {})

    for indicator in quantitative_indicators:
        if indicator not in existing_indicators:  # 缺失的指标
            if indicator in industry_stats[industry]:
                # 使用行业中位数（比均值更稳健）
                filled_value = industry_stats[industry][indicator]['median']
                filled_data.append({
                    'company_code': company_code,
                    'company_name': company_name,
                    'indicator_code': indicator,
                    'value': filled_value,
                    'source': 'industry_median',
                    'industry': industry,
                    'sample_count': industry_stats[industry][indicator]['count']
                })

print(f"\n成功填充 {len(filled_data)} 条记录")

# 按指标统计
by_indicator = defaultdict(int)
for item in filled_data:
    by_indicator[item['indicator_code']] += 1

print("\n各指标填充数量（前20）:")
for indicator, count in sorted(by_indicator.items(), key=lambda x: -x[1])[:20]:
    print(f"  {indicator}: +{count}条")

# 保存填充结果
with open('output/audit/ci_industry_filled_v1_2025.csv', 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['company_code', 'company_name', 'indicator_code', 'value',
                 'source', 'industry', 'sample_count']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(filled_data)

print(f"\n已保存到: output/audit/ci_industry_filled_v1_2025.csv")

# 统计覆盖率提升
print("\n覆盖率分析:")
total_companies = len(company_registry)
print(f"总企业数: {total_companies}")

# 原始覆盖率
original_coverage = {}
for indicator in quantitative_indicators:
    count = sum(1 for company_data in data.values() if indicator in company_data)
    original_coverage[indicator] = count

# 填充后覆盖率
filled_coverage = {}
for indicator in quantitative_indicators:
    original = original_coverage.get(indicator, 0)
    filled = by_indicator.get(indicator, 0)
    filled_coverage[indicator] = original + filled

print("\n核心指标覆盖率提升（前10）:")
for indicator in ['Q_E_GHG_INTENSITY', 'Q_E_ENERGY_INTENSITY', 'Q_E_SO2_INTENSITY',
                  'Q_E_NOX_INTENSITY', 'Q_E_WATER_INTENSITY', 'Q_E_SOLID_WASTE_INTENSITY',
                  'Q_S_SAFETY_INVEST_RATE', 'Q_S_ENV_INVEST_RATE', 'Q_S_RD_RATE', 'Q_S_DONATION_RATE']:
    original = original_coverage.get(indicator, 0)
    filled_total = filled_coverage.get(indicator, 0)
    original_rate = original / total_companies * 100
    filled_rate = filled_total / total_companies * 100
    print(f"  {indicator}: {original}条({original_rate:.1f}%) → {filled_total}条({filled_rate:.1f}%)")
