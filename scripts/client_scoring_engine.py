#!/usr/bin/env python3
"""
客户ESG评分引擎 - 严格按照2025年报告评分方法
使用正态分布函数计算指标得分
"""

import csv
import json
import math
from pathlib import Path
from collections import defaultdict

print("=" * 80)
print("客户ESG评分引擎 - 正态分布法")
print("=" * 80)

# ========== 客户定义的37个定量指标 ==========
QUANTITATIVE_INDICATORS = {
    # 环境保护 (12个指标)
    'Q_E_GHG_INTENSITY': {'weight': 9.00, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_GHG_REDUCTION_RATE': {'weight': 4.50, 'prefer': 'higher', 'type': 'environmental'},
    'Q_E_ENERGY_INTENSITY': {'weight': 6.45, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_CLEAN_ENERGY_INTENSITY': {'weight': 2.55, 'prefer': 'higher', 'type': 'environmental'},
    'Q_E_NOX_INTENSITY': {'weight': 2.48, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_SO2_INTENSITY': {'weight': 2.48, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_PM_INTENSITY': {'weight': 2.48, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_WASTEWATER_INTENSITY': {'weight': 2.48, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_WATER_INTENSITY': {'weight': 2.48, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_RECYCLED_WATER_RATE': {'weight': 2.46, 'prefer': 'higher', 'type': 'environmental'},
    'Q_E_SOLID_WASTE_INTENSITY': {'weight': 3.82, 'prefer': 'lower', 'type': 'environmental'},
    'Q_E_HAZARDOUS_WASTE_INTENSITY': {'weight': 3.82, 'prefer': 'lower', 'type': 'environmental'},

    # 社会责任 (12个指标)
    'Q_S_SAFETY_INVEST_RATE': {'weight': 2.50, 'prefer': 'higher', 'type': 'social'},
    'Q_S_ENV_INVEST_RATE': {'weight': 1.50, 'prefer': 'higher', 'type': 'social'},
    'Q_S_RD_RATE': {'weight': 3.00, 'prefer': 'higher', 'type': 'social'},
    'Q_S_CHARITY_RATE': {'weight': 3.00, 'prefer': 'higher', 'type': 'social'},
    'Q_S_EMPLOYEE_SALARY': {'weight': 2.80, 'prefer': 'higher', 'type': 'social'},
    'Q_S_FEMALE_EMPLOYEE_RATE': {'weight': 0.75, 'prefer': 'higher', 'type': 'social'},
    'Q_S_FEMALE_MANAGER_RATE': {'weight': 0.75, 'prefer': 'higher', 'type': 'social'},
    'Q_S_UNIONIZATION_RATE': {'weight': 0.75, 'prefer': 'higher', 'type': 'social'},
    'Q_S_EMPLOYEE_TURNOVER_RATE': {'weight': 0.75, 'prefer': 'lower', 'type': 'social'},
    'Q_S_TRAINING_COVERAGE': {'weight': 0.90, 'prefer': 'higher', 'type': 'social'},
    'Q_S_TRAINING_HOURS': {'weight': 0.90, 'prefer': 'higher', 'type': 'social'},
    'Q_S_EMPLOYEE_SATISFACTION': {'weight': 0.90, 'prefer': 'higher', 'type': 'social'},

    # 公司治理 (13个指标)
    'Q_G_DIVIDEND_PER_SHARE': {'weight': 2.80, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_ROE': {'weight': 2.80, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_ROTA': {'weight': 2.80, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_EBITDA_MARGIN': {'weight': 1.40, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_OPERATING_CASH_RATE': {'weight': 1.40, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_COST_REVENUE_RATIO': {'weight': 1.40, 'prefer': 'lower', 'type': 'governance'},
    'Q_G_ASSET_TURNOVER': {'weight': 2.10, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_AR_TURNOVER': {'weight': 2.10, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_CURRENT_ASSET_TURNOVER': {'weight': 2.10, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_TWO_FUNDS_RATIO': {'weight': 2.10, 'prefer': 'lower', 'type': 'governance'},
    'Q_G_DEBT_RATIO': {'weight': 2.80, 'prefer': 'bilateral', 'type': 'governance'},  # 双向指标
    'Q_G_EBITDA_INTEREST_COVER': {'weight': 2.80, 'prefer': 'higher', 'type': 'governance'},
    'Q_G_QUICK_RATIO': {'weight': 2.10, 'prefer': 'higher', 'type': 'governance'},
}

def calculate_normal_distribution_score(value, all_values, prefer, weight):
    """
    使用正态分布函数计算指标得分

    参数:
        value: 企业该指标的值
        all_values: 所有企业该指标的值列表
        prefer: 'higher'(正向) / 'lower'(负向) / 'bilateral'(双向)
        weight: 指标权重

    返回:
        该指标的加权得分
    """
    if not all_values or value is None:
        return 0.0

    # 计算均值和标准差
    mean = sum(all_values) / len(all_values)
    if len(all_values) > 1:
        variance = sum((x - mean) ** 2 for x in all_values) / (len(all_values) - 1)
        std = math.sqrt(variance)
    else:
        std = 0

    if std == 0:
        return weight  # 所有值相同，给满分

    # 计算Z分数
    z_score = (value - mean) / std

    if prefer == 'higher':
        # 正向指标：越大越好
        # 使用累积分布函数CDF，将Z分数转为0-1之间的概率
        # 然后乘以权重
        if z_score >= 3:
            normalized = 1.0
        elif z_score <= -3:
            normalized = 0.0
        else:
            # 使用误差函数erf近似CDF
            normalized = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
        score = normalized * weight

    elif prefer == 'lower':
        # 负向指标：越小越好
        if z_score <= -3:
            normalized = 1.0
        elif z_score >= 3:
            normalized = 0.0
        else:
            normalized = 0.5 * (1 - math.erf(z_score / math.sqrt(2)))
        score = normalized * weight

    elif prefer == 'bilateral':
        # 双向指标：中间最优（如资产负债率）
        # 以均值为最优点，向两侧递减
        abs_z = abs(z_score)
        if abs_z >= 3:
            normalized = 0.0
        else:
            # 使用正态分布概率密度函数
            normalized = math.exp(-0.5 * z_score ** 2) / math.sqrt(2 * math.pi)
            # 标准化到0-1
            normalized = normalized / (1 / math.sqrt(2 * math.pi))
        score = normalized * weight

    else:
        score = 0.0

    return score

def calculate_company_quantitative_score(company_data, all_companies_data):
    """
    计算单个企业的定量总分

    参数:
        company_data: 该企业的指标数据字典
        all_companies_data: 所有企业的指标数据（用于正态分布计算）

    返回:
        定量总分（0-80分）
    """
    total_score = 0.0
    indicator_scores = {}

    for indicator_code, config in QUANTITATIVE_INDICATORS.items():
        value = company_data.get(indicator_code)

        if value is not None and indicator_code in all_companies_data:
            all_values = all_companies_data[indicator_code]
            score = calculate_normal_distribution_score(
                value, all_values, config['prefer'], config['weight']
            )
            indicator_scores[indicator_code] = score
            total_score += score
        else:
            indicator_scores[indicator_code] = 0.0

    return total_score, indicator_scores

# ========== 主流程 ==========
def main():
    # 读取企业数据
    print("\n加载企业指标数据...")
    companies = {}
    all_indicators_values = defaultdict(list)

    with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row['company_code']
            indicator = row['indicator_code']

            # 只处理客户定义的37个指标
            if indicator in QUANTITATIVE_INDICATORS:
                value = float(row['value'])

                if code not in companies:
                    companies[code] = {'company_code': code}

                companies[code][indicator] = value
                all_indicators_values[indicator].append(value)

    print(f"  已加载 {len(companies)} 家企业")
    print(f"  覆盖 {len(all_indicators_values)} 个指标")

    # 计算每个企业的得分
    print("\n计算企业得分（正态分布法）...")
    results = []

    for code, company_data in companies.items():
        quantitative_score, indicator_scores = calculate_company_quantitative_score(
            company_data, all_indicators_values
        )

        # 定性得分暂时设为0（需要后续实现）
        qualitative_score = 0.0

        # 总分 = 定量80% + 定性20%（但定性分满分是20，所以直接相加）
        total_score = quantitative_score + qualitative_score

        results.append({
            'company_code': code,
            'quantitative_score': round(quantitative_score, 2),
            'qualitative_score': round(qualitative_score, 2),
            'total_score': round(total_score, 2),
            'indicator_scores': indicator_scores
        })

    # 排序
    results.sort(key=lambda x: x['total_score'], reverse=True)

    # 添加排名
    for rank, result in enumerate(results, 1):
        result['rank'] = rank

    # 保存结果
    output_file = 'output/audit/client_method_esg_scores_2025.csv'
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['rank', 'company_code', 'total_score', 'quantitative_score', 'qualitative_score']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({
                'rank': result['rank'],
                'company_code': result['company_code'],
                'total_score': result['total_score'],
                'quantitative_score': result['quantitative_score'],
                'qualitative_score': result['qualitative_score']
            })

    print(f"\n已保存到: {output_file}")
    print(f"\nTop 10企业（正态分布法）:")
    for result in results[:10]:
        print(f"  {result['rank']}. {result['company_code']} - {result['total_score']}分 " +
              f"(定量:{result['quantitative_score']:.2f} + 定性:{result['qualitative_score']:.2f})")

    print("\n" + "=" * 80)
    print("✅ 客户评分方法已实现（定量部分）")
    print("=" * 80)
    print("\n注意：定性指标（20分）尚未实现，当前仅为定量得分")

if __name__ == '__main__':
    main()
