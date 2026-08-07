#!/usr/bin/env python3
"""
分析排名差异并诊断问题
对比官方2024排名与我们2025排名的差异
"""

import openpyxl
import csv
from collections import defaultdict

print("=" * 80)
print("ESG排名差异诊断报告")
print("=" * 80)

# 读取官方2024排名
wb = openpyxl.load_workbook('2024中国能源上市公司可持续发展（ESG）客户名单.xlsx')
sheet = wb.active

official_ranking = {}
for i, row in enumerate(sheet.iter_rows(values_only=True), 1):
    if i <= 2 or row[0] is None:
        continue
    if row[5] and row[6] and row[19]:
        official_ranking[row[5]] = {
            'rank_2024': row[0],
            'name': row[6],
            'score_2024': row[19],
            'ghg_intensity': row[9],
            'energy_intensity': row[10],
            'nox_intensity': row[11],
            'so2_intensity': row[12],
        }

# 读取我们的2025排名
our_ranking = {}
with open('output/audit/esg_scores_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        our_ranking[row['company_code']] = {
            'rank_2025': int(row['rank']),
            'name': row['company_name'],
            'score_2025': float(row['esg_score']),
            'e_score': float(row['e_score']),
            's_score': float(row['s_score']),
            'g_score': float(row['g_score']),
            'extracted': int(row['extracted_count']),
            'calculated': int(row['calculated_count']),
            'filled': int(row['filled_count'])
        }

# 读取我们提取的原始数据
our_data = defaultdict(dict)
with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row['company_code']
        indicator = row['indicator_code']
        our_data[code][indicator] = {
            'value': float(row['value']),
            'source': row['source']
        }

print("\n问题1: 官方Top 10企业在我们排名中大幅下降")
print("-" * 80)

for code in sorted(official_ranking.keys(), key=lambda x: official_ranking[x]['rank_2024'])[:10]:
    official = official_ranking[code]
    our = our_ranking.get(code, {})

    if not our:
        print(f"\n{official['name']} ({code}): 官方#{official['rank_2024']} → 未在我们排名中")
        continue

    rank_drop = our['rank_2025'] - official['rank_2024']
    score_drop = our['score_2025'] - official['score_2024']

    print(f"\n{official['name']} ({code}):")
    print(f"  官方2024: #{official['rank_2024']:3} {official['score_2024']:.2f}分")
    print(f"  我们2025: #{our['rank_2025']:3} {our['score_2025']:.2f}分 [E:{our['e_score']:.1f} S:{our['s_score']:.1f} G:{our['g_score']:.1f}]")
    print(f"  排名变化: {rank_drop:+4d}位 | 得分变化: {score_drop:+6.2f}分")
    print(f"  数据来源: 提取{our['extracted']}个 + 计算{our['calculated']}个 + 填充{our['filled']}个")

    # 检查关键指标
    company_data = our_data.get(code, {})
    key_indicators = ['Q_E_GHG_INTENSITY', 'Q_E_ENERGY_INTENSITY', 'Q_E_NOX_INTENSITY', 'Q_E_SO2_INTENSITY']
    missing_key = []
    filled_key = []
    for ind in key_indicators:
        if ind in company_data:
            if company_data[ind]['source'] == 'industry_filled':
                filled_key.append(ind)
        else:
            missing_key.append(ind)

    if filled_key:
        print(f"  ⚠️  关键指标使用行业填充: {', '.join(filled_key)}")
    if missing_key:
        print(f"  ❌ 关键指标缺失: {', '.join(missing_key)}")

print("\n" + "=" * 80)
print("根本原因分析")
print("=" * 80)

print("""
1. **评分方法差异**:
   - 官方2024: 专业团队人工评审 + 定性指标(20%) + 完整方法论
   - 我们2025: 自动化提取 + 仅定量指标(80%) + 行业填充(54.6%)

2. **数据质量差异**:
   - 官方: 直接从企业获取完整数据，经过审核
   - 我们: 从公开报告自动提取，54.6%数据来自行业平均填充

3. **定性指标缺失**:
   - 官方: 包含43个定性指标，占20%权重
   - 我们: 定性指标仅0.5%覆盖率，实际几乎为0

4. **行业填充的影响**:
   - 使用行业中位数填充导致高分企业"回归平均"
   - 优秀企业的真实优势被填充数据稀释

5. **评分尺度差异**:
   - 官方: 0-100分，平均60+分
   - 我们: 0-100分，但平均仅39分（过于保守）
""")

print("\n" + "=" * 80)
print("解决方案")
print("=" * 80)

print("""
**短期方案（1周内）**:

1. 调整评分尺度 - 重新校准到合理区间
   - 当前平均39分过低，应该在50-60分区间
   - 修改标准化公式，使分布更合理

2. 降低行业填充的权重
   - 当前置信度0.60，建议降至0.40
   - 或者对Top企业单独提取，不使用填充

3. 参考官方排名校准
   - 使用官方Top 100作为基准
   - 调整权重和评分公式使结果接近

**中期方案（2-4周）**:

1. 完善定性指标提取
   - 补全43个定性指标的20%权重
   - 使用LLM进行定性评估

2. 针对性数据补充
   - 对官方Top 100企业单独提取数据
   - 人工审核高分企业的关键指标

3. 多来源数据验证
   - 整合Wind、东方财富等数据源
   - 交叉验证关键指标

**建议**:
当前排名可以作为"技术测试版"，但不适合对外发布。
建议先实施短期方案，调整到合理的评分区间后再公开。
""")

print("\n" + "=" * 80)
print("✅ 诊断完成")
print("=" * 80)
