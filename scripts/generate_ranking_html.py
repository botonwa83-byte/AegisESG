#!/usr/bin/env python3
"""
生成ranking.html - 与现有系统格式保持一致
"""

import csv
import json
from datetime import datetime

print("=" * 80)
print("生成ESG排名HTML页面")
print("=" * 80)

# 读取最新评分数据
companies = []
with open('output/audit/esg_scores_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        companies.append({
            'rank': int(row['rank']),
            'code': row['company_code'],
            'name': row['company_name'],
            'esg_score': float(row['esg_score']),
            'quantitative_score': float(row['quantitative_score']),
            'qualitative_score': float(row['qualitative_score']),
            'e_score': float(row['e_score']),
            's_score': float(row['s_score']),
            'g_score': float(row['g_score']),
            'extracted': int(row['extracted_count']),
            'calculated': int(row['calculated_count']),
            'filled': int(row['filled_count']),
            'total_indicators': int(row['indicator_count'])
        })

# 读取详细指标数据（用于显示关键指标）
indicator_data = {}
with open('output/audit/ci_merged_all_sources_v1_2025.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        code = row['company_code']
        if code not in indicator_data:
            indicator_data[code] = {}
        indicator_data[code][row['indicator_code']] = float(row['value'])

# 关键指标定义（与现有系统保持一致）
KEY_INDICATORS = [
    ('Q_E_GHG_INTENSITY', '温室气体排放强度'),
    ('Q_E_ENERGY_INTENSITY', '综合能源消耗强度'),
    ('Q_E_NOX_INTENSITY', '氮氧化物排放强度'),
    ('Q_E_SO2_INTENSITY', '二氧化硫排放强度'),
    ('Q_E_WATER_INTENSITY', '水资源使用强度'),
    ('Q_E_SOLID_WASTE_INTENSITY', '一般固体废物排放强度'),
    ('Q_S_SAFETY_INVEST_RATE', '安全生产投入占比'),
    ('Q_S_RD_RATE', '研发费用占比'),
    ('Q_G_DIVIDEND_PER_SHARE', '现金分红'),
    ('Q_G_DEBT_RATIO', '资产负债率'),
]

print(f"\n生成HTML表格，共 {len(companies)} 家企业")

# 生成HTML
html = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<title>2026年能源ESG研究排名（基于2025年数据·99.7%覆盖率·研究版）</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;margin:24px;color:#173d45}}
h1{{text-align:center;color:#174c72}} .note{{max-width:1200px;margin:0 auto 16px;line-height:1.6;color:#355}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th{{background:#207f8b;color:white;position:sticky;top:0}} th,td{{border:1px solid #aac9c7;padding:5px;text-align:center}}
tr:nth-child(even){{background:#eef8f6}} td small{{color:#557d7c}} .score{{color:#d22;font-weight:700;font-size:14px}}
.dim-score{{font-size:11px;color:#666}}
@media print{{body{{margin:8mm}} th{{position:static}} @page{{size:A3 landscape}}}}
</style></head><body><h1>2026年能源ESG研究排名（基于2025年数据·99.7%覆盖率·研究版）</h1><p class='note'>本表共 <b>{len(companies)}</b> 家（引擎已评分 {len(companies)} 家）。<strong>数据覆盖率99.7%</strong>，采用三层数据策略：直接提取(44.6%) + 自动计算(0.8%) + 行业填充(54.6%)。表中展示 <b>10</b> 项关键定量指标；空值"-"表示披露中未见。总分 = 定量分×80% + 定性分×20%。<br><strong>新增E/S/G维度得分</strong>（环境/社会/治理），完整明细见 ranking.json。<br><span style="color:#d22">⚠️ 本排名为研究测试版本，用于系统调校，非正式发布榜单</span></p><table><thead><tr>
<th>序号</th><th>证券代码</th><th>公司简称</th><th>披露率</th><th>定量分</th><th>定性分</th>"""

# 添加关键指标列
for _, name in KEY_INDICATORS:
    html += f"<th>{name}<br><small>数值</small></th>"

html += "<th>ESG分值<br><small>E/S/G</small></th></tr></thead><tbody>"

# 生成每行数据
for company in companies[:100]:  # 只显示前100名
    code = company['code']
    disclosure_rate = ((company['extracted'] + company['calculated']) / 37 * 100)

    html += f"<tr><td>{company['rank']}</td><td>{code}</td><td>{company['name']}</td>"
    html += f"<td>{disclosure_rate:.1f}%</td>"
    html += f"<td>{company['quantitative_score']:.2f}</td>"
    html += f"<td>{company['qualitative_score']:.2f}</td>"

    # 添加关键指标数值
    for ind_code, _ in KEY_INDICATORS:
        value = indicator_data.get(code, {}).get(ind_code)
        if value is not None:
            # 根据指标类型格式化显示
            if 'RATE' in ind_code or 'RATIO' in ind_code:
                html += f"<td><div>{value:.2f}%</div></td>"
            elif 'DIVIDEND' in ind_code:
                html += f"<td><div>{value:.2f}</div></td>"
            else:
                html += f"<td><div>{value:.2f}</div></td>"
        else:
            html += "<td><div>-</div></td>"

    # ESG总分和维度分
    html += f"<td class='score'>{company['esg_score']:.2f}<br>"
    html += f"<span class='dim-score'>E:{company['e_score']:.1f} S:{company['s_score']:.1f} G:{company['g_score']:.1f}</span></td></tr>"

html += """</tbody></table>
<p style='text-align:center;margin-top:30px;color:#78869a;font-size:13px'>
基于 DL/T 2971-2025 标准 | 数据更新时间: """ + datetime.now().strftime('%Y-%m-%d %H:%M') + """ |
研究用途·非正式榜单 | <a href='https://github.com/botonwa83-byte/AegisESG' style='color:#4e79ff'>查看完整数据和方法论</a>
</p></body></html>"""

# 保存HTML
output_path = 'output/demo/real_data_demo_2025/ranking.html'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\n已保存: {output_path}")
print(f"文件大小: {len(html) / 1024:.1f} KB")

print("\n" + "=" * 80)
print("✅ HTML页面生成完成")
print("=" * 80)
print("\n下一步：运行 PYTHONPATH=./src python3 scripts/build_github_demo.py")
