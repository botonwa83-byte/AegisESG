#!/usr/bin/env python3
"""合并计算的强度指标到提取结果中"""

import csv

# 读取原始提取结果
original_data = []
with open('output/audit/ci_incremental_candidates_v1_2025.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    original_data = list(reader)

print(f"原始提取记录: {len(original_data)}")

# 读取计算的强度
calculated_data = []
with open('output/audit/ci_calculated_intensities_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        calculated_data.append({
            'company_code': row['company_code'],
            'company_name': row['company_name'],
            'report_year': '2025',
            'indicator_code': row['indicator_code'],
            'value': row['value'],
            'status': 'calculated',
            'source_url': '',
            'source_file': '',
            'source_page': '',
            'evidence_text': f"Calculated from {row['abs_indicator']}={row['abs_value']}, revenue={row['revenue']}",
            'confidence': '0.85'
        })

print(f"计算的强度记录: {len(calculated_data)}")

# 合并（避免重复）
merged = original_data.copy()
existing_keys = {(r['company_code'], r['indicator_code']) for r in original_data}

added = 0
for calc in calculated_data:
    key = (calc['company_code'], calc['indicator_code'])
    if key not in existing_keys:
        merged.append(calc)
        added += 1

print(f"新增计算记录: {added}")
print(f"合并后总记录: {len(merged)}")

# 保存合并结果
with open('output/audit/ci_merged_candidates_v1_2025.csv', 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['company_code', 'company_name', 'report_year', 'indicator_code',
                 'value', 'status', 'source_url', 'source_file', 'source_page',
                 'evidence_text', 'confidence']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(merged)

print("已保存到: output/audit/ci_merged_candidates_v1_2025.csv")
