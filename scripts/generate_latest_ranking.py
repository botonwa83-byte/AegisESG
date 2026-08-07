#!/usr/bin/env python3
"""
生成新的排名数据（基于最新ESG评分）
更新到demo目录以供GitHub Pages使用
"""

import csv
import json
from pathlib import Path
from datetime import datetime

print("=" * 80)
print("生成最新ESG排名数据")
print("=" * 80)

ROOT = Path(__file__).resolve().parents[1]

# 读取我们最新的ESG评分
esg_scores = []
with open('output/audit/esg_scores_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        esg_scores.append({
            'rank': int(row['rank']),
            'company_code': row['company_code'],
            'company_name': row['company_name'],
            'esg_score': float(row['esg_score']),
            'quantitative_score': float(row['quantitative_score']),
            'qualitative_score': float(row['qualitative_score']),
            'e_score': float(row['e_score']),
            's_score': float(row['s_score']),
            'g_score': float(row['g_score']),
            'indicator_count': int(row['indicator_count']),
            'extracted_count': int(row['extracted_count']),
            'calculated_count': int(row['calculated_count']),
            'filled_count': int(row['filled_count'])
        })

print(f"\n已加载 {len(esg_scores)} 家企业ESG评分")

# 读取详细指标数据
indicator_data = {}
with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row['company_code']
        if code not in indicator_data:
            indicator_data[code] = {}
        indicator_data[code][row['indicator_code']] = {
            'value': float(row['value']),
            'source': row['source'],
            'confidence': float(row['confidence'])
        }

# 生成ranking.json（兼容现有格式）
ranking_json = []
for company in esg_scores:
    code = company['company_code']

    # 计算披露率
    total_indicators = 37  # 定量指标总数
    disclosed = company['extracted_count'] + company['calculated_count']
    disclosure_rate = (disclosed / total_indicators) * 100

    # 评级（简化版）
    score = company['esg_score']
    if score >= 60:
        grade = "A"
    elif score >= 50:
        grade = "BBB"
    elif score >= 40:
        grade = "BB"
    elif score >= 30:
        grade = "B"
    else:
        grade = "C"

    # 构建details（简化版，只包含关键信息）
    details = []
    if code in indicator_data:
        for ind_code, ind_data in indicator_data[code].items():
            details.append({
                'indicator_code': ind_code,
                'raw_value': ind_data['value'],
                'status': 'confirmed' if ind_data['source'] == 'extracted' else
                         ('calculated' if ind_data['source'] == 'calculated' else 'filled'),
                'source': ind_data['source'],
                'confidence': ind_data['confidence']
            })

    ranking_json.append({
        'rank': company['rank'],
        'company_code': code,
        'company_name': company['company_name'],
        'report_year': 2025,
        'quantitative_score': company['quantitative_score'],
        'qualitative_score': company['qualitative_score'],
        'total_score': company['esg_score'],
        'dimension_scores': {
            'E': company['e_score'],
            'S': company['s_score'],
            'G': company['g_score']
        },
        'disclosure_rate': round(disclosure_rate, 2),
        'grade': grade,
        'grade_reason': 'score_band',
        'data_quality': {
            'extracted': company['extracted_count'],
            'calculated': company['calculated_count'],
            'filled': company['filled_count']
        },
        'details': details[:10]  # 只保留前10个指标详情（节省空间）
    })

# 保存ranking.json
output_dir = ROOT / "output/demo/real_data_demo_2025"
output_dir.mkdir(parents=True, exist_ok=True)

ranking_json_path = output_dir / "ranking.json"
with open(ranking_json_path, 'w', encoding='utf-8') as f:
    json.dump(ranking_json, f, ensure_ascii=False, indent=2)

print(f"已保存: {ranking_json_path}")
print(f"  - 企业数: {len(ranking_json)}")
print(f"  - 文件大小: {ranking_json_path.stat().st_size / 1024:.1f} KB")

# 生成ranking_metadata.json
metadata = {
    'title': '2026年能源企业ESG评分排名（基于2025年数据）',
    'version': 'v1_2025_with_dimensions',
    'report_year': 2025,
    'generated_at': datetime.now().isoformat(),
    'total_companies': len(ranking_json),
    'methodology': 'DL/T 2971-2025',
    'quantitative_weight': 0.8,
    'qualitative_weight': 0.2,
    'data_coverage': {
        'quantitative': '99.7%',
        'qualitative': '0.5%'
    },
    'features': [
        'E/S/G维度评分',
        '37个定量指标',
        '三层数据获取策略',
        '行业分类和对标'
    ],
    'notes': [
        '本排名基于自动化数据提取和计算',
        '数据来源：企业2025年年报和ESG报告',
        '定量指标覆盖率99.7%',
        '定性指标尚在完善中',
        '评分方法符合DL/T 2971-2025标准'
    ]
}

metadata_path = output_dir / "ranking_metadata.json"
with open(metadata_path, 'w', encoding='utf-8') as f:
    json.dump(metadata, f, ensure_ascii=False, indent=2)

print(f"已保存: {metadata_path}")

# 生成简化的ranking.csv（用于表格展示）
ranking_csv_path = output_dir / "ranking.csv"
with open(ranking_csv_path, 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['rank', 'company_code', 'company_name', 'total_score',
                  'e_score', 's_score', 'g_score', 'disclosure_rate', 'grade']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in ranking_json:
        writer.writerow({
            'rank': row['rank'],
            'company_code': row['company_code'],
            'company_name': row['company_name'],
            'total_score': row['total_score'],
            'e_score': row['dimension_scores']['E'],
            's_score': row['dimension_scores']['S'],
            'g_score': row['dimension_scores']['G'],
            'disclosure_rate': row['disclosure_rate'],
            'grade': row['grade']
        })

print(f"已保存: {ranking_csv_path}")

print("\n" + "=" * 80)
print("✅ 排名数据生成完成")
print("=" * 80)
print(f"\n下一步：运行 scripts/build_github_demo.py 更新GitHub Pages")
