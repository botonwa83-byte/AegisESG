#!/usr/bin/env python3
"""
计算企业ESG评分的同比(YoY)变化趋势
"""

import csv
import json
from collections import defaultdict

print("=" * 70)
print("ESG评分同比(YoY)趋势分析")
print("=" * 70)

# 读取2024年历史数据
print("\n读取2024年历史数据...")
hist_companies = {}
with open('data/reference/2024_energy_company_registry.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row['stock_code']
        hist_companies[code] = {
            'name': row['company_name'],
            'score_2024': float(row['historical_esg_score']),
            'rank_2024': int(row['historical_rank'])
        }

print(f"  2024年企业数: {len(hist_companies)}")

# 读取2025年数据
print("读取2025年当前数据...")
curr_companies = {}
with open('output/audit/esg_scores_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row['company_code']
        curr_companies[code] = {
            'name': row['company_name'],
            'score_2025': float(row['esg_score']),
            'e_score': float(row['e_score']),
            's_score': float(row['s_score']),
            'g_score': float(row['g_score']),
            'rank_2025': int(row['rank']),
            'extracted_count': int(row['extracted_count']),
            'calculated_count': int(row['calculated_count']),
            'filled_count': int(row['filled_count'])
        }

print(f"  2025年企业数: {len(curr_companies)}")

# 匹配企业
matched = set(hist_companies.keys()) & set(curr_companies.keys())
print(f"\n匹配企业数: {len(matched)} (匹配率: {len(matched)/len(hist_companies)*100:.1f}%)")

# 计算YoY指标
yoy_results = []
for code in matched:
    hist = hist_companies[code]
    curr = curr_companies[code]

    score_change = curr['score_2025'] - hist['score_2024']
    score_change_pct = (score_change / hist['score_2024'] * 100) if hist['score_2024'] > 0 else 0
    rank_change = hist['rank_2024'] - curr['rank_2025']  # 正数表示排名上升

    yoy_results.append({
        'company_code': code,
        'company_name': curr['name'],
        'score_2024': hist['score_2024'],
        'score_2025': curr['score_2025'],
        'score_change': score_change,
        'score_change_pct': score_change_pct,
        'rank_2024': hist['rank_2024'],
        'rank_2025': curr['rank_2025'],
        'rank_change': rank_change,
        'e_score': curr['e_score'],
        's_score': curr['s_score'],
        'g_score': curr['g_score'],
        'extracted_count': curr['extracted_count'],
        'calculated_count': curr['calculated_count'],
        'filled_count': curr['filled_count']
    })

# 保存YoY结果
output_file = 'output/audit/esg_yoy_trends_v1_2024_2025.csv'
with open(output_file, 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['company_code', 'company_name',
                  'score_2024', 'score_2025', 'score_change', 'score_change_pct',
                  'rank_2024', 'rank_2025', 'rank_change',
                  'e_score', 's_score', 'g_score',
                  'extracted_count', 'calculated_count', 'filled_count']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(yoy_results)

print(f"已保存到: {output_file}")

# 统计分析
print("\n" + "=" * 70)
print("YoY趋势统计")
print("=" * 70)

score_changes = [r['score_change'] for r in yoy_results]
score_change_pcts = [r['score_change_pct'] for r in yoy_results]

improved = [r for r in yoy_results if r['score_change'] > 0]
declined = [r for r in yoy_results if r['score_change'] < 0]
unchanged = [r for r in yoy_results if r['score_change'] == 0]

print(f"\n得分变化分布:")
print(f"  改善企业: {len(improved)} ({len(improved)/len(yoy_results)*100:.1f}%)")
print(f"  下降企业: {len(declined)} ({len(declined)/len(yoy_results)*100:.1f}%)")
print(f"  持平企业: {len(unchanged)} ({len(unchanged)/len(yoy_results)*100:.1f}%)")

print(f"\n得分变化幅度:")
print(f"  平均变化: {sum(score_changes)/len(score_changes):+.2f}分")
print(f"  最大提升: {max(score_changes):+.2f}分")
print(f"  最大下降: {min(score_changes):+.2f}分")
print(f"  平均变化率: {sum(score_change_pcts)/len(score_change_pcts):+.1f}%")

# Top改善企业
print(f"\n" + "=" * 70)
print("Top 10 改善最大企业")
print("=" * 70)
top_improved = sorted(yoy_results, key=lambda x: x['score_change'], reverse=True)[:10]
for i, company in enumerate(top_improved, 1):
    print(f"{i:2d}. {company['company_name'][:20]:<20} " +
          f"{company['score_2024']:5.2f} -> {company['score_2025']:5.2f} " +
          f"({company['score_change']:+6.2f}, {company['score_change_pct']:+6.1f}%) " +
          f"排名:{company['rank_change']:+4d}")

# Top下降企业
print(f"\n" + "=" * 70)
print("Top 10 下降最大企业")
print("=" * 70)
top_declined = sorted(yoy_results, key=lambda x: x['score_change'])[:10]
for i, company in enumerate(top_declined, 1):
    print(f"{i:2d}. {company['company_name'][:20]:<20} " +
          f"{company['score_2024']:5.2f} -> {company['score_2025']:5.2f} " +
          f"({company['score_change']:+6.2f}, {company['score_change_pct']:+6.1f}%) " +
          f"排名:{company['rank_change']:+4d}")

# 注意事项
print("\n" + "=" * 70)
print("⚠️  重要说明")
print("=" * 70)
print("""
注意：2024年和2025年的ESG评分可能使用了不同的方法论和数据源，
因此YoY变化较大可能反映的是：
1. 评分方法的差异（2024年可能是第三方报告，2025年是本系统计算）
2. 数据覆盖率的提升（2025年覆盖率达99.7%）
3. 企业实际ESG表现的变化

建议使用YoY趋势作为参考，而非绝对比较依据。
更准确的趋势分析需要使用相同方法论计算的多年数据。
""")

print("=" * 70)
print("✅ YoY趋势分析完成")
print("=" * 70)
