#!/usr/bin/env python3
"""
合并所有数据源：直接提取 + 计算强度 + 行业填充
创建完整的评分数据集
"""

import csv
from collections import defaultdict

# 读取所有数据源
all_data = defaultdict(lambda: defaultdict(dict))

# 1. 直接提取数据（优先级最高）
print("读取直接提取数据...")
with open('output/audit/ci_incremental_candidates_v1_2025.csv', 'rb') as f:
    f.readline()
    for line in f:
        try:
            line_str = line.decode('utf-8', errors='ignore').strip()
            if not line_str:
                continue
            parts = line_str.split(',')
            if len(parts) >= 5:
                company = parts[0].strip()
                company_name = parts[1].strip()
                indicator = parts[3].strip()
                value = parts[4].strip()
                if value:
                    all_data[company][indicator] = {
                        'value': float(value),
                        'company_name': company_name,
                        'source': 'extracted',
                        'confidence': 0.90
                    }
        except:
            continue

extracted_count = sum(len(inds) for inds in all_data.values())
print(f"  已加载 {extracted_count} 条提取记录")

# 2. 计算强度数据（优先级中等，只在缺失时填充）
print("\n读取计算强度数据...")
calculated_count = 0
with open('output/audit/ci_calculated_intensities_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        company = row['company_code']
        indicator = row['indicator_code']
        if indicator not in all_data[company]:  # 只在缺失时添加
            all_data[company][indicator] = {
                'value': float(row['value']),
                'company_name': row['company_name'],
                'source': 'calculated',
                'confidence': 0.85
            }
            calculated_count += 1

print(f"  新增 {calculated_count} 条计算记录")

# 3. 行业填充数据（优先级最低，只在前两者都缺失时填充）
print("\n读取行业填充数据...")
filled_count = 0
with open('output/audit/ci_industry_filled_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        company = row['company_code']
        indicator = row['indicator_code']
        if indicator not in all_data[company]:  # 只在缺失时添加
            all_data[company][indicator] = {
                'value': float(row['value']),
                'company_name': row['company_name'],
                'source': 'industry_filled',
                'confidence': 0.60
            }
            filled_count += 1

print(f"  新增 {filled_count} 条填充记录")

# 展开为记录列表
merged_records = []
for company, indicators in all_data.items():
    company_name = list(indicators.values())[0]['company_name']
    for indicator, info in indicators.items():
        merged_records.append({
            'company_code': company,
            'company_name': company_name,
            'report_year': 2025,
            'indicator_code': indicator,
            'value': info['value'],
            'source': info['source'],
            'confidence': info['confidence']
        })

print(f"\n合并结果:")
print(f"  总企业数: {len(all_data)}")
print(f"  总记录数: {len(merged_records)}")

# 按来源统计
by_source = defaultdict(int)
for rec in merged_records:
    by_source[rec['source']] += 1

print(f"\n按来源统计:")
for source, count in sorted(by_source.items()):
    pct = count / len(merged_records) * 100
    print(f"  {source}: {count}条 ({pct:.1f}%)")

# 保存合并结果
with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['company_code', 'company_name', 'report_year', 'indicator_code',
                 'value', 'source', 'confidence']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(merged_records)

print(f"\n已保存到: output/audit/ci_merged_all_sources_v1_2025.csv")

# 计算覆盖率
print("\n核心指标覆盖率:")
core_indicators = ['Q_E_GHG_INTENSITY', 'Q_E_ENERGY_INTENSITY', 'Q_E_SO2_INTENSITY',
                  'Q_E_NOX_INTENSITY', 'Q_E_WATER_INTENSITY', 'Q_E_SOLID_WASTE_INTENSITY']

total_companies = len(all_data)
for indicator in core_indicators:
    count = sum(1 for company_data in all_data.values() if indicator in company_data)
    rate = count / total_companies * 100

    # 按来源统计
    extracted = sum(1 for c in all_data.values() if indicator in c and c[indicator]['source'] == 'extracted')
    calculated = sum(1 for c in all_data.values() if indicator in c and c[indicator]['source'] == 'calculated')
    filled = sum(1 for c in all_data.values() if indicator in c and c[indicator]['source'] == 'industry_filled')

    print(f"  {indicator}: {count}/{total_companies} ({rate:.1f}%)")
    print(f"    提取{extracted} + 计算{calculated} + 填充{filled}")
