#!/usr/bin/env python3
"""
定性指标提取框架
基于文本分析和关键词匹配识别企业ESG定性披露
"""

import csv
import json
import re
from pathlib import Path
from collections import defaultdict

print("=" * 70)
print("定性指标提取引擎 - DL/T 2971-2025")
print("=" * 70)

# 读取方法论
with open('data/methodologies/energy_esg_2025_research_sasac.json', 'r', encoding='utf-8') as f:
    methodology = json.load(f)

# 获取定性指标
qualitative_indicators = [ind for ind in methodology['indicators'] if ind['kind'] == 'qualitative']
print(f"\n定性指标数量: {len(qualitative_indicators)}")
print(f"定性指标总权重: {sum(ind['weight'] for ind in qualitative_indicators):.2f}")

# 定义关键词规则（基于指标名称的简化匹配）
# 实际应用中需要更复杂的NLP和语义分析
KEYWORD_RULES = {
    'Q_E_ENV_SYSTEM': ['环境管理体系', 'ISO14001', '环境认证', '环保体系'],
    'Q_E_EMERGENCY': ['应急预案', '应急演练', '应急管理', '突发环境事件'],
    'Q_E_ENV_TRAINING': ['环保培训', '环境教育', '环保意识'],
    'Q_E_COMPLIANCE': ['环保处罚', '环境违法', '环境合规', '守法'],
    'Q_E_ENV_IMPACT': ['环境影响评价', '环评', '环境监测'],
    'Q_S_EMPLOYEE_RIGHTS': ['劳动合同', '社会保险', '员工权益'],
    'Q_S_HEALTH_SAFETY': ['职业健康', '安全生产', '工伤'],
    'Q_S_DIVERSITY': ['多元化', '女性管理层', '性别平等'],
    'Q_G_GOVERNANCE': ['公司治理', '内部控制', '三会运作'],
    'Q_G_INTEGRITY': ['反腐败', '廉洁', '合规经营'],
}

# 评分规则（简化版：检测到关键词给予基础分）
def score_qualitative_indicator(text_content, indicator_code, keywords):
    """
    对定性指标进行评分（0-100分）
    基于关键词匹配和文本长度
    """
    if not text_content:
        return 0.0

    # 检测关键词出现次数
    matches = 0
    for keyword in keywords:
        matches += text_content.count(keyword)

    if matches == 0:
        return 0.0

    # 基础分：检测到关键词给50分
    base_score = 50.0

    # 加分：根据匹配次数
    frequency_bonus = min(matches * 5, 30)  # 最多+30分

    # 加分：根据相关文本长度（简化）
    length_bonus = min(len(text_content) / 100, 20)  # 最多+20分

    total_score = base_score + frequency_bonus + length_bonus
    return min(total_score, 100.0)

# 读取企业名称映射
print("\n加载企业名称映射...")
company_names = {}
try:
    with open('output/audit/esg_scores_v1_2025.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            company_names[row['company_code']] = row['company_name']
    print(f"  已加载{len(company_names)}家企业名称")
except Exception as e:
    print(f"  警告: 无法加载企业名称: {e}")

# 读取企业文本数据
print("\n加载企业文本数据...")
company_texts = {}
text_dir = Path('data/text')

if text_dir.exists():
    # 文本按公司代码组织：data/text/{company_code}/2025/*.txt
    company_dirs = sorted([d for d in text_dir.iterdir() if d.is_dir()])[:50]  # 先处理50家企业
    print(f"  找到{len(company_dirs)}个企业目录，处理前50个作为示例")

    for company_dir in company_dirs:
        company_code = company_dir.name
        # 读取该企业的所有文本文件
        text_files = list(company_dir.glob('2025/*.txt'))

        if text_files:
            combined_content = []
            for text_file in text_files:
                try:
                    with open(text_file, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        combined_content.append(content)
                except Exception as e:
                    print(f"  警告: 无法读取 {text_file}: {e}")

            if combined_content:
                company_texts[company_code] = '\n'.join(combined_content)
else:
    print("  警告: 未找到text目录")

print(f"  已加载{len(company_texts)}家企业的文本数据")

# 提取定性指标
print("\n提取定性指标...")
qualitative_results = []

for company_code, text_content in company_texts.items():
    # 获取企业名称
    company_name = company_names.get(company_code, company_code)

    for indicator_code, keywords in KEYWORD_RULES.items():
        score = score_qualitative_indicator(text_content, indicator_code, keywords)

        if score > 0:
            qualitative_results.append({
                'company_code': company_code,
                'company_name': company_name,
                'indicator_code': indicator_code,
                'score': score,
                'confidence': 0.70,  # 定性评分置信度较低
                'method': 'keyword_matching'
            })

print(f"  提取到{len(qualitative_results)}条定性指标记录")

# 保存结果
if qualitative_results:
    output_file = 'output/audit/qualitative_indicators_v1_2025.csv'
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['company_code', 'company_name', 'indicator_code', 'score', 'confidence', 'method']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(qualitative_results)

    print(f"\n已保存到: {output_file}")

    # 统计
    print("\n" + "=" * 70)
    print("定性指标提取统计")
    print("=" * 70)

    by_indicator = defaultdict(int)
    for record in qualitative_results:
        by_indicator[record['indicator_code']] += 1

    print(f"\n各指标提取数量:")
    for indicator_code, count in sorted(by_indicator.items(), key=lambda x: x[1], reverse=True):
        print(f"  {indicator_code}: {count}条")
else:
    print("\n未提取到定性指标数据")

print("\n" + "=" * 70)
print("⚠️  当前限制")
print("=" * 70)
print("""
当前实现是一个简化的演示框架，存在以下局限：

1. **方法限制**: 仅使用简单关键词匹配，未使用NLP语义分析
2. **评分简化**: 基于关键词出现频次，未考虑披露质量和深度
3. **覆盖率低**: 仅处理了部分企业和部分定性指标
4. **置信度低**: 定性评分置信度设为0.70（低于定量0.90）

完整实现需要:
- 使用NLP模型进行语义理解
- 建立定性评分标准和评分表
- 人工审核和标注训练数据
- 整合到评分引擎中

建议后续采用：
1. 使用大语言模型（LLM）进行定性内容理解
2. 建立定性指标的评分rubric（评分准则）
3. 人工审核样本以提高准确性
4. 逐步扩展到所有43个定性指标
""")

print("\n" + "=" * 70)
print("✅ 定性指标提取框架搭建完成")
print("=" * 70)
