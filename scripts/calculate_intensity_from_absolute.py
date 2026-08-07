#!/usr/bin/env python3
"""
从绝对排放量和营业收入计算排放强度
用于补充那些只披露绝对量而没有披露强度的企业数据
"""

import csv
import re
import sys
from collections import defaultdict

def parse_revenue_from_evidence(evidence_text):
    """从证据文本中提取营业收入（元）"""
    # 多种格式匹配
    patterns = [
        r'营业收入[（(]元[)）]\s*([\d,]+\.?\d*)',  # 营业收入（元） 23,036,275,300.70
        r'(?:operating\s+)?revenue\s+([\d,]+\.?\d*)',  # revenue 90,964
        r'营业收入.*?([\d,]{10,}\.?\d*)',  # 营业收入...后面的大数字
        r'Revenue.*?([\d,]{10,}\.?\d*)',  # Revenue后面的大数字
    ]

    for pattern in patterns:
        match = re.search(pattern, evidence_text, re.IGNORECASE)
        if match:
            revenue_str = match.group(1).replace(',', '')
            try:
                value = float(revenue_str)
                # 合理性检查：营收应该在百万到万亿之间
                if 1000000 < value < 1000000000000:
                    return value
            except:
                continue

    return None

def read_candidates(csv_path):
    """读取提取结果"""
    data = defaultdict(lambda: defaultdict(dict))

    with open(csv_path, 'rb') as f:
        # 跳过header
        f.readline()

        for line in f:
            try:
                line_str = line.decode('utf-8', errors='ignore').strip()
                if not line_str:
                    continue

                parts = line_str.split(',')
                if len(parts) < 11:
                    continue

                company_code = parts[0].strip()
                company_name = parts[1].strip()
                indicator = parts[3].strip()
                value = parts[4].strip()
                evidence = ','.join(parts[9:]).strip('"')

                if not value or not company_code:
                    continue

                data[company_code][indicator] = {
                    'company_name': company_name,
                    'value': float(value) if value else None,
                    'evidence': evidence
                }

            except Exception as e:
                continue

    return data

def calculate_intensities(data):
    """计算强度指标"""
    # 指标映射：(绝对量指标, 强度指标, 转换系数)
    mappings = [
        ('Q_E_GHG_EMISSION', 'Q_E_GHG_INTENSITY', 1000, '千克/万元'),  # 吨→千克, 元→万元
        ('Q_E_ENERGY_CONSUMPTION', 'Q_E_ENERGY_INTENSITY', 1000, '千克/万元'),  # 吨标煤→千克, 元→万元
        ('Q_E_NOX_EMISSION', 'Q_E_NOX_INTENSITY', 100000, '克/万元'),  # 吨→克, 元→万元
        ('Q_E_SO2_EMISSION', 'Q_E_SO2_INTENSITY', 100000, '克/万元'),  # 吨→克, 元→万元
        ('Q_E_WATER_CONSUMPTION', 'Q_E_WATER_INTENSITY', 1000, '千克/万元'),  # 吨→千克, 元→万元
        ('Q_E_SOLID_WASTE_GENERATION', 'Q_E_SOLID_WASTE_INTENSITY', 1000, '千克/万元'),  # 吨→千克, 元→万元
        ('Q_E_WASTEWATER_DISCHARGE', 'Q_E_WASTEWATER_INTENSITY', 1000, '千克/万元'),  # 吨→千克, 元→万元
        ('Q_E_HAZ_WASTE_GENERATION', 'Q_E_HAZ_WASTE_INTENSITY', 1000, '千克/万元'),  # 吨→千克, 元→万元
        ('Q_E_PM_EMISSION', 'Q_E_PM_INTENSITY', 100000, '克/万元'),  # 吨→克, 元→万元
    ]

    calculated = []

    for company_code, indicators in data.items():
        company_name = indicators.get(list(indicators.keys())[0], {}).get('company_name', '')

        # 尝试从 Q_G_REVENUE_GROWTH 的证据中提取营业收入
        revenue = None
        if 'Q_G_REVENUE_GROWTH' in indicators:
            evidence = indicators['Q_G_REVENUE_GROWTH'].get('evidence', '')
            revenue = parse_revenue_from_evidence(evidence)

        if not revenue:
            continue

        revenue_wan = revenue / 10000  # 转换为万元

        for abs_indicator, intensity_indicator, factor, unit in mappings:
            # 如果有绝对量但没有强度，则计算
            if abs_indicator in indicators and intensity_indicator not in indicators:
                abs_value = indicators[abs_indicator]['value']
                if abs_value and abs_value > 0:
                    # 计算强度 = 绝对量 * 转换系数 / 营收(万元)
                    intensity = (abs_value * factor) / revenue_wan

                    calculated.append({
                        'company_code': company_code,
                        'company_name': company_name,
                        'indicator_code': intensity_indicator,
                        'value': intensity,
                        'source': 'calculated',
                        'abs_value': abs_value,
                        'abs_indicator': abs_indicator,
                        'revenue': revenue,
                        'unit': unit
                    })

    return calculated

def main():
    input_csv = 'output/audit/ci_incremental_candidates_v1_2025.csv'
    output_csv = 'output/audit/ci_calculated_intensities_v1_2025.csv'

    print(f"读取提取结果: {input_csv}")
    data = read_candidates(input_csv)
    print(f"已加载 {len(data)} 家企业的数据")

    print("\n计算强度指标...")
    calculated = calculate_intensities(data)

    print(f"\n成功计算 {len(calculated)} 条强度记录")

    # 按指标统计
    by_indicator = defaultdict(int)
    for item in calculated:
        by_indicator[item['indicator_code']] += 1

    print("\n各指标计算数量:")
    for indicator, count in sorted(by_indicator.items()):
        print(f"  {indicator}: {count} 条")

    # 保存结果
    print(f"\n保存到: {output_csv}")
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['company_code', 'company_name', 'indicator_code', 'value',
                     'source', 'abs_indicator', 'abs_value', 'revenue', 'unit']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(calculated)

    print("完成！")

if __name__ == '__main__':
    main()
