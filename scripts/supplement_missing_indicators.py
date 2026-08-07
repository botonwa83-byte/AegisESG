#!/usr/bin/env python3
"""
补充缺失的15个定量指标
优先从财务数据计算公司治理指标
"""

import csv
import json
from pathlib import Path
from collections import defaultdict

print("=" * 80)
print("补充缺失的定量指标 - 从财务数据提取")
print("=" * 80)

# 读取现有的财务指标
financial_data = defaultdict(dict)

with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row['company_code']
        financial_data[code][row['indicator_code']] = float(row['value'])

print(f"\n已加载 {len(financial_data)} 家企业的现有指标数据")

# 定义需要计算的指标
indicators_to_calculate = {
    # 公司治理指标 - 可以从现有数据计算
    'Q_G_DEBT_RATIO': {
        'name': '资产负债率',
        'formula': lambda d: (d.get('Q_G_TOTAL_LIABILITIES', 0) / d.get('Q_G_TOTAL_ASSETS', 1)) * 100
                           if d.get('Q_G_TOTAL_ASSETS', 0) > 0 else None,
        'unit': '%'
    },
    'Q_G_ROTA': {
        'name': '总资产收益率',
        'formula': lambda d: (d.get('Q_G_NET_PROFIT', 0) / d.get('Q_G_TOTAL_ASSETS', 1)) * 100
                           if d.get('Q_G_TOTAL_ASSETS', 0) > 0 else None,
        'unit': '%'
    },
    'Q_G_OPERATING_CASH_RATE': {
        'name': '营业收现率',
        'formula': lambda d: (d.get('Q_G_OPERATING_CASH_FLOW', 0) / d.get('Q_G_REVENUE', 1)) * 100
                           if d.get('Q_G_REVENUE', 0) > 0 else None,
        'unit': '%'
    },
    'Q_G_COST_REVENUE_RATIO': {
        'name': '成本费用占营业收入比例',
        'formula': lambda d: ((d.get('Q_G_OPERATING_COST', 0) + d.get('Q_G_TOTAL_EXPENSES', 0)) /
                            d.get('Q_G_REVENUE', 1)) * 100
                           if d.get('Q_G_REVENUE', 0) > 0 else None,
        'unit': '%'
    },
    'Q_G_TWO_FUNDS_RATIO': {
        'name': '两金占流动资产比例',
        'formula': lambda d: ((d.get('Q_G_INVENTORY', 0) + d.get('Q_G_ACCOUNTS_RECEIVABLE', 0)) /
                            d.get('Q_G_CURRENT_ASSETS', 1)) * 100
                           if d.get('Q_G_CURRENT_ASSETS', 0) > 0 else None,
        'unit': '%'
    },
    'Q_G_EBITDA_INTEREST_COVER': {
        'name': 'EBITDA利息倍数',
        'formula': lambda d: d.get('Q_G_EBITDA', 0) / d.get('Q_G_INTEREST_EXPENSE', 1)
                           if d.get('Q_G_INTEREST_EXPENSE', 0) > 0 else None,
        'unit': '倍'
    },
}

# 计算新指标
calculated = defaultdict(dict)
for company_code, data in financial_data.items():
    for indicator_code, config in indicators_to_calculate.items():
        try:
            value = config['formula'](data)
            if value is not None:
                calculated[company_code][indicator_code] = {
                    'value': value,
                    'source': 'calculated_from_financial',
                    'confidence': 0.85
                }
        except:
            pass

print(f"\n计算结果统计:")
for indicator_code, config in indicators_to_calculate.items():
    count = sum(1 for c in calculated.values() if indicator_code in c)
    print(f"  {config['name']:<20} ({indicator_code}): {count}家企业")

# 检查还需要从报告提取的指标
need_extraction = [
    'Q_G_DIVIDEND_PER_SHARE',  # 现金分红 - 需要从利润分配表提取
    'Q_S_EMPLOYEE_SALARY',      # 员工薪酬 - 从应付职工薪酬/员工人数
    'Q_S_CHARITY_RATE',         # 公益投入 - 从ESG报告
    'Q_S_UNIONIZATION_RATE',    # 工会覆盖率 - 从ESG报告
    'Q_S_TRAINING_COVERAGE',    # 培训覆盖率 - 从ESG报告
    'Q_S_TRAINING_HOURS',       # 培训时长 - 从ESG报告
    'Q_S_EMPLOYEE_SATISFACTION', # 员工满意度 - 从ESG报告
    'Q_E_RECYCLED_WATER_RATE',  # 再生水比例 - 从环境报告
    'Q_E_HAZARDOUS_WASTE_INTENSITY', # 危废强度 - 从环境报告
]

print(f"\n还需要从报告提取的指标: {len(need_extraction)}个")
for ind in need_extraction:
    print(f"  - {ind}")

# 合并到现有数据
print(f"\n合并计算结果到数据集...")
new_rows = []
with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    existing_rows = list(reader)
    fieldnames = reader.fieldnames

# 获取公司名称映射
company_names = {}
with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['company_code'] not in company_names:
            company_names[row['company_code']] = row['company_name']

# 添加计算的新指标
for company_code, indicators in calculated.items():
    for indicator_code, data in indicators.items():
        new_rows.append({
            'company_code': company_code,
            'company_name': company_names.get(company_code, ''),
            'report_year': 2025,
            'indicator_code': indicator_code,
            'value': data['value'],
            'source': data['source'],
            'confidence': data['confidence']
        })

print(f"  新增 {len(new_rows)} 条计算指标")

# 保存（先保存到临时文件验证）
output_file = 'output/audit/ci_merged_with_calculated_v1_2025.csv'
with open(output_file, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(existing_rows)
    writer.writerows(new_rows)

print(f"\n已保存到: {output_file}")
print(f"  原有数据: {len(existing_rows)}条")
print(f"  新增数据: {len(new_rows)}条")
print(f"  总计: {len(existing_rows) + len(new_rows)}条")

print("\n" + "=" * 80)
print("✅ 已计算6个公司治理指标")
print("⏳ 还需要从ESG/财务报告提取9个指标")
print("=" * 80)
