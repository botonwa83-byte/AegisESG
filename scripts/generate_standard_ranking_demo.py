#!/usr/bin/env python3
"""
按照客户标准排名表格格式生成demo页面
参考：排名表标准.png 和 2024年客户Excel格式
"""

import json
import csv

print("=" * 80)
print("生成符合客户标准的排名demo页面")
print("=" * 80)

# 读取排名数据
with open('output/audit/client_method_ranking_2025/ranking.json', 'r', encoding='utf-8') as f:
    ranking = json.load(f)

print(f"\n已加载 {len(ranking)} 家企业排名数据")

# 10项关键指标定义（与客户标准一致）
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

# 生成HTML
html = """<!doctype html>
<html lang='zh-CN'>
<head>
<meta charset='utf-8'>
<title>2026中国能源上市公司可持续发展（ESG）评价</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;margin:16px;color:#173d45;font-size:12px}
h1{text-align:center;color:#174c72;font-size:18px;margin:20px 0}
.note{max-width:1400px;margin:0 auto 12px;line-height:1.5;color:#355;font-size:11px}
table{border-collapse:collapse;width:100%;font-size:11px;margin:0 auto;max-width:1600px}
th{background:#4472C4;color:white;padding:8px 4px;text-align:center;border:1px solid #2E5A9D;font-weight:bold}
td{border:1px solid #B4C7E7;padding:4px 6px;text-align:center}
tr.value-row{background:#FFFFFF}
tr.score-row{background:#F2F2F2}
td.rank-col{font-weight:bold;background:#E7E6E6}
td.company-col{text-align:left;padding-left:8px}
td.esg-score{background:#FFF2CC;font-weight:bold;color:#C00000;font-size:13px}
.indicator-label{font-size:10px;color:#666;display:block;margin-top:2px}
@media print{body{margin:8mm} th{position:static} @page{size:A3 landscape}}
</style>
</head>
<body>
<h1>2026中国能源上市公司可持续发展（ESG）评价</h1>
<p class='note'>
本表共 <b>{}</b> 家企业。评价标准：DL/T 2971—2025。
每个企业占2行：第1行为指标原始数值，第2行为标准化得分（0-100分）。
表中展示10项关键定量指标。总分 = 定量分×80% + 定性分×20%。
<span style="color:#C00000">⚠️ 本排名为研究测试版本，用于系统调校验证，非正式发布榜单</span>
</p>
<table>
<thead>
<tr>
<th rowspan="2" style="width:40px">序号</th>
<th rowspan="2" style="width:90px">证券代码</th>
<th rowspan="2" style="width:120px">公司简称</th>
<th rowspan="2" style="width:60px">披露率</th>
<th rowspan="2" style="width:60px">定量分</th>
<th rowspan="2" style="width:60px">定性分</th>
""".format(len(ranking))

# 添加10个指标列
for _, name in KEY_INDICATORS:
    html += f"<th style='width:80px'>{name}</th>"

html += """
<th rowspan="2" style="width:90px">ESG<br>分值</th>
</tr>
<tr>
"""

# 第二行表头：指标说明
for _ in KEY_INDICATORS:
    html += "<th style='font-size:9px;color:#AAA'>数值/分值</th>"

html += """
</tr>
</thead>
<tbody>
"""

# 生成数据行（只显示前100名）
for company in ranking[:100]:
    # 提取指标数据
    indicators = {d['indicator_code']: d for d in company['details']}

    rank = company['rank']
    code = company['company_code']
    name = company['company_name']
    disclosure = company['disclosure_rate']
    quant_score = company['quantitative_score']
    qual_score = company['qualitative_score']
    esg_score = company['total_score']

    # 第1行：指标数值
    html += f"""
<tr class="value-row">
<td class="rank-col" rowspan="2">{rank}</td>
<td rowspan="2">{code}</td>
<td class="company-col" rowspan="2">{name}</td>
<td rowspan="2">{disclosure:.1f}%</td>
<td rowspan="2">{quant_score:.2f}</td>
<td rowspan="2">{qual_score:.2f}</td>
"""

    for ind_code, _ in KEY_INDICATORS:
        ind = indicators.get(ind_code, {})
        raw_value = ind.get('raw_value')
        if raw_value is not None:
            html += f"<td>{raw_value:.2f}</td>"
        else:
            html += "<td>-</td>"

    html += f"""
<td class="esg-score" rowspan="2">{esg_score:.2f}</td>
</tr>
"""

    # 第2行：指标分值
    html += """
<tr class="score-row">
"""

    for ind_code, _ in KEY_INDICATORS:
        ind = indicators.get(ind_code, {})
        score = ind.get('normalized_score', 0)
        if score > 0:
            html += f"<td style='color:#666'>{score:.1f}</td>"
        else:
            html += "<td style='color:#CCC'>-</td>"

    html += """
</tr>
"""

html += """
</tbody>
</table>
<p style='text-align:center;margin-top:20px;color:#999;font-size:10px'>
数据来源：企业2025年年报及ESG报告 | 评价标准：DL/T 2971—2025 |
生成时间：2026-08-07 | <a href="https://github.com/botonwa83-byte/AegisESG" style="color:#4472C4">查看完整数据</a>
</p>
</body>
</html>
"""

# 保存HTML
output_file = 'output/demo/real_data_demo_2025/ranking_standard.html'
with open(output_file, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\n已保存: {output_file}")
print(f"格式: 每企业2行（数值行+分值行）")
print(f"显示: 前100名企业")

print("\n" + "=" * 80)
print("✅ 客户标准格式排名表已生成")
print("=" * 80)
print(f"\n预览: file://{output_file}")
