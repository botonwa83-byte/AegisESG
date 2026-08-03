from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from .methodology import Methodology
from .models import (
    CompanyResult,
    Direction,
    Indicator,
    IndicatorKind,
    IndicatorResult,
    Observation,
    ValueStatus,
)


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


@dataclass(frozen=True)
class PopulationStats:
    count: int
    mean: float
    stddev: float


class MissingStrategy(str, Enum):
    """Versioned missing-value behavior used by ranking modes."""

    LEGACY_ZERO_V1 = "legacy_zero_v1"
    INDICATOR_NEUTRAL_V1 = "indicator_neutral_v1"
    DISCLOSED_WEIGHT_V1 = "disclosed_weight_v1"


class ScoringEngine:
    """可复现评分引擎。

    环境、社会定量指标采用样本Z分数的标准正态CDF；治理指标在提供
    `benchmark` 时采用以优秀值为峰值的单/双侧正态衰减。官方报告未
    公开具体均值、方差、极值剔除阈值及优秀值，本实现会把本次样本统计
    写入明细，使结果可审计，但不宣称复刻第三方机构的未披露参数。
    """

    def __init__(self, methodology: Methodology):
        self.methodology = methodology

    def evaluate(
        self, observations: list[Observation],
        missing_strategy: MissingStrategy | str = MissingStrategy.LEGACY_ZERO_V1,
    ) -> list[CompanyResult]:
        strategy = MissingStrategy(missing_strategy)
        years = {item.report_year for item in observations}
        if len(years) > 1:
            raise ValueError("一次评分批次只能包含一个报告期")
        confirmed = [
            o for o in observations
            if o.status == ValueStatus.CONFIRMED and o.value is not None
        ]
        stats = self._population_stats(confirmed)
        companies: dict[tuple[str, int], tuple[str, dict[str, Observation]]] = {}
        for obs in observations:
            key = (obs.company_code, obs.report_year)
            if key not in companies:
                companies[key] = (obs.company_name, {})
            companies[key][1][obs.indicator_code] = obs

        results = [
            self._evaluate_company(code, name, year, values, stats, strategy)
            for (code, year), (name, values) in companies.items()
        ]
        results.sort(key=lambda x: (-x.total_score, x.company_code))
        previous_score: float | None = None
        previous_rank = 0
        for result in results:
            rounded = round(result.total_score, 2)
            if previous_score is None or rounded != previous_score:
                previous_rank += 1
                previous_score = rounded
            result.rank = previous_rank
        return results

    def _population_stats(self, observations: list[Observation]) -> dict[str, PopulationStats]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for obs in observations:
            grouped[obs.indicator_code].append(float(obs.value))
        result: dict[str, PopulationStats] = {}
        for code, raw_values in grouped.items():
            values = _winsorize(raw_values)
            mean = statistics.fmean(values)
            stddev = statistics.pstdev(values) if len(values) > 1 else 0.0
            result[code] = PopulationStats(len(values), mean, stddev)
        return result

    def _evaluate_company(
        self,
        code: str,
        name: str,
        year: int,
        observations: dict[str, Observation],
        stats: dict[str, PopulationStats],
        missing_strategy: MissingStrategy,
    ) -> CompanyResult:
        details: list[IndicatorResult] = []
        dimension_weighted = defaultdict(float)
        dimension_max = defaultdict(float)
        kind_scores = defaultdict(float)
        kind_confirmed_weight = defaultdict(float)
        kind_total_weight = defaultdict(float)
        dimension_confirmed_weight = defaultdict(float)
        confirmed_count = 0

        for indicator in self.methodology.indicators:
            obs = observations.get(indicator.code)
            status = obs.status if obs else ValueStatus.MISSING
            raw = obs.value if obs else None
            if status == ValueStatus.CONFIRMED and raw is not None:
                confirmed_count += 1
                normalized = self._score_value(indicator, float(raw), stats.get(indicator.code))
                kind_confirmed_weight[indicator.kind] += indicator.weight
                dimension_confirmed_weight[(indicator.kind, indicator.dimension)] += indicator.weight
            elif status == ValueStatus.NOT_APPLICABLE:
                normalized = 0.0
            elif missing_strategy == MissingStrategy.INDICATOR_NEUTRAL_V1:
                normalized = 50.0
            else:
                normalized = 0.0
            weighted = normalized * indicator.weight / 100.0
            kind_scores[indicator.kind] += weighted
            kind_total_weight[indicator.kind] += indicator.weight
            dimension_weighted[(indicator.kind, indicator.dimension)] += weighted
            dimension_max[(indicator.kind, indicator.dimension)] += indicator.weight
            stat = stats.get(indicator.code)
            details.append(IndicatorResult(
                indicator_code=indicator.code,
                raw_value=raw,
                normalized_score=round(normalized, 4),
                weighted_score=round(weighted, 4),
                weight=indicator.weight,
                status=status,
                population_count=stat.count if stat else 0,
                mean=round(stat.mean, 6) if stat else None,
                stddev=round(stat.stddev, 6) if stat else None,
                benchmark=indicator.benchmark,
            ))

        if missing_strategy == MissingStrategy.DISCLOSED_WEIGHT_V1:
            for kind in IndicatorKind:
                confirmed_weight = kind_confirmed_weight[kind]
                kind_scores[kind] = (
                    kind_scores[kind] * kind_total_weight[kind] / confirmed_weight
                    if confirmed_weight else 0.0
                )
            for key, score in tuple(dimension_weighted.items()):
                confirmed_weight = dimension_confirmed_weight[key]
                dimension_weighted[key] = (
                    score * dimension_max[key] / confirmed_weight if confirmed_weight else 0.0
                )

        quantitative = kind_scores[IndicatorKind.QUANTITATIVE]
        qualitative = kind_scores[IndicatorKind.QUALITATIVE]
        total = (
            quantitative * self.methodology.quantitative_ratio
            + qualitative * self.methodology.qualitative_ratio
        )
        dimensions = {}
        for dimension in ("E", "S", "G"):
            q = dimension_weighted[(IndicatorKind.QUANTITATIVE, dimension)]
            x = dimension_weighted[(IndicatorKind.QUALITATIVE, dimension)]
            dimensions[dimension] = round(
                q * self.methodology.quantitative_ratio
                + x * self.methodology.qualitative_ratio,
                2,
            )
        return CompanyResult(
            company_code=code,
            company_name=name,
            report_year=year,
            quantitative_score=round(quantitative, 2),
            qualitative_score=round(qualitative, 2),
            total_score=round(total, 2),
            dimension_scores=dimensions,
            disclosure_rate=round(confirmed_count / len(self.methodology.indicators) * 100, 2),
            details=details,
        )

    def _score_value(
        self,
        indicator: Indicator,
        value: float,
        stats: PopulationStats | None,
    ) -> float:
        if indicator.kind == IndicatorKind.QUALITATIVE:
            return value if value in (0, 20, 50, 80, 100) else min(100.0, max(0.0, value))
        if not stats or stats.stddev <= 1e-12:
            return 50.0
        z = (value - stats.mean) / stats.stddev
        if indicator.benchmark is not None:
            distance = (value - indicator.benchmark) / stats.stddev
            if indicator.direction == Direction.POSITIVE and value >= indicator.benchmark:
                return 100.0
            if indicator.direction == Direction.NEGATIVE and value <= indicator.benchmark:
                return 100.0
            return 100.0 * math.exp(-0.5 * distance * distance)
        if indicator.direction == Direction.NEGATIVE:
            return 100.0 * (1.0 - normal_cdf(z))
        if indicator.direction == Direction.BIDIRECTIONAL:
            return 100.0 * math.exp(-0.5 * z * z)
        return 100.0 * normal_cdf(z)


def _winsorize(values: list[float], lower: float = 0.01, upper: float = 0.99) -> list[float]:
    if len(values) < 20:
        return list(values)
    ordered = sorted(values)
    lo = _quantile(ordered, lower)
    hi = _quantile(ordered, upper)
    return [min(hi, max(lo, value)) for value in values]


def _quantile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    left = math.floor(position)
    right = math.ceil(position)
    if left == right:
        return ordered[left]
    fraction = position - left
    return ordered[left] * (1.0 - fraction) + ordered[right] * fraction
