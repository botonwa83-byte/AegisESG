#!/usr/bin/env python3
"""快速测试提取规则改进效果"""

import sys
sys.path.insert(0, 'src')

from aegis_esg.extraction import DIRECT_RULES, RULES

# 统计规则数量
print("=" * 60)
print("提取规则统计")
print("=" * 60)

print(f"\n📊 DirectRule规则数量: {len(DIRECT_RULES)}")
print(f"📊 RULES(_rule)规则数量: {len(RULES)}")

# 统计关键指标的规则
key_indicators = [
    "Q_S_SAFETY_INVEST_RATE",
    "Q_E_SOLID_WASTE_INTENSITY",
    "Q_E_ENERGY_INTENSITY",
    "Q_E_WATER_INTENSITY",
    "Q_E_GHG_INTENSITY",
    "Q_E_SO2_INTENSITY",
    "Q_E_NOX_INTENSITY",
]

print("\n" + "=" * 60)
print("关键指标DirectRule覆盖情况")
print("=" * 60)

for indicator in key_indicators:
    count = sum(1 for rule in DIRECT_RULES if rule.indicator_code == indicator)
    status = "✅" if count > 0 else "❌"
    print(f"{status} {indicator}: {count} 条DirectRule")

print("\n" + "=" * 60)
print("关键指标RULES覆盖情况")
print("=" * 60)

for indicator in key_indicators:
    count = sum(1 for rule in RULES if rule.indicator_code == indicator)
    status = "✅" if count > 0 else "❌"
    print(f"{status} {indicator}: {count} 条RULES")

# 测试一些规则的正则表达式
print("\n" + "=" * 60)
print("测试关键词扩展")
print("=" * 60)

test_texts = [
    ("Q_E_SOLID_WASTE_INTENSITY", "一般固废强度 吨/万元 1.23 1.45"),
    ("Q_E_GHG_INTENSITY", "温室气体排放强度 吨CO₂/百万元 38.02 44.11"),
    ("Q_S_SAFETY_INVEST_RATE", "安全投入占比 % 0.5 0.6"),
]

for indicator_code, text in test_texts:
    for rule in DIRECT_RULES:
        if rule.indicator_code == indicator_code:
            match = rule.pattern.search(text)
            if match:
                print(f"✅ {indicator_code}: 匹配成功")
                print(f"   文本: {text}")
                print(f"   匹配值: {match.group(1) if match.lastindex else 'N/A'}")
            break
    else:
        print(f"❌ {indicator_code}: 未找到规则")

print("\n" + "=" * 60)
print("规则优化验证完成")
print("=" * 60)
