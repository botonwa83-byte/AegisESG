"""行业均值填充引擎：使用行业基准填充缺失指标值

本模块计算行业基准参数（均值、中位数、标准差），并对缺失指标使用行业均值填充。
适用于行业特征明显的指标（如能源强度、安全投入等）。

填充规则：
1. 仅填充status=MISSING或不存在的观测
2. 使用一级或二级行业均值（根据样本量）
3. 所有填充值标注为IMPUTED状态
4. 记录行业样本量和标准差用于置信度评估

重要约束：
- 填充值仅用于研究排名，不进入正式排名
- 不修改已确认的观测
- 不影响原有评分算法
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import Observation, ValueStatus


@dataclass
class IndustryBenchmark:
    """行业基准参数"""
    industry: str  # 行业分类
    indicator_code: str  # 指标代码
    sample_count: int  # 样本量
    mean: float  # 均值
    median: float  # 中位数
    stdev: float  # 标准差
    min_value: float  # 最小值
    max_value: float  # 最大值

    @property
    def cv(self) -> float:
        """变异系数"""
        if self.mean == 0:
            return float('inf')
        return abs(self.stdev / self.mean)

    @property
    def confidence(self) -> float:
        """置信度（基于样本量和CV）"""
        # 样本量越大越好
        sample_factor = min(1.0, self.sample_count / 30)  # 30个样本达到1.0
        # CV越小越好
        cv_factor = max(0.3, min(1.0, 1 - self.cv / 2))
        return sample_factor * cv_factor * 0.7  # 最高0.7（低于实际披露）


@dataclass
class ImputationResult:
    """填充结果"""
    imputed_observation: Observation | None
    success: bool
    benchmark: IndustryBenchmark | None
    failure_reason: str | None = None


# 行业分类映射（一级和二级）
INDUSTRY_MAPPING = {
    # 一级分类
    "coal": "煤炭",
    "oil_gas": "油气",
    "power": "电力",
    "renewable": "新能源",

    # 二级分类
    "coal_mining": "煤炭开采",
    "coal_chemical": "煤化工",
    "oil_extraction": "石油开采",
    "natural_gas": "天然气",
    "refining": "油气炼化",
    "thermal_power": "火电",
    "hydro_power": "水电",
    "nuclear_power": "核电",
    "wind_power": "风电",
    "solar_power": "光伏",
    "other_renewable": "其他新能源",
}


# 允许行业填充的指标白名单（行业特征明显）
IMPUTATION_WHITELIST = {
    # 环境强度类（行业差异大）
    "Q_E_ENERGY_INTENSITY",
    "Q_E_WATER_INTENSITY",
    "Q_E_GHG_INTENSITY",
    "Q_E_SO2_INTENSITY",
    "Q_E_NOX_INTENSITY",
    "Q_E_SOLID_WASTE_INTENSITY",
    "Q_E_HAZ_WASTE_INTENSITY",
    "Q_E_WASTEWATER_INTENSITY",
    "Q_E_PM_INTENSITY",

    # 社会投入类（行业相关）
    "Q_S_SAFETY_INVEST_RATE",
    "Q_S_ENV_INVEST_RATE",
    "Q_S_RD_RATE",

    # 部分治理指标（行业特征明显）
    "Q_G_ASSET_TURNOVER",
    "Q_G_CURRENT_ASSET_TURNOVER",
}

# 禁止填充的指标黑名单（公司个体差异大）
IMPUTATION_BLACKLIST = {
    # 所有定性指标（公司个性化）
    # 治理结构指标
    "Q_G_DEBT_ASSET_RATE",
    "Q_G_ROE",
    "Q_G_ROA",

    # 分红决策
    "Q_S_DIVIDEND_PER_SHARE",

    # 人均指标（公司差异大）
    "Q_S_PAY_PER_EMPLOYEE",
    "Q_S_BENEFIT_PER_EMPLOYEE",
    "Q_S_EDU_PER_EMPLOYEE",
}


class IndustryImputationEngine:
    """行业均值填充引擎"""

    def __init__(
        self,
        min_industry_sample: int = 10,  # 最少行业样本量
        use_median: bool = False,  # 使用中位数而非均值（更稳健）
        imputation_whitelist: set[str] | None = None,
    ):
        self.min_industry_sample = min_industry_sample
        self.use_median = use_median
        self.imputation_whitelist = imputation_whitelist or IMPUTATION_WHITELIST

    def build_industry_benchmarks(
        self,
        observations: list[Observation],
        industry_mapping: dict[str, str],  # company_code -> industry
    ) -> dict[tuple[str, str], IndustryBenchmark]:
        """构建行业基准参数

        Args:
            observations: 已确认的观测数据
            industry_mapping: 公司代码到行业的映射

        Returns:
            (industry, indicator_code) -> IndustryBenchmark
        """
        # 按行业×指标分组
        groups: dict[tuple[str, str], list[float]] = defaultdict(list)

        for obs in observations:
            if obs.status != ValueStatus.CONFIRMED or obs.value is None:
                continue

            industry = industry_mapping.get(obs.company_code)
            if industry is None:
                continue

            key = (industry, obs.indicator_code)
            groups[key].append(float(obs.value))

        # 计算基准参数
        benchmarks = {}
        for (industry, indicator_code), values in groups.items():
            if len(values) < self.min_industry_sample:
                continue  # 样本量不足

            benchmark = IndustryBenchmark(
                industry=industry,
                indicator_code=indicator_code,
                sample_count=len(values),
                mean=statistics.mean(values),
                median=statistics.median(values),
                stdev=statistics.stdev(values) if len(values) >= 2 else 0.0,
                min_value=min(values),
                max_value=max(values),
            )
            benchmarks[(industry, indicator_code)] = benchmark

        return benchmarks

    def impute_one(
        self,
        company_code: str,
        company_name: str,
        report_year: int,
        indicator_code: str,
        industry: str,
        benchmarks: dict[tuple[str, str], IndustryBenchmark],
    ) -> ImputationResult:
        """填充单个观测

        Args:
            company_code: 公司代码
            company_name: 公司名称
            report_year: 报告年度
            indicator_code: 指标代码
            industry: 行业分类
            benchmarks: 行业基准字典

        Returns:
            填充结果
        """
        # 检查白名单
        if indicator_code not in self.imputation_whitelist:
            return ImputationResult(
                imputed_observation=None,
                success=False,
                benchmark=None,
                failure_reason=f"指标不在白名单: {indicator_code}"
            )

        # 检查黑名单
        if indicator_code in IMPUTATION_BLACKLIST:
            return ImputationResult(
                imputed_observation=None,
                success=False,
                benchmark=None,
                failure_reason=f"指标在黑名单: {indicator_code}"
            )

        # 查找行业基准
        benchmark = benchmarks.get((industry, indicator_code))
        if benchmark is None:
            return ImputationResult(
                imputed_observation=None,
                success=False,
                benchmark=None,
                failure_reason=f"无行业基准: {industry} x {indicator_code}"
            )

        # 选择填充值（均值或中位数）
        imputed_value = benchmark.median if self.use_median else benchmark.mean

        # 创建填充观测
        imputed_obs = Observation(
            company_code=company_code,
            company_name=company_name,
            report_year=report_year,
            indicator_code=indicator_code,
            value=imputed_value,
            status=ValueStatus.IMPUTED,  # 需要添加到models.py
            source_type="industry_mean_imputed",
            confidence=benchmark.confidence,
            note=f"使用{industry}行业{'中位数' if self.use_median else '均值'}填充(n={benchmark.sample_count}, CV={benchmark.cv:.3f})",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )

        return ImputationResult(
            imputed_observation=imputed_obs,
            success=True,
            benchmark=benchmark,
            failure_reason=None
        )

    def impute_batch(
        self,
        observations: list[Observation],
        industry_mapping: dict[str, str],
        target_year: int,
        target_indicators: set[str] | None = None,
    ) -> tuple[list[Observation], list[ImputationResult], dict[tuple[str, str], IndustryBenchmark]]:
        """批量填充

        Args:
            observations: 观测数据（用于计算基准）
            industry_mapping: 公司代码到行业的映射
            target_year: 目标年份
            target_indicators: 目标指标集合（None表示全部白名单指标）

        Returns:
            (成功填充的观测列表, 所有填充结果, 行业基准字典)
        """
        # 构建行业基准
        benchmarks = self.build_industry_benchmarks(observations, industry_mapping)

        # 找出需要填充的(公司, 指标)
        target_year_obs = [obs for obs in observations if obs.report_year == target_year]

        # 已有覆盖
        existing_coverage = {
            (obs.company_code, obs.indicator_code)
            for obs in target_year_obs
            if obs.status == ValueStatus.CONFIRMED and obs.value is not None
        }

        # 所有公司
        all_companies = {obs.company_code: obs.company_name for obs in target_year_obs}

        # 目标指标
        if target_indicators is None:
            target_indicators = self.imputation_whitelist

        # 批量填充
        all_imputed = []
        all_results = []

        for company_code, company_name in all_companies.items():
            industry = industry_mapping.get(company_code)
            if industry is None:
                continue  # 无行业分类

            for indicator_code in target_indicators:
                # 跳过已有覆盖
                if (company_code, indicator_code) in existing_coverage:
                    continue

                result = self.impute_one(
                    company_code=company_code,
                    company_name=company_name,
                    report_year=target_year,
                    indicator_code=indicator_code,
                    industry=industry,
                    benchmarks=benchmarks,
                )
                all_results.append(result)

                if result.success and result.imputed_observation is not None:
                    all_imputed.append(result.imputed_observation)

        return all_imputed, all_results, benchmarks
