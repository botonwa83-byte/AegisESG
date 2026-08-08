"""排名分级系统：区分基础排名和高级排名

本模块实现排名的分级访问控制：
- 基础排名（免费）：仅使用已披露数据，disclosed_weight策略
- 高级排名（会员）：使用增强数据（预测+填充），enriched策略

设计原则：
1. 不修改评分算法核心，只是使用不同的输入数据
2. 透明标注数据来源（披露/预测/填充）
3. 支持排名对比和稳定性分析
4. 记录会员等级和访问控制
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from .models import Observation, ValueStatus, CompanyResult
from .scoring import MissingStrategy


class RankingTier(str, Enum):
    """排名等级"""
    BASIC = "basic"  # 基础排名（免费）
    PREMIUM = "premium"  # 高级排名（会员）
    PROFESSIONAL = "professional"  # 专业排名（高级会员，未来扩展）


class DataEnrichmentLevel(str, Enum):
    """数据增强级别"""
    DISCLOSED_ONLY = "disclosed_only"  # 仅已披露数据
    WITH_PREDICTION = "with_prediction"  # +时间序列预测
    WITH_IMPUTATION = "with_imputation"  # +行业均值填充
    FULL_ENRICHMENT = "full_enrichment"  # 全部增强（预测+填充+派生）


@dataclass
class RankingTierConfig:
    """排名等级配置"""
    tier: RankingTier
    name: str  # 等级名称
    description: str  # 等级描述
    enrichment_level: DataEnrichmentLevel  # 数据增强级别
    missing_strategy: MissingStrategy  # 缺失值策略
    allowed_statuses: set[ValueStatus]  # 允许的观测状态
    features: list[str]  # 功能特性
    price_info: str  # 价格信息（用于展示）


# 预定义的排名等级配置
RANKING_TIER_CONFIGS: dict[RankingTier, RankingTierConfig] = {
    RankingTier.BASIC: RankingTierConfig(
        tier=RankingTier.BASIC,
        name="基础排名",
        description="仅使用企业已公开披露的数据，按披露权重计算评分",
        enrichment_level=DataEnrichmentLevel.DISCLOSED_ONLY,
        missing_strategy=MissingStrategy.DISCLOSED_WEIGHT_V1,
        allowed_statuses={ValueStatus.CONFIRMED},
        features=[
            "企业已披露数据",
            "行标权重评分",
            "E/S/G分项得分",
            "行业排名",
            "基础趋势分析",
        ],
        price_info="免费",
    ),

    RankingTier.PREMIUM: RankingTierConfig(
        tier=RankingTier.PREMIUM,
        name="高级排名",
        description="使用增强数据（历史预测+行业填充），提供更全面的企业ESG评估",
        enrichment_level=DataEnrichmentLevel.FULL_ENRICHMENT,
        missing_strategy=MissingStrategy.INDICATOR_NEUTRAL_V1,
        allowed_statuses={
            ValueStatus.CONFIRMED,
            ValueStatus.PREDICTED,
            ValueStatus.IMPUTED,
            ValueStatus.DERIVED,
        },
        features=[
            "✓ 基础排名所有功能",
            "✓ 时间序列预测数据",
            "✓ 行业均值填充",
            "✓ 数据覆盖率提升80%+",
            "✓ 多策略排名对比",
            "✓ 排名稳定性分析",
            "✓ 数据来源透明标注",
            "✓ 详细审计报告",
        ],
        price_info="会员专享",
    ),

    RankingTier.PROFESSIONAL: RankingTierConfig(
        tier=RankingTier.PROFESSIONAL,
        name="专业排名",
        description="包含高级排名全部功能，额外提供API访问和定制化分析（未来扩展）",
        enrichment_level=DataEnrichmentLevel.FULL_ENRICHMENT,
        missing_strategy=MissingStrategy.INDICATOR_NEUTRAL_V1,
        allowed_statuses={
            ValueStatus.CONFIRMED,
            ValueStatus.PREDICTED,
            ValueStatus.IMPUTED,
            ValueStatus.DERIVED,
        },
        features=[
            "✓ 高级排名所有功能",
            "✓ API批量访问",
            "✓ 历史数据下载",
            "✓ 定制化分析报告",
            "✓ 专属技术支持",
        ],
        price_info="企业版",
    ),
}


@dataclass
class RankingComparison:
    """排名对比结果"""
    company_code: str
    company_name: str
    basic_rank: int | None  # 基础排名
    premium_rank: int | None  # 高级排名
    rank_change: int | None  # 排名变化（正数=上升，负数=下降）
    basic_score: float  # 基础得分
    premium_score: float  # 高级得分
    score_change: float  # 得分变化
    basic_coverage: float  # 基础数据覆盖率
    premium_coverage: float  # 高级数据覆盖率
    coverage_improvement: float  # 覆盖率提升


class RankingTierManager:
    """排名分级管理器"""

    def __init__(self):
        self.configs = RANKING_TIER_CONFIGS

    def get_config(self, tier: RankingTier) -> RankingTierConfig:
        """获取排名等级配置"""
        return self.configs[tier]

    def filter_observations_by_tier(
        self,
        observations: list[Observation],
        tier: RankingTier,
    ) -> list[Observation]:
        """根据排名等级过滤观测数据

        Args:
            observations: 全部观测数据
            tier: 排名等级

        Returns:
            过滤后的观测数据
        """
        config = self.get_config(tier)
        allowed_statuses = config.allowed_statuses

        filtered = [
            obs for obs in observations
            if obs.status in allowed_statuses
        ]

        return filtered

    def compare_rankings(
        self,
        basic_results: list[CompanyResult],
        premium_results: list[CompanyResult],
    ) -> list[RankingComparison]:
        """对比基础排名和高级排名

        Args:
            basic_results: 基础排名结果
            premium_results: 高级排名结果

        Returns:
            排名对比列表
        """
        # 构建索引
        basic_dict = {r.company_code: r for r in basic_results}
        premium_dict = {r.company_code: r for r in premium_results}

        # 所有公司
        all_companies = set(basic_dict.keys()) | set(premium_dict.keys())

        comparisons = []
        for company_code in all_companies:
            basic = basic_dict.get(company_code)
            premium = premium_dict.get(company_code)

            if basic is None or premium is None:
                continue  # 跳过只在一个排名中出现的公司

            # 计算排名变化
            basic_rank = basic.rank if basic.rank is not None else 999
            premium_rank = premium.rank if premium.rank is not None else 999
            rank_change = basic_rank - premium_rank  # 正数=排名上升

            comparison = RankingComparison(
                company_code=company_code,
                company_name=basic.company_name,
                basic_rank=basic.rank,
                premium_rank=premium.rank,
                rank_change=rank_change,
                basic_score=basic.total_score,
                premium_score=premium.total_score,
                score_change=premium.total_score - basic.total_score,
                basic_coverage=basic.disclosure_rate,
                premium_coverage=premium.disclosure_rate,
                coverage_improvement=premium.disclosure_rate - basic.disclosure_rate,
            )
            comparisons.append(comparison)

        # 按高级排名排序
        comparisons.sort(key=lambda x: x.premium_rank if x.premium_rank is not None else 999)

        return comparisons

    def generate_tier_summary(
        self,
        tier: RankingTier,
        results: list[CompanyResult],
        observations: list[Observation],
    ) -> dict:
        """生成排名等级摘要

        Args:
            tier: 排名等级
            results: 排名结果
            observations: 观测数据

        Returns:
            摘要字典
        """
        config = self.get_config(tier)

        # 统计观测来源
        status_counts = {}
        for obs in observations:
            status = obs.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

        # 计算平均覆盖率
        avg_coverage = sum(r.disclosure_rate for r in results) / len(results) if results else 0

        # 统计数据增强情况
        enhanced_count = sum(
            1 for obs in observations
            if obs.status in {ValueStatus.PREDICTED, ValueStatus.IMPUTED, ValueStatus.DERIVED}
        )

        summary = {
            "tier": tier.value,
            "tier_name": config.name,
            "description": config.description,
            "enrichment_level": config.enrichment_level.value,
            "missing_strategy": config.missing_strategy.value,
            "company_count": len(results),
            "total_observations": len(observations),
            "observation_by_status": status_counts,
            "enhanced_observations": enhanced_count,
            "enhanced_ratio": enhanced_count / len(observations) if observations else 0,
            "average_coverage_rate": avg_coverage,
            "features": config.features,
            "price_info": config.price_info,
        }

        return summary

    def check_access_permission(
        self,
        user_tier: RankingTier,
        requested_tier: RankingTier,
    ) -> tuple[bool, str | None]:
        """检查用户是否有权限访问请求的排名等级

        Args:
            user_tier: 用户等级
            requested_tier: 请求的排名等级

        Returns:
            (是否有权限, 拒绝原因)
        """
        tier_levels = {
            RankingTier.BASIC: 0,
            RankingTier.PREMIUM: 1,
            RankingTier.PROFESSIONAL: 2,
        }

        user_level = tier_levels[user_tier]
        requested_level = tier_levels[requested_tier]

        if user_level >= requested_level:
            return True, None

        # 拒绝原因
        requested_config = self.get_config(requested_tier)
        reason = f"访问{requested_config.name}需要升级会员等级（{requested_config.price_info}）"

        return False, reason


@dataclass
class RankingExportConfig:
    """排名导出配置"""
    tier: RankingTier
    include_details: bool = False  # 是否包含详细指标
    include_data_source: bool = False  # 是否包含数据来源标注
    top_n: int | None = None  # 只导出前N名（None=全部）
    format: Literal["csv", "json", "html"] = "csv"


def export_ranking_with_tier(
    results: list[CompanyResult],
    observations: list[Observation],
    config: RankingExportConfig,
) -> dict:
    """根据等级配置导出排名

    Args:
        results: 排名结果
        observations: 观测数据
        config: 导出配置

    Returns:
        导出数据字典
    """
    tier_config = RANKING_TIER_CONFIGS[config.tier]

    # 过滤前N名
    if config.top_n is not None:
        results = results[:config.top_n]

    # 基础字段
    export_data = {
        "tier": tier_config.name,
        "tier_level": config.tier.value,
        "description": tier_config.description,
        "companies": [],
    }

    # 构建观测索引（用于数据来源标注）
    if config.include_data_source:
        obs_dict = {}
        for obs in observations:
            key = (obs.company_code, obs.indicator_code)
            obs_dict[key] = obs

    for result in results:
        company_data = {
            "rank": result.rank,
            "company_code": result.company_code,
            "company_name": result.company_name,
            "total_score": round(result.total_score, 2),
            "grade": result.grade,
            "dimension_scores": {
                "E": round(result.dimension_scores.get("E", 0), 2),
                "S": round(result.dimension_scores.get("S", 0), 2),
                "G": round(result.dimension_scores.get("G", 0), 2),
            },
            "disclosure_rate": round(result.disclosure_rate * 100, 1),
        }

        # 高级功能：包含详细指标
        if config.include_details and config.tier != RankingTier.BASIC:
            company_data["indicator_details"] = [
                {
                    "code": detail.indicator_code,
                    "raw_value": detail.raw_value,
                    "score": round(detail.normalized_score, 2),
                    "weight": detail.weight,
                }
                for detail in result.details
            ]

        # 高级功能：数据来源标注
        if config.include_data_source and config.tier != RankingTier.BASIC:
            data_sources = {}
            for detail in result.details:
                key = (result.company_code, detail.indicator_code)
                obs = obs_dict.get(key)
                if obs:
                    data_sources[detail.indicator_code] = {
                        "status": obs.status.value,
                        "source_type": obs.source_type,
                        "confidence": round(obs.confidence, 2),
                    }
            company_data["data_sources"] = data_sources

        export_data["companies"].append(company_data)

    return export_data
