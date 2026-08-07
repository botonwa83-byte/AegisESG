#!/usr/bin/env python3
"""
更新GitHub Pages排名数据
将最新的ESG评分数据生成HTML格式用于GitHub Pages展示
"""

import csv
import json
from datetime import datetime

print("=" * 70)
print("生成GitHub Pages排名数据")
print("=" * 70)

# 读取最新评分数据
companies = []
with open('output/audit/esg_scores_with_industry_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        companies.append({
            'overall_rank': int(row['overall_rank']),
            'industry': row['industry'],
            'industry_rank': int(row['industry_rank']),
            'company_code': row['company_code'],
            'company_name': row['company_name'],
            'esg_score': float(row['esg_score']),
            'e_score': float(row['e_score']),
            's_score': float(row['s_score']),
            'g_score': float(row['g_score'])
        })

print(f"\n已加载 {len(companies)} 家企业数据")

# 按总排名排序
companies_by_rank = sorted(companies, key=lambda x: x['overall_rank'])

# 生成简化的JSON数据（用于前端展示）
ranking_data = {
    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'total_companies': len(companies),
    'data_version': 'v1_2025',
    'top_100': []
}

for company in companies_by_rank[:100]:
    ranking_data['top_100'].append({
        'rank': company['overall_rank'],
        'code': company['company_code'],
        'name': company['company_name'],
        'industry': company['industry'],
        'esg': round(company['esg_score'], 2),
        'e': round(company['e_score'], 1),
        's': round(company['s_score'], 1),
        'g': round(company['g_score'], 1)
    })

# 保存为JSON
output_json = 'docs/ranking/data.json'
with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(ranking_data, f, ensure_ascii=False, indent=2)

print(f"已保存到: {output_json}")

# 生成简单的HTML预览页面
html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ESG评分排名 - Top 100</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #333;
            text-align: center;
        }}
        .info {{
            text-align: center;
            color: #666;
            margin-bottom: 20px;
        }}
        table {{
            width: 100%;
            background: white;
            border-collapse: collapse;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: #4CAF50;
            color: white;
            font-weight: 600;
        }}
        tr:hover {{
            background: #f5f5f5;
        }}
        .rank {{
            font-weight: bold;
            color: #4CAF50;
        }}
        .score {{
            font-weight: 600;
        }}
        .industry {{
            color: #666;
            font-size: 0.9em;
        }}
        .dim-score {{
            font-size: 0.9em;
            color: #777;
        }}
    </style>
</head>
<body>
    <h1>🌱 能源企业ESG评分排名 Top 100</h1>
    <div class="info">
        <p>更新时间: {ranking_data['updated_at']} | 数据版本: {ranking_data['data_version']} | 企业总数: {ranking_data['total_companies']}</p>
        <p>评分维度: E(环境) + S(社会) + G(治理) = ESG综合得分</p>
    </div>

    <table>
        <thead>
            <tr>
                <th>排名</th>
                <th>股票代码</th>
                <th>企业名称</th>
                <th>行业</th>
                <th>ESG得分</th>
                <th>E得分</th>
                <th>S得分</th>
                <th>G得分</th>
            </tr>
        </thead>
        <tbody>
"""

for company in ranking_data['top_100']:
    html_content += f"""            <tr>
                <td class="rank">{company['rank']}</td>
                <td>{company['code']}</td>
                <td>{company['name']}</td>
                <td class="industry">{company['industry']}</td>
                <td class="score">{company['esg']}</td>
                <td class="dim-score">{company['e']}</td>
                <td class="dim-score">{company['s']}</td>
                <td class="dim-score">{company['g']}</td>
            </tr>
"""

html_content += """        </tbody>
    </table>

    <div style="margin-top: 40px; text-align: center; color: #999;">
        <p>基于 DL/T 2971-2025 标准 | 数据覆盖率 99.7%</p>
        <p><a href="https://github.com/botonwa83-byte/AegisESG" style="color: #4CAF50;">查看完整数据和方法论</a></p>
    </div>
</body>
</html>
"""

# 保存HTML
output_html = 'docs/ranking/top100.html'
with open(output_html, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"已保存到: {output_html}")

print("\n" + "=" * 70)
print("✅ GitHub Pages数据更新完成")
print("=" * 70)
print(f"\n访问地址:")
print(f"  JSON数据: https://botonwa83-byte.github.io/AegisESG/ranking/data.json")
print(f"  排名页面: https://botonwa83-byte.github.io/AegisESG/ranking/top100.html")
print(f"  主页面: https://botonwa83-byte.github.io/AegisESG/")
