#!/usr/bin/env python3
"""分析提取结果 - 不依赖pandas"""

import csv
from collections import Counter, defaultdict

print("=" * 70)
print("ESG数据提取结果分析")
print("=" * 70)

# 读取CSV
records = []
with open("output/audit/ci_incremental_candidates_v1_2025.csv", 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        records.append(row)

print(f"\n📊 总体统计")
print(f"{'='*70}")
print(f"总提取记录数: {len(records):,}")

companies = set(r['company_code'] for r in records)
indicators = set(r['indicator_code'] for r in records)

print(f"覆盖企业数: {len(companies):,}")
print(f"覆盖指标数: {len(indicators)}")

# 按指标统计
print(f"\n📈 指标覆盖率Top 30")
print(f"{'='*70}")
indicator_counts = Counter(r['indicator_code'] for r in records)

for indicator, count in indicator_counts.most_common(30):
    # 统计该指标覆盖的企业数
    indicator_companies = set(r['company_code'] for r in records if r['indicator_code'] == indicator)
    coverage_pct = len(indicator_companies) / len(companies) * 100
    print(f"{indicator:40s}: {count:5,} 条记录, {len(indicator_companies):4,}家企业 ({coverage_pct:5.1f}%)")

# 关键指标统计
key_indicators = [
    "Q_S_SAFETY_INVEST_RATE",
    "Q_E_SOLID_WASTE_INTENSITY",
    "Q_E_ENERGY_INTENSITY",
    "Q_E_WATER_INTENSITY",
    "Q_E_GHG_INTENSITY",
    "Q_E_SO2_INTENSITY",
    "Q_E_NOX_INTENSITY",
]

print(f"\n🎯 7个关键指标提取情况")
print(f"{'='*70}")
print(f"{'指标代码':<40s} {'记录数':>10s} {'覆盖企业':>10s} {'覆盖率':>10s}")
print(f"{'-'*70}")

for indicator in key_indicators:
    indicator_records = [r for r in records if r['indicator_code'] == indicator]
    record_count = len(indicator_records)
    indicator_companies = set(r['company_code'] for r in indicator_records)
    company_count = len(indicator_companies)
    coverage_rate = (company_count / len(companies) * 100) if len(companies) > 0 else 0
    missing_rate = 100 - coverage_rate

    print(f"{indicator:<40s} {record_count:>10,} {company_count:>10,} {coverage_rate:>9.1f}% (缺失{missing_rate:.1f}%)")

# 按类型分组统计
print(f"\n📊 按指标类型分组")
print(f"{'='*70}")

env_indicators = [i for i in indicators if i.startswith('Q_E_')]
social_indicators = [i for i in indicators if i.startswith('Q_S_')]
gov_indicators = [i for i in indicators if i.startswith('Q_G_')]

env_records = [r for r in records if r['indicator_code'].startswith('Q_E_')]
social_records = [r for r in records if r['indicator_code'].startswith('Q_S_')]
gov_records = [r for r in records if r['indicator_code'].startswith('Q_G_')]

print(f"环境指标 (E): {len(env_indicators)}个指标, {len(env_records):,}条记录")
print(f"社会指标 (S): {len(social_indicators)}个指标, {len(social_records):,}条记录")
print(f"治理指标 (G): {len(gov_indicators)}个指标, {len(gov_records):,}条记录")

# 置信度分布
print(f"\n🔍 置信度分布")
print(f"{'='*70}")

confidence_bins = {
    '0.9-1.0': 0,
    '0.8-0.9': 0,
    '0.7-0.8': 0,
    '0.5-0.7': 0,
    '0-0.5': 0,
}

for r in records:
    try:
        conf = float(r['confidence'])
        if conf >= 0.9:
            confidence_bins['0.9-1.0'] += 1
        elif conf >= 0.8:
            confidence_bins['0.8-0.9'] += 1
        elif conf >= 0.7:
            confidence_bins['0.7-0.8'] += 1
        elif conf >= 0.5:
            confidence_bins['0.5-0.7'] += 1
        else:
            confidence_bins['0-0.5'] += 1
    except:
        pass

for bin_name, count in sorted(confidence_bins.items(), reverse=True):
    pct = count / len(records) * 100
    print(f"{bin_name:10s}: {count:6,} ({pct:5.1f}%)")

# 按企业统计覆盖率
print(f"\n🏢 企业指标覆盖率分布")
print(f"{'='*70}")

company_indicator_counts = defaultdict(set)
for r in records:
    company_indicator_counts[r['company_code']].add(r['indicator_code'])

indicator_counts_list = [len(indicators) for indicators in company_indicator_counts.values()]
avg_indicators = sum(indicator_counts_list) / len(indicator_counts_list) if indicator_counts_list else 0

print(f"平均每企业指标数: {avg_indicators:.1f}")
print(f"最大值: {max(indicator_counts_list) if indicator_counts_list else 0}")
print(f"最小值: {min(indicator_counts_list) if indicator_counts_list else 0}")

# 覆盖率分布
coverage_dist = Counter(indicator_counts_list)
print(f"\n指标数分布（前10）:")
for num_indicators, num_companies in sorted(coverage_dist.items())[:10]:
    print(f"  {num_indicators:2d}个指标: {num_companies:4d}家企业")

print(f"\n{'='*70}")
print("分析完成！")
print(f"{'='*70}")
