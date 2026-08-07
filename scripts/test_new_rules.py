#!/usr/bin/env python3
"""测试新增规则的提取效果"""

import sys
sys.path.insert(0, 'src')

from aegis_esg.extraction import extract_from_text_files, DIRECT_RULES
from pathlib import Path

# 测试几个样本公司
test_companies = [
    ('000009.SZ', '中国宝安'),
    ('000027.SZ', '深圳能源'),
    ('000400.SZ', '许继电气'),
    ('002459.SZ', '晶澳科技'),
    ('605162.SH', '新中港'),
]

print(f"当前DirectRule规则数: {len(DIRECT_RULES)}")
print()

# 检查新增规则
new_indicators = ['Q_G_REVENUE', 'Q_E_SO2_EMISSION', 'Q_E_NOX_EMISSION', 'Q_E_SOLID_WASTE_GENERATION']
print("检查新增规则:")
for indicator in new_indicators:
    count = sum(1 for rule in DIRECT_RULES if rule.indicator_code == indicator)
    print(f"  {indicator}: {count}条规则")
print()

for company_code, company_name in test_companies:
    text_dir = Path(f'data/text/{company_code}/2025')
    if not text_dir.exists():
        continue

    print(f"=== {company_code} {company_name} ===")

    # 提取数据
    observations, _ = extract_from_text_files(
        company_code=company_code,
        company_name=company_name,
        report_year=2025,
        text_dir=text_dir,
        source_url=f"test_{company_code}",
        source_file=f"test_{company_code}",
    )

    # 统计新增指标
    found = {}
    for obs in observations:
        if obs.indicator_code in new_indicators:
            found[obs.indicator_code] = obs.value

    if found:
        for indicator, value in found.items():
            print(f"  {indicator}: {value}")
    else:
        print("  未提取到新增指标")

    print()

print("测试完成!")
