"""公式派生引擎：从已有观测推导缺失指标值

本模块通过财务公式从已确认的观测数据中派生新的指标值，用于提升数据覆盖率。
所有派生值都会标注来源、公式和置信度，确保审计追溯能力。

设计原则：
1. 仅从status=CONFIRMED的观测派生
2. 派生值置信度为源数据最低置信度 × 0.9
3. 派生值不参与行业基准统计（避免循环依赖）
4. 记录完整的派生链：公式、源观测ID、计算时间
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .models import Observation, ValueStatus


@dataclass(frozen=True)
class DerivationRule:
    """派生规则定义"""
    target_indicator: str  # 目标指标代码
    target_name: str  # 目标指标名称
    source_indicators: list[str]  # 源指标代码列表
    formula: Callable[[dict[str, float]], float | None]  # 派生函数
    formula_description: str  # 公式描述（用于审计）
    min_confidence: float = 0.5  # 最低源数据置信度要求
    validation: Callable[[float], bool] | None = None  # 结果验证函数


# ============================================================================
# 强度类指标派生规则（分子/分母）
# ============================================================================

def _intensity_formula(numerator_key: str, denominator_key: str):
    """通用强度公式：分子 / 分母"""
    def formula(sources: dict[str, float]) -> float | None:
        numerator = sources.get(numerator_key)
        denominator = sources.get(denominator_key)
        if numerator is None or denominator is None or denominator <= 0:
            return None
        return numerator / denominator
    return formula


def _validate_positive(value: float) -> bool:
    """验证值为正数"""
    return value > 0 and math.isfinite(value)


def _validate_ratio_reasonable(value: float, max_ratio: float = 10.0) -> bool:
    """验证比率在合理范围内（避免分母过小导致的异常值）"""
    return 0 <= value <= max_ratio and math.isfinite(value)


# 能源强度：综合能耗 / 营业收入
ENERGY_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_ENERGY_INTENSITY",
    target_name="综合能源消耗强度",
    source_indicators=["Q_E_ENERGY_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_ENERGY_TOTAL", "Q_G_REVENUE"),
    formula_description="综合能耗(tce) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=100.0)
)

# 水资源强度：用水总量 / 营业收入
WATER_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_WATER_INTENSITY",
    target_name="水资源使用强度",
    source_indicators=["Q_E_WATER_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_WATER_TOTAL", "Q_G_REVENUE"),
    formula_description="用水总量(万吨) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=50.0)
)

# 温室气体强度：GHG排放量 / 营业收入
GHG_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_GHG_INTENSITY",
    target_name="温室气体排放强度",
    source_indicators=["Q_E_GHG_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_GHG_TOTAL", "Q_G_REVENUE"),
    formula_description="温室气体排放量(万tCO2e) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=100.0)
)

# SO2强度：SO2排放量 / 营业收入
SO2_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_SO2_INTENSITY",
    target_name="二氧化硫排放强度",
    source_indicators=["Q_E_SO2_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_SO2_TOTAL", "Q_G_REVENUE"),
    formula_description="SO2排放量(吨) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=10.0)
)

# NOx强度：NOx排放量 / 营业收入
NOX_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_NOX_INTENSITY",
    target_name="氮氧化物排放强度",
    source_indicators=["Q_E_NOX_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_NOX_TOTAL", "Q_G_REVENUE"),
    formula_description="NOx排放量(吨) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=10.0)
)

# 固废强度：固废排放量 / 营业收入
SOLID_WASTE_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_SOLID_WASTE_INTENSITY",
    target_name="一般固体废物排放强度",
    source_indicators=["Q_E_SOLID_WASTE_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_SOLID_WASTE_TOTAL", "Q_G_REVENUE"),
    formula_description="固废排放量(万吨) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=50.0)
)

# 危废强度：危废排放量 / 营业收入
HAZ_WASTE_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_HAZ_WASTE_INTENSITY",
    target_name="危险固体废物排放强度",
    source_indicators=["Q_E_HAZ_WASTE_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_HAZ_WASTE_TOTAL", "Q_G_REVENUE"),
    formula_description="危废排放量(吨) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=5.0)
)

# 废水强度：废水排放量 / 营业收入
WASTEWATER_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_WASTEWATER_INTENSITY",
    target_name="废水/污水排放强度",
    source_indicators=["Q_E_WASTEWATER_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_WASTEWATER_TOTAL", "Q_G_REVENUE"),
    formula_description="废水排放量(万吨) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=50.0)
)

# 颗粒物强度：PM排放量 / 营业收入
PM_INTENSITY_RULE = DerivationRule(
    target_indicator="Q_E_PM_INTENSITY",
    target_name="颗粒物排放强度",
    source_indicators=["Q_E_PM_TOTAL", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_E_PM_TOTAL", "Q_G_REVENUE"),
    formula_description="颗粒物排放量(吨) / 营业收入(亿元)",
    validation=lambda v: _validate_ratio_reasonable(v, max_ratio=10.0)
)


# ============================================================================
# 社会指标派生规则（人均指标）
# ============================================================================

# 人均薪酬：薪酬总额 / 员工人数
PAY_PER_EMPLOYEE_RULE = DerivationRule(
    target_indicator="Q_S_PAY_PER_EMPLOYEE",
    target_name="员工薪酬",
    source_indicators=["Q_S_PAY_TOTAL", "Q_S_EMPLOYEE_COUNT"],
    formula=_intensity_formula("Q_S_PAY_TOTAL", "Q_S_EMPLOYEE_COUNT"),
    formula_description="薪酬总额(万元) / 员工人数(人)",
    validation=lambda v: 1.0 <= v <= 500.0  # 人均1-500万/年合理范围
)

# 人均福利：福利总额 / 员工人数
BENEFIT_PER_EMPLOYEE_RULE = DerivationRule(
    target_indicator="Q_S_BENEFIT_PER_EMPLOYEE",
    target_name="员工福利、社保和公积金费用",
    source_indicators=["Q_S_BENEFIT_TOTAL", "Q_S_EMPLOYEE_COUNT"],
    formula=_intensity_formula("Q_S_BENEFIT_TOTAL", "Q_S_EMPLOYEE_COUNT"),
    formula_description="福利总额(万元) / 员工人数(人)",
    validation=lambda v: 0.5 <= v <= 100.0  # 人均0.5-100万/年合理范围
)

# 人均教育经费：教育经费 / 员工人数
EDU_PER_EMPLOYEE_RULE = DerivationRule(
    target_indicator="Q_S_EDU_PER_EMPLOYEE",
    target_name="工会和职工教育经费",
    source_indicators=["Q_S_EDU_TOTAL", "Q_S_EMPLOYEE_COUNT"],
    formula=_intensity_formula("Q_S_EDU_TOTAL", "Q_S_EMPLOYEE_COUNT"),
    formula_description="教育经费(万元) / 员工人数(人)",
    validation=lambda v: 0.01 <= v <= 10.0  # 人均0.01-10万/年合理范围
)


# ============================================================================
# 治理指标派生规则（财务比率）
# ============================================================================

# 营业利润率：营业利润 / 营业收入
OPERATING_MARGIN_RULE = DerivationRule(
    target_indicator="Q_G_OPERATING_MARGIN",
    target_name="营业利润率",
    source_indicators=["Q_G_OPERATING_PROFIT", "Q_G_REVENUE"],
    formula=_intensity_formula("Q_G_OPERATING_PROFIT", "Q_G_REVENUE"),
    formula_description="营业利润 / 营业收入",
    validation=lambda v: -1.0 <= v <= 1.0  # -100%到100%合理范围
)

# 总资产报酬率：净利润 / 总资产
ROA_RULE = DerivationRule(
    target_indicator="Q_G_ROA",
    target_name="总资产报酬率",
    source_indicators=["Q_G_NET_PROFIT", "Q_G_TOTAL_ASSETS"],
    formula=_intensity_formula("Q_G_NET_PROFIT", "Q_G_TOTAL_ASSETS"),
    formula_description="净利润 / 总资产",
    validation=lambda v: -0.5 <= v <= 0.5  # -50%到50%合理范围
)


# ============================================================================
# 主派生规则注册表
# ============================================================================

ALL_DERIVATION_RULES: list[DerivationRule] = [
    # 环境强度类（高优先级）
    ENERGY_INTENSITY_RULE,
    WATER_INTENSITY_RULE,
    GHG_INTENSITY_RULE,
    SO2_INTENSITY_RULE,
    NOX_INTENSITY_RULE,
    SOLID_WASTE_INTENSITY_RULE,
    HAZ_WASTE_INTENSITY_RULE,
    WASTEWATER_INTENSITY_RULE,
    PM_INTENSITY_RULE,

    # 社会人均类
    PAY_PER_EMPLOYEE_RULE,
    BENEFIT_PER_EMPLOYEE_RULE,
    EDU_PER_EMPLOYEE_RULE,

    # 治理财务比率
    OPERATING_MARGIN_RULE,
    ROA_RULE,
]


# ============================================================================
# 派生引擎
# ============================================================================

@dataclass
class DerivationResult:
    """派生结果"""
    derived_observation: Observation | None
    success: bool
    rule: DerivationRule
    source_values: dict[str, float]
    derived_value: float | None
    failure_reason: str | None = None


class FormulaDerivationEngine:
    """公式派生引擎"""

    def __init__(self, rules: list[DerivationRule] | None = None):
        self.rules = rules or ALL_DERIVATION_RULES
        self._rules_by_target = {rule.target_indicator: rule for rule in self.rules}

    def derive_for_company(
        self,
        company_code: str,
        company_name: str,
        report_year: int,
        observations: list[Observation],
    ) -> list[DerivationResult]:
        """为单个公司派生缺失指标

        Args:
            company_code: 公司代码
            company_name: 公司名称
            report_year: 报告年度
            observations: 该公司该年度的已确认观测

        Returns:
            派生结果列表（包括成功和失败）
        """
        # 构建已确认观测索引
        confirmed = {
            obs.indicator_code: obs
            for obs in observations
            if obs.status == ValueStatus.CONFIRMED and obs.value is not None
        }

        # 已有的目标指标（不需要派生）
        existing_targets = set(confirmed.keys())

        results = []
        for rule in self.rules:
            # 跳过已有观测的指标
            if rule.target_indicator in existing_targets:
                continue

            # 检查源指标是否齐全
            source_values = {}
            missing_sources = []
            min_confidence = 1.0

            for source_code in rule.source_indicators:
                source_obs = confirmed.get(source_code)
                if source_obs is None or source_obs.value is None:
                    missing_sources.append(source_code)
                else:
                    source_values[source_code] = float(source_obs.value)
                    if source_obs.confidence is not None:
                        min_confidence = min(min_confidence, source_obs.confidence)

            # 源数据不齐全
            if missing_sources:
                results.append(DerivationResult(
                    derived_observation=None,
                    success=False,
                    rule=rule,
                    source_values=source_values,
                    derived_value=None,
                    failure_reason=f"缺少源指标: {', '.join(missing_sources)}"
                ))
                continue

            # 源数据置信度过低
            if min_confidence < rule.min_confidence:
                results.append(DerivationResult(
                    derived_observation=None,
                    success=False,
                    rule=rule,
                    source_values=source_values,
                    derived_value=None,
                    failure_reason=f"源数据置信度过低: {min_confidence:.2f} < {rule.min_confidence}"
                ))
                continue

            # 应用派生公式
            try:
                derived_value = rule.formula(source_values)
            except Exception as e:
                results.append(DerivationResult(
                    derived_observation=None,
                    success=False,
                    rule=rule,
                    source_values=source_values,
                    derived_value=None,
                    failure_reason=f"公式计算错误: {e}"
                ))
                continue

            # 公式返回None（条件不满足）
            if derived_value is None:
                results.append(DerivationResult(
                    derived_observation=None,
                    success=False,
                    rule=rule,
                    source_values=source_values,
                    derived_value=None,
                    failure_reason="公式返回None（分母为0或其他条件不满足）"
                ))
                continue

            # 验证派生值合理性
            if rule.validation is not None and not rule.validation(derived_value):
                results.append(DerivationResult(
                    derived_observation=None,
                    success=False,
                    rule=rule,
                    source_values=source_values,
                    derived_value=derived_value,
                    failure_reason=f"派生值未通过合理性验证: {derived_value}"
                ))
                continue

            # 成功派生
            derived_confidence = min_confidence * 0.9  # 派生值置信度打折
            derived_obs = Observation(
                company_code=company_code,
                company_name=company_name,
                report_year=report_year,
                indicator_code=rule.target_indicator,
                value=derived_value,
                status=ValueStatus.DERIVED,  # 新状态：派生值
                source_type="formula_derived",
                confidence=derived_confidence,
                note=f"从{len(source_values)}个源指标派生: {rule.formula_description}",
                evidence_page=None,
                evidence_url=None,
                evidence_text=None,
                collected_at=datetime.now(timezone.utc).isoformat(),
            )

            results.append(DerivationResult(
                derived_observation=derived_obs,
                success=True,
                rule=rule,
                source_values=source_values,
                derived_value=derived_value,
                failure_reason=None
            ))

        return results

    def derive_batch(
        self,
        observations: list[Observation],
    ) -> tuple[list[Observation], list[DerivationResult]]:
        """批量派生（按公司×年度分组）

        Returns:
            (成功派生的观测列表, 所有派生结果)
        """
        # 按公司×年度分组
        groups: dict[tuple[str, int], tuple[str, list[Observation]]] = {}
        for obs in observations:
            key = (obs.company_code, obs.report_year)
            if key not in groups:
                groups[key] = (obs.company_name, [])
            groups[key][1].append(obs)

        # 逐公司派生
        all_derived = []
        all_results = []

        for (code, year), (name, obs_list) in groups.items():
            results = self.derive_for_company(code, name, year, obs_list)
            all_results.extend(results)

            for result in results:
                if result.success and result.derived_observation is not None:
                    all_derived.append(result.derived_observation)

        return all_derived, all_results
