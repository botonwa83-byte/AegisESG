#!/usr/bin/env python3
"""
企业行业分类工具
基于公司名称、业务特征进行行业细分
"""

import csv
import json
from collections import defaultdict

# 行业分类规则（按优先级排序）
INDUSTRY_RULES = [
    # 核电
    ('核电', ['核电', '核能', '核工']),
    # 水电
    ('水电', ['水电', '水力', '长江电力', '黔源', '川投能源', '桂冠', '三峡', '乌江', '岷江', '赣能', '闽东', '郴电']),
    # 风电
    ('风电', ['风电', '风能', '金风', '明阳', '运达', '大金重工', '天顺风能', '泰胜风能']),
    # 光伏/太阳能
    ('光伏', ['阳光电源', '隆基', '通威', '晶科', '协鑫', '天合', '东方日升', '亿晶', '太阳能', '拓日新能', '爱康科技', '中利集团', '林洋能源', '珈伟新能']),
    # 燃气
    ('燃气', ['燃气', '天然气', '新奥', '港华', '昆仑能源', '中国燃气', '华润燃气', '深圳燃气', '佛燃', '皖天然气', '贵州燃气']),
    # 煤炭
    ('煤炭', ['煤业', '煤炭', '焦煤', '兖矿', '陕煤', '中国神华', '山煤', '盘江', '冀中能源', '开滦', '山西焦煤', '西山煤电', '潞安']),
    # 石油石化
    ('石油石化', ['石油', '石化', '中石油', '中石化', '中海油', '石油工程', '海油工程', '石油化工', '泰山石油', '广聚能源']),
    # 火电（包含传统电力）
    ('火电', ['华电', '国电', '大唐', '华能', '国电投', '电力发展', '粤电力', '皖能电力', '内蒙华电', '建投能源', '京能电力', '浙能电力', '申能股份', '深圳能源', '豫能控股', '漳泽电力', '国投电力', '华银电力']),
    # 电力设备
    ('电力设备', ['许继电气', '平高电气', '特变电工', '保变电气', '思源电气', '东方电气', '上海电气', '国电南瑞', '国电南自', '积成电子', '科陆电子', '科达利', '通达股份']),
    # 电力电缆
    ('电力电缆', ['东方电缆', '中天科技', '汉缆股份', '太阳电缆', '宝胜股份']),
    # 新能源材料
    ('新能源材料', ['德业股份', '湖南裕能', '横店东磁', '英杰电气', '通合科技', '新疆火炬', '岳阳兴长', '升达林业']),
    # 综合能源/公用事业
    ('综合能源', ['能源', '电力', '公用'])
]

def classify_company(company_name):
    """根据公司名称分类"""
    for industry, keywords in INDUSTRY_RULES:
        for keyword in keywords:
            if keyword in company_name:
                return industry
    return '其他能源'

# 读取企业列表
print("正在读取企业数据...")
companies = {}
with open('output/audit/esg_scores_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row['company_code']
        companies[code] = {
            'name': row['company_name'],
            'esg_score': float(row['esg_score']),
            'e_score': float(row['e_score']),
            's_score': float(row['s_score']),
            'g_score': float(row['g_score']),
            'rank': int(row['rank'])
        }

# 分类
print(f"正在对{len(companies)}家企业进行行业分类...")
industry_distribution = defaultdict(list)

for code, info in companies.items():
    industry = classify_company(info['name'])
    industry_distribution[industry].append({
        'code': code,
        'name': info['name'],
        'esg_score': info['esg_score'],
        'e_score': info['e_score'],
        's_score': info['s_score'],
        'g_score': info['g_score'],
        'overall_rank': info['rank']
    })

# 计算行业内排名
for industry in industry_distribution:
    industry_distribution[industry].sort(key=lambda x: x['esg_score'], reverse=True)
    for i, company in enumerate(industry_distribution[industry], 1):
        company['industry_rank'] = i

# 输出行业分布统计
print("\n" + "=" * 70)
print("行业分布统计")
print("=" * 70)
for industry in sorted(industry_distribution.keys(), key=lambda x: len(industry_distribution[x]), reverse=True):
    companies_in_industry = industry_distribution[industry]
    avg_score = sum(c['esg_score'] for c in companies_in_industry) / len(companies_in_industry)
    print(f"{industry:12s}: {len(companies_in_industry):3d}家企业, 平均ESG得分: {avg_score:.2f}")

# 保存分类结果
output_file = 'output/audit/esg_scores_with_industry_v1_2025.csv'
with open(output_file, 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['overall_rank', 'industry', 'industry_rank', 'company_code', 'company_name',
                  'esg_score', 'e_score', 's_score', 'g_score']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for industry in sorted(industry_distribution.keys()):
        for company in industry_distribution[industry]:
            writer.writerow({
                'overall_rank': company['overall_rank'],
                'industry': industry,
                'industry_rank': company['industry_rank'],
                'company_code': company['code'],
                'company_name': company['name'],
                'esg_score': company['esg_score'],
                'e_score': company['e_score'],
                's_score': company['s_score'],
                'g_score': company['g_score']
            })

print(f"\n已保存到: {output_file}")

# 输出各行业Top 3
print("\n" + "=" * 70)
print("各行业Top 3企业")
print("=" * 70)
for industry in sorted(industry_distribution.keys(), key=lambda x: len(industry_distribution[x]), reverse=True):
    companies_in_industry = industry_distribution[industry]
    if len(companies_in_industry) >= 3:
        print(f"\n{industry} (共{len(companies_in_industry)}家):")
        for company in companies_in_industry[:3]:
            print(f"  {company['industry_rank']}. {company['name'][:20]:<20} " +
                  f"{company['esg_score']:.2f}分 [E:{company['e_score']:.1f} S:{company['s_score']:.1f} G:{company['g_score']:.1f}] " +
                  f"(总排名#{company['overall_rank']})")

print("\n" + "=" * 70)
print("✅ 行业分类完成")
print("=" * 70)
