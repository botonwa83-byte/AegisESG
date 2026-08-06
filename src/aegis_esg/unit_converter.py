"""单位标准化模块 - 将企业披露单位转换为方法论标准单位

根据 DL/T 2971-2025 标准和 energy_esg_2025_research_sasac.json 方法论
"""
from __future__ import annotations

# 方法论标准单位定义
STANDARD_UNITS = {
    "Q_E_GHG_INTENSITY": "千克/万元",           # 温室气体排放强度
    "Q_E_ENERGY_INTENSITY": "千克/万元",       # 能源消耗强度（千克标准煤）
    "Q_E_WATER_INTENSITY": "立方米/万元",      # 水资源使用强度
    "Q_E_NOX_INTENSITY": "克/万元",            # NOx排放强度
    "Q_E_SO2_INTENSITY": "克/万元",            # SO2排放强度
    "Q_E_PM_INTENSITY": "克/万元",             # PM排放强度
    "Q_E_SOLID_WASTE_INTENSITY": "千克/万元",  # 固废排放强度
    "Q_E_HAZ_WASTE_INTENSITY": "千克/万元",    # 危废排放强度
    "Q_E_WASTEWATER_INTENSITY": "立方米/万元", # 废水排放强度
}

# 单位换算表：(源单位, 目标单位) -> 换算系数
UNIT_CONVERSIONS = {
    # 温室气体排放强度：目标 千克/万元
    ("吨CO2e", "百万元", "千克", "万元"): 10.0,      # 1吨/百万元 = 10千克/万元
    ("吨CO2", "百万元", "千克", "万元"): 10.0,
    ("吨二氧化碳当量", "百万元", "千克", "万元"): 10.0,
    ("千克CO2e", "万元", "千克", "万元"): 1.0,
    ("吨CO2e", "万元", "千克", "万元"): 1000.0,
    ("tCO2e", "百万元", "千克", "万元"): 10.0,

    # 能源消耗强度：目标 千克/万元（千克标准煤）
    ("吨标准煤", "百万元", "千克", "万元"): 10.0,
    ("吨标煤", "百万元", "千克", "万元"): 10.0,
    ("tce", "百万元", "千克", "万元"): 10.0,
    ("千克标煤", "万元", "千克", "万元"): 1.0,
    ("吨标煤", "万元", "千克", "万元"): 1000.0,

    # NOx, SO2排放强度：目标 克/万元
    ("千克", "万元", "克", "万元"): 1000.0,
    ("吨", "百万元", "克", "万元"): 10000.0,
    ("克", "万元", "克", "万元"): 1.0,
    ("kg", "万元", "克", "万元"): 1000.0,
    ("g", "万元", "克", "万元"): 1.0,

    # 水资源、废水：目标 立方米/万元
    ("吨", "百万元", "立方米", "万元"): 0.01,      # 1吨/百万元 = 0.01立方米/万元
    ("立方米", "百万元", "立方米", "万元"): 0.01,
    ("m³", "百万元", "立方米", "万元"): 0.01,
    ("立方米", "万元", "立方米", "万元"): 1.0,

    # 固废、危废：目标 千克/万元
    ("吨", "百万元", "千克", "万元"): 10.0,
    ("千克", "万元", "千克", "万元"): 1.0,
    ("kg", "万元", "千克", "万元"): 1.0,
}


def detect_unit_components(unit_text: str) -> dict:
    """从单位文本中提取组成部分

    Args:
        unit_text: 如 "吨CO2e/百万元营收"

    Returns:
        {
            'numerator': '吨CO2e',
            'denominator': '百万元',
            'raw': unit_text
        }
    """
    # 清理文本
    text = unit_text.strip()

    # 提取分子分母
    if '/' in text or '／' in text:
        parts = text.replace('／', '/').split('/')
        if len(parts) >= 2:
            numerator = parts[0].strip()
            denominator = parts[1].strip()

            # 清理分母中的额外文字
            for suffix in ['营收', '营业收入', '收入', '产值']:
                denominator = denominator.replace(suffix, '')

            return {
                'numerator': numerator,
                'denominator': denominator.strip(),
                'raw': text
            }

    return {'numerator': '', 'denominator': '', 'raw': text}


def convert_to_standard(value: float, source_unit_text: str, indicator_code: str) -> tuple[float, bool]:
    """转换到方法论标准单位

    Args:
        value: 原始数值
        source_unit_text: 源单位文本，如 "吨CO2e/百万元"
        indicator_code: 指标代码，如 "Q_E_GHG_INTENSITY"

    Returns:
        (标准化后的值, 是否成功转换)
    """
    # 获取标准单位
    if indicator_code not in STANDARD_UNITS:
        return value, False

    standard_unit = STANDARD_UNITS[indicator_code]

    # 解析源单位
    components = detect_unit_components(source_unit_text)
    if not components['numerator'] or not components['denominator']:
        return value, False

    # 查找换算系数
    source_num = components['numerator']
    source_den = components['denominator']

    # 解析标准单位
    if '/' in standard_unit:
        target_num, target_den = standard_unit.split('/')
    else:
        return value, False

    # 尝试匹配换算规则
    for key, factor in UNIT_CONVERSIONS.items():
        src_num_unit, src_den_unit, tgt_num_unit, tgt_den_unit = key

        # 检查是否匹配
        if (src_num_unit in source_num and src_den_unit in source_den and
            tgt_num_unit in target_num and tgt_den_unit in target_den):
            return value * factor, True

    # 未找到匹配规则
    return value, False


def get_standard_unit(indicator_code: str) -> str | None:
    """获取指标的标准单位"""
    return STANDARD_UNITS.get(indicator_code)


def validate_value_range(value: float, indicator_code: str) -> bool:
    """验证数值是否在合理范围内

    基于历史数据的经验范围
    """
    # 合理范围定义（基于方法论中的分位数）
    REASONABLE_RANGES = {
        "Q_E_GHG_INTENSITY": (0, 50000),      # 千克/万元
        "Q_E_ENERGY_INTENSITY": (0, 50000),   # 千克/万元
        "Q_E_WATER_INTENSITY": (0, 10000),    # 立方米/万元
        "Q_E_NOX_INTENSITY": (0, 10000),      # 克/万元
        "Q_E_SO2_INTENSITY": (0, 10000),      # 克/万元
        "Q_E_PM_INTENSITY": (0, 5000),        # 克/万元
        "Q_E_SOLID_WASTE_INTENSITY": (0, 20000), # 千克/万元
        "Q_E_HAZ_WASTE_INTENSITY": (0, 5000),  # 千克/万元
        "Q_E_WASTEWATER_INTENSITY": (0, 5000), # 立方米/万元
    }

    if indicator_code in REASONABLE_RANGES:
        min_val, max_val = REASONABLE_RANGES[indicator_code]
        return min_val <= value <= max_val

    return True  # 未知指标，不验证


# 测试代码
if __name__ == "__main__":
    # 测试用例
    test_cases = [
        (44.11, "吨CO2e/百万元", "Q_E_GHG_INTENSITY", 441.1),
        (1.23, "吨标煤/百万元", "Q_E_ENERGY_INTENSITY", 12.3),
        (0.5, "千克/万元", "Q_E_NOX_INTENSITY", 500.0),
    ]

    print("单位转换测试：")
    for value, unit, code, expected in test_cases:
        result, success = convert_to_standard(value, unit, code)
        status = "✅" if success and abs(result - expected) < 0.01 else "❌"
        print(f"{status} {value} {unit} -> {result:.2f} (预期 {expected})")
