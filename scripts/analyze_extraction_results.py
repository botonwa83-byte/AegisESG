#!/usr/bin/env python3
"""分析提取结果，对比优化前后效果"""

import pandas as pd
from collections import Counter

print("=" * 70)
print("ESG数据提取结果分析")
print("=" * 70)

# 读取提取结果
df = pd.read_csv("output/audit/ci_incremental_candidates_v1_2025.csv")

print(f"\n📊 总体统计")
print(f"{'='*70}")
print(f"总提取记录数: {len(df):,}")
print(f"覆盖企业数: {df['company_code'].nunique():,}")
print(f"覆盖指标数: {df['indicator_code'].nunique()}")

# 按指标统计
print(f"\n📈 指标覆盖率Top 20")
print(f"{'='*70}")
indicator_counts = df['indicator_code'].value_counts().head(20)
for indicator, count in indicator_counts.items():
    print(f"{indicator:40s}: {count:5,} 条记录")

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
print(f"{'指标代码':<40s} {'记录数':>10s} {'覆盖企业':>10s}")
print(f"{'-'*70}")

total_companies = df['company_code'].nunique()
for indicator in key_indicators:
    indicator_df = df[df['indicator_code'] == indicator]
    record_count = len(indicator_df)
    company_count = indicator_df['company_code'].nunique()
    coverage_rate = (company_count / total_companies * 100) if total_companies > 0 else 0

    print(f"{indicator:<40s} {record_count:>10,} {company_count:>10,} ({coverage_rate:5.1f}%)")

# 置信度分布
print(f"\n🔍 置信度分布")
print(f"{'='*70}")
confidence_bins = [0, 0.5, 0.7, 0.8, 0.9, 1.0]
confidence_labels = ['0-0.5', '0.5-0.7', '0.7-0.8', '0.8-0.9', '0.9-1.0']
df['confidence_bin'] = pd.cut(df['confidence'], bins=confidence_bins, labels=confidence_labels)
print(df['confidence_bin'].value_counts().sort_index())

# 数据来源统计
if 'extraction_method' in df.columns:
    print(f"\n📋 提取方法分布")
    print(f"{'='*70}")
    print(df['extraction_method'].value_counts())

# 按企业统计覆盖率
print(f"\n🏢 企业指标覆盖率分布")
print(f"{'='*70}")
company_indicator_counts = df.groupby('company_code')['indicator_code'].nunique()
print(f"平均每企业指标数: {company_indicator_counts.mean():.1f}")
print(f"中位数: {company_indicator_counts.median():.1f}")
print(f"最大值: {company_indicator_counts.max()}")
print(f"最小值: {company_indicator_counts.min()}")

# 覆盖率分布
coverage_dist = company_indicator_counts.value_counts().sort_index()
print(f"\n指标数分布（前10）:")
for num_indicators, num_companies in coverage_dist.head(10).items():
    print(f"  {num_indicators:2d}个指标: {num_companies:4d}家企业")

print(f"\n{'='*70}")
print("分析完成！")
print(f"{'='*70}")
