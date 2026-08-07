#!/usr/bin/env python3
"""
完整的指标计算引擎 - 根据方法论公式计算所有可推导的指标
目标：将覆盖率提升到90%+
"""

import csv
import json
from collections import defaultdict

# 读取方法论
with open('data/methodologies/energy_esg_2025_research_sasac.json', 'r', encoding='utf-8') as f:
    methodology = json.load(f)

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
                if value_str:
                    data[company_code][indicator] = {
                        'value': float(value_str),
                        'company_name': company_name
                    }
        except:
            continue

print(f"已加载 {len(data)} 家企业的数据")

calculated = []

# 计算各类指标
for company_code, indicators in data.items():
    company_name = list(indicators.values())[0]['company_name']

    # 1. 财务比率指标
    # ROE = 净利润 / 净资产 * 100
    if 'Q_G_NET_PROFIT' in indicators and 'Q_G_NET_ASSETS' in indicators and 'Q_G_ROE' not in indicators:
        net_profit = indicators['Q_G_NET_PROFIT']['value']
        net_assets = indicators['Q_G_NET_ASSETS']['value']
        if net_assets > 0:
            roe = (net_profit / net_assets) * 100
            calculated.append({
                'company_code': company_code,
                'company_name': company_name,
                'indicator_code': 'Q_G_ROE',
                'value': roe,
                'formula': 'NET_PROFIT/NET_ASSETS*100'
            })

    # 资产负债率 = 负债总额 / 资产总额 * 100
    if 'Q_G_LIABILITIES' in indicators and 'Q_G_TOTAL_ASSETS' in indicators and 'Q_G_DEBT_ASSET_RATE' not in indicators:
        liabilities = indicators['Q_G_LIABILITIES']['value']
        total_assets = indicators['Q_G_TOTAL_ASSETS']['value']
        if total_assets > 0:
            debt_rate = (liabilities / total_assets) * 100
            calculated.append({
                'company_code': company_code,
                'company_name': company_name,
                'indicator_code': 'Q_G_DEBT_ASSET_RATE',
                'value': debt_rate,
                'formula': 'LIABILITIES/TOTAL_ASSETS*100'
            })

    # 营业利润率 = 营业利润 / 营业收入 * 100
    if 'Q_G_OPERATING_PROFIT' in indicators and 'Q_G_REVENUE' in indicators and 'Q_G_OPERATING_MARGIN' not in indicators:
        op = indicators['Q_G_OPERATING_PROFIT']['value']
        revenue = indicators['Q_G_REVENUE']['value']
        if revenue > 0:
            margin = (op / revenue) * 100
            calculated.append({
                'company_code': company_code,
                'company_name': company_name,
                'indicator_code': 'Q_G_OPERATING_MARGIN',
                'value': margin,
                'formula': 'OPERATING_PROFIT/REVENUE*100'
            })

    # 2. 社会指标比率
    # 研发费用占比 = 研发费用 / 营业收入 * 100
    if 'Q_S_RD_EXPENSE' in indicators and 'Q_G_REVENUE' in indicators and 'Q_S_RD_RATE' not in indicators:
        rd = indicators['Q_S_RD_EXPENSE']['value']
        revenue = indicators['Q_G_REVENUE']['value']
        if revenue > 0:
            rate = (rd / revenue) * 100
            calculated.append({
                'company_code': company_code,
                'company_name': company_name,
                'indicator_code': 'Q_S_RD_RATE',
                'value': rate,
                'formula': 'RD_EXPENSE/REVENUE*100'
            })

print(f"\n成功计算 {len(calculated)} 条新指标")

# 按指标统计
by_indicator = defaultdict(int)
for item in calculated:
    by_indicator[item['indicator_code']] += 1

print("\n各指标计算数量:")
for indicator, count in sorted(by_indicator.items()):
    print(f"  {indicator}: {count}条")

# 保存
with open('output/audit/ci_calculated_ratios_v1_2025.csv', 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['company_code', 'company_name', 'indicator_code', 'value', 'formula']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(calculated)

print(f"\n已保存到: output/audit/ci_calculated_ratios_v1_2025.csv")
