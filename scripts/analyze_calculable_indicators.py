#!/usr/bin/env python3
"""
根据方法论定义的计算公式，从已有数据推导缺失指标
目标：将数据覆盖度提高到90%以上
"""

import json
import csv
from collections import defaultdict

# 读取方法论
with open('data/methodologies/energy_esg_2025_research_sasac.json', 'r', encoding='utf-8') as f:
    methodology = json.load(f)

# 提取可计算的指标公式
calculable_indicators = {}
for ind in methodology['indicators']:
    if ind['kind'] == 'quantitative' and 'formula' in ind:
        calculable_indicators[ind['code']] = {
            'formula': ind['formula'],
            'name': ind['name'],
            'unit': ind['unit']
        }

print(f"可计算的定量指标: {len(calculable_indicators)}")
print("\n关键计算公式:")
for code, info in list(calculable_indicators.items())[:10]:
    print(f"  {code}: {info['formula']}")

# 分析公式依赖关系
formula_deps = {
    # 强度指标 = 绝对量 / 营业收入
    'Q_E_GHG_INTENSITY': ['Q_E_GHG_EMISSION', 'Q_G_REVENUE'],
    'Q_E_ENERGY_INTENSITY': ['Q_E_ENERGY_CONSUMPTION', 'Q_G_REVENUE'],
    'Q_E_NOX_INTENSITY': ['Q_E_NOX_EMISSION', 'Q_G_REVENUE'],
    'Q_E_SO2_INTENSITY': ['Q_E_SO2_EMISSION', 'Q_G_REVENUE'],
    'Q_E_PM_INTENSITY': ['Q_E_PM_EMISSION', 'Q_G_REVENUE'],
    'Q_E_WASTEWATER_INTENSITY': ['Q_E_WASTEWATER_DISCHARGE', 'Q_G_REVENUE'],
    'Q_E_WATER_INTENSITY': ['Q_E_WATER_CONSUMPTION', 'Q_G_REVENUE'],
    'Q_E_SOLID_WASTE_INTENSITY': ['Q_E_SOLID_WASTE_GENERATION', 'Q_G_REVENUE'],
    'Q_E_HAZ_WASTE_INTENSITY': ['Q_E_HAZ_WASTE_GENERATION', 'Q_G_REVENUE'],
    'Q_E_CLEAN_ENERGY_INTENSITY': ['Q_E_CLEAN_ENERGY_CONSUMPTION', 'Q_G_REVENUE'],

    # 比率指标 = 部分 / 总量 * 100
    'Q_E_GHG_REDUCTION_RATE': ['Q_E_GHG_REDUCTION', 'Q_E_GHG_EMISSION'],
    'Q_E_ALTERNATIVE_WATER_RATE': ['Q_E_ALTERNATIVE_WATER', 'Q_E_WATER_CONSUMPTION'],
    'Q_S_SAFETY_INVEST_RATE': ['Q_S_SAFETY_INVEST', 'Q_G_REVENUE'],
    'Q_S_ENV_INVEST_RATE': ['Q_S_ENV_INVEST', 'Q_G_REVENUE'],
    'Q_S_RD_RATE': ['Q_S_RD_EXPENSE', 'Q_G_REVENUE'],
    'Q_S_DONATION_RATE': ['Q_S_DONATION', 'Q_G_REVENUE'],

    # 人均指标 = 总量 / 员工数
    'Q_S_PAY_PER_EMPLOYEE': ['Q_S_PAY_TOTAL', 'Q_S_EMPLOYEE_COUNT'],
    'Q_S_BENEFIT_PER_EMPLOYEE': ['Q_S_BENEFIT_TOTAL', 'Q_S_EMPLOYEE_COUNT'],
    'Q_S_EDU_PER_EMPLOYEE': ['Q_S_EDU_TOTAL', 'Q_S_EMPLOYEE_COUNT'],

    # 财务比率
    'Q_G_ROE': ['Q_G_NET_PROFIT', 'Q_G_NET_ASSETS'],
    'Q_G_ROA': ['Q_G_EBIT', 'Q_G_TOTAL_ASSETS'],
    'Q_G_OPERATING_MARGIN': ['Q_G_OPERATING_PROFIT', 'Q_G_REVENUE'],
    'Q_G_EBITDA_MARGIN': ['Q_G_EBITDA', 'Q_G_REVENUE'],
    'Q_G_CASH_REALIZATION': ['Q_G_OPERATING_CASH', 'Q_G_REVENUE'],
    'Q_G_COST_REVENUE_RATE': ['Q_G_COST_TOTAL', 'Q_G_REVENUE'],
    'Q_G_ASSET_TURNOVER': ['Q_G_REVENUE', 'Q_G_TOTAL_ASSETS'],
    'Q_G_AR_TURNOVER': ['Q_G_REVENUE', 'Q_G_AR_AVERAGE'],
    'Q_G_CURRENT_ASSET_TURNOVER': ['Q_G_REVENUE', 'Q_G_CURRENT_ASSETS'],
    'Q_G_TWO_FUNDS_RATE': ['Q_G_AR', 'Q_G_INVENTORY', 'Q_G_CURRENT_ASSETS'],
    'Q_G_DEBT_ASSET_RATE': ['Q_G_LIABILITIES', 'Q_G_TOTAL_ASSETS'],
    'Q_G_EBITDA_INTEREST': ['Q_G_EBITDA', 'Q_G_INTEREST'],
    'Q_G_QUICK_RATIO': ['Q_G_QUICK_ASSETS', 'Q_G_CURRENT_LIABILITIES'],
    'Q_G_CASH_CURRENT_LIABILITY': ['Q_G_OPERATING_CASH', 'Q_G_CURRENT_LIABILITIES'],
    'Q_G_REVENUE_GROWTH': ['Q_G_REVENUE_CURRENT', 'Q_G_REVENUE_LAST'],
    'Q_G_OPERATING_PROFIT_GROWTH': ['Q_G_OPERATING_PROFIT_CURRENT', 'Q_G_OPERATING_PROFIT_LAST'],
    'Q_G_CAPITAL_ACCUMULATION': ['Q_G_EQUITY_END', 'Q_G_EQUITY_BEGIN'],
}

print(f"\n可通过计算补充的指标: {len(formula_deps)}")

# 读取现有提取数据
print("\n读取提取数据...")
data = defaultdict(lambda: defaultdict(dict))

try:
    with open('output/audit/ci_incremental_candidates_v1_2025.csv', 'rb') as f:
        f.readline()  # skip header
        for line in f:
            try:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if not line_str:
                    continue
                parts = line_str.split(',')
                if len(parts) >= 5:
                    company_code = parts[0].strip()
                    indicator = parts[3].strip()
                    value_str = parts[4].strip()
                    if value_str:
                        data[company_code][indicator] = float(value_str)
            except:
                continue
except Exception as e:
    print(f"读取错误: {e}")

print(f"已加载 {len(data)} 家企业的数据")

# 统计可补充的指标数量
can_calculate = defaultdict(int)
for company, indicators in data.items():
    for target, deps in formula_deps.items():
        if target not in indicators:  # 目标指标缺失
            # 检查依赖指标是否都存在
            if all(dep in indicators for dep in deps):
                can_calculate[target] += 1

print("\n可补充的指标统计（前20个）:")
for indicator, count in sorted(can_calculate.items(), key=lambda x: -x[1])[:20]:
    print(f"  {indicator}: +{count}条")

total_can_add = sum(can_calculate.values())
print(f"\n总计可新增: {total_can_add}条记录")
