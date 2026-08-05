from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import Enum

from .grade import GradeFlags, map_esg_grade
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
    thin_population: bool = False


DEFAULT_MINIMUM_POPULATION = 20


class MissingStrategy(str, Enum):
    """Versioned missing-value behavior used by ranking modes."""

    LEGACY_ZERO_V1 = "legacy_zero_v1"
    INDICATOR_NEUTRAL_V1 = "indicator_neutral_v1"
    DISCLOSED_WEIGHT_V1 = "disclosed_weight_v1"


@dataclass
class ScoringCache:
    """Exact, in-memory scoring state used for dependency-scoped recomputation."""

    results: dict[tuple[str, int], CompanyResult]
    stats: dict[str, PopulationStats]
    observations: dict[tuple[str, int], tuple[str, dict[str, Observation]]]
    companies_by_indicator: dict[str, set[tuple[str, int]]]
    missing_strategy: MissingStrategy
    company_flags: dict[str, GradeFlags] = field(default_factory=dict)


class ScoringEngine:
    """可复现评分引擎。

    环境、社会定量指标采用样本Z分数的标准正态CDF；治理指标在提供
    `benchmark` 时采用以优秀值为峰值的单/双侧正态衰减。官方报告未
    公开具体均值、方差、极值剔除阈值及优秀值，本实现会把本次样本统计
    写入明细，使结果可审计，但不宣称复刻第三方机构的未披露参数。
    """

    def __init__(
        self,
        methodology: Methodology,
        *,
        minimum_population: int = DEFAULT_MINIMUM_POPULATION,
    ):
        self.methodology = methodology
        self.minimum_population = int(minimum_population)

    def evaluate(
        self, observations: list[Observation],
        missing_strategy: MissingStrategy | str = MissingStrategy.LEGACY_ZERO_V1,
        company_flags: dict[str, GradeFlags] | None = None,
        *,
        universe_codes: set[str] | None = None,
        minimum_population: int | None = None,
    ) -> list[CompanyResult]:
        """Score companies using client-aligned industry baselines.

        When ``universe_codes`` is set (frozen energy sample), population μ/σ for
        each quantitative indicator is computed only from confirmed disclosures
        inside that universe — matching “同指标、样本池内已披露企业”测算基准.
        Undisclosed values never enter the baseline. Thin populations
        (n < minimum_population) are still scored but flagged for audit gates.
        """
        strategy = MissingStrategy(missing_strategy)
        flags = company_flags or {}
        threshold = self.minimum_population if minimum_population is None else int(minimum_population)
        years = {item.report_year for item in observations}
        if len(years) > 1:
            raise ValueError("一次评分批次只能包含一个报告期")
        scoped = (
            [o for o in observations if o.company_code in universe_codes]
            if universe_codes is not None else list(observations)
        )
        confirmed = [
            o for o in scoped
            if o.status == ValueStatus.CONFIRMED and o.value is not None
        ]
        stats = self._population_stats(confirmed, minimum_population=threshold)
        companies: dict[tuple[str, int], tuple[str, dict[str, Observation]]] = {}
        for obs in scoped:
            key = (obs.company_code, obs.report_year)
            if key not in companies:
                companies[key] = (obs.company_name, {})
            companies[key][1][obs.indicator_code] = obs

        results = [
            self._evaluate_company(code, name, year, values, stats, strategy, flags.get(code))
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

    def build_cache(
        self, observations: list[Observation],
        missing_strategy: MissingStrategy | str = MissingStrategy.LEGACY_ZERO_V1,
        company_flags: dict[str, GradeFlags] | None = None,
    ) -> ScoringCache:
        strategy = MissingStrategy(missing_strategy)
        flags = company_flags or {}
        confirmed = [o for o in observations if o.status == ValueStatus.CONFIRMED and o.value is not None]
        stats = self._population_stats(confirmed)
        companies: dict[tuple[str, int], tuple[str, dict[str, Observation]]] = {}
        by_indicator: dict[str, set[tuple[str, int]]] = defaultdict(set)
        for obs in observations:
            key = (obs.company_code, obs.report_year)
            if key not in companies:
                companies[key] = (obs.company_name, {})
            companies[key][1][obs.indicator_code] = obs
            by_indicator[obs.indicator_code].add(key)
        results = self.evaluate(observations, strategy, flags)
        return ScoringCache(
            results={(item.company_code, item.report_year): item for item in results},
            stats=stats, observations=companies, companies_by_indicator=dict(by_indicator),
            missing_strategy=strategy, company_flags=dict(flags),
        )

    def evaluate_from_cache(
        self, cache: ScoringCache, affected_indicators: set[str],
    ) -> list[CompanyResult]:
        """Recompute the affected indicator population and rerank cached company scores."""
        affected_companies = set().union(
            *(cache.companies_by_indicator.get(code, set()) for code in affected_indicators)
        ) if affected_indicators else set()
        results = {
            key: value for key, value in cache.results.items()
            if key not in affected_companies
        }
        for key in affected_companies:
            name, values = cache.observations[key]
            results[key] = self._evaluate_company(
                key[0], name, key[1], values, cache.stats, cache.missing_strategy,
                cache.company_flags.get(key[0]),
            )
        ranked = sorted(results.values(), key=lambda item: (-item.total_score, item.company_code))
        previous_score: float | None = None
        previous_rank = 0
        for result in ranked:
            rounded = round(result.total_score, 2)
            if previous_score is None or rounded != previous_score:
                previous_rank += 1
                previous_score = rounded
            result.rank = previous_rank
        return ranked

    def apply_cache_changes(
        self, cache: ScoringCache, changes: list[Observation],
    ) -> tuple[list[CompanyResult], dict]:
        """Atomically replace observations, invalidate exact stats, and rerank."""
        if not changes:
            raise ValueError("增量事务至少包含一条观测变更")
        identities = [(item.company_code, item.report_year, item.indicator_code) for item in changes]
        if len(identities) != len(set(identities)):
            raise ValueError("同一公司、年度和指标在事务中只能变更一次")
        existing_years = {year for _, year in cache.observations}
        if existing_years and any(item.report_year not in existing_years for item in changes):
            raise ValueError("增量事务不能混入新的报告期")

        staged_observations = {
            key: (name, dict(values)) for key, (name, values) in cache.observations.items()
        }
        staged_by_indicator = {
            code: set(companies) for code, companies in cache.companies_by_indicator.items()
        }
        affected_indicators = {item.indicator_code for item in changes}
        affected_companies = set().union(
            *(staged_by_indicator.get(code, set()) for code in affected_indicators)
        )
        for item in changes:
            key = (item.company_code, item.report_year)
            if key not in staged_observations:
                staged_observations[key] = (item.company_name, {})
            staged_observations[key][1][item.indicator_code] = item
            staged_by_indicator.setdefault(item.indicator_code, set()).add(key)
            affected_companies.add(key)

        staged_stats = dict(cache.stats)
        for code in affected_indicators:
            confirmed = [
                values[code] for _, values in staged_observations.values()
                if code in values and values[code].status == ValueStatus.CONFIRMED
                and values[code].value is not None
            ]
            replacement = self._population_stats(confirmed)
            if code in replacement:
                staged_stats[code] = replacement[code]
            else:
                staged_stats.pop(code, None)

        staged_results = {
            key: value for key, value in cache.results.items() if key not in affected_companies
        }
        for key, result in tuple(staged_results.items()):
            details = []
            changed_metadata = False
            for detail in result.details:
                if detail.indicator_code not in affected_indicators:
                    details.append(detail)
                    continue
                stat = staged_stats.get(detail.indicator_code)
                details.append(replace(
                    detail,
                    population_count=stat.count if stat else 0,
                    mean=round(stat.mean, 6) if stat else None,
                    stddev=round(stat.stddev, 6) if stat else None,
                    thin_population=bool(stat.thin_population) if stat else True,
                ))
                changed_metadata = True
            if changed_metadata:
                staged_results[key] = replace(result, details=details)
        for key in affected_companies:
            name, values = staged_observations[key]
            staged_results[key] = self._evaluate_company(
                key[0], name, key[1], values, staged_stats, cache.missing_strategy,
                cache.company_flags.get(key[0]),
            )
        ranked = sorted(staged_results.values(), key=lambda item: (-item.total_score, item.company_code))
        previous_score: float | None = None
        previous_rank = 0
        for result in ranked:
            rounded = round(result.total_score, 2)
            if previous_score is None or rounded != previous_score:
                previous_rank += 1
                previous_score = rounded
            result.rank = previous_rank

        cache.observations = staged_observations
        cache.companies_by_indicator = staged_by_indicator
        cache.stats = staged_stats
        cache.results = staged_results
        return ranked, {
            "transaction_version": "scoring-cache-change-v1",
            "change_count": len(changes),
            "affected_indicators": sorted(affected_indicators),
            "affected_company_count": len(affected_companies),
            "committed": True,
        }

    def _population_stats(
        self,
        observations: list[Observation],
        *,
        minimum_population: int | None = None,
    ) -> dict[str, PopulationStats]:
        threshold = self.minimum_population if minimum_population is None else int(minimum_population)
        grouped: dict[str, list[float]] = defaultdict(list)
        for obs in observations:
            grouped[obs.indicator_code].append(float(obs.value))
        result: dict[str, PopulationStats] = {}
        for code, raw_values in grouped.items():
            values = _winsorize(raw_values)
            mean = statistics.fmean(values)
            stddev = statistics.pstdev(values) if len(values) > 1 else 0.0
            result[code] = PopulationStats(
                len(values), mean, stddev,
                thin_population=len(values) < threshold,
            )
        return result

    def _evaluate_company(
        self,
        code: str,
        name: str,
        year: int,
        observations: dict[str, Observation],
        stats: dict[str, PopulationStats],
        missing_strategy: MissingStrategy,
        flags: GradeFlags | None = None,
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
                thin_population=bool(stat.thin_population) if stat else True,
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
        disclosure_rate = round(confirmed_count / len(self.methodology.indicators) * 100, 2)
        total_score = round(total, 2)
        grade = map_esg_grade(total_score, disclosure_rate, flags)
        return CompanyResult(
            company_code=code,
            company_name=name,
            report_year=year,
            quantitative_score=round(quantitative, 2),
            qualitative_score=round(qualitative, 2),
            total_score=total_score,
            dimension_scores=dimensions,
            disclosure_rate=disclosure_rate,
            details=details,
            grade=grade.grade,
            grade_reason=grade.reason,
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


def build_population_baseline_report(
    observations: list[Observation],
    methodology: Methodology,
    *,
    universe_codes: set[str] | None = None,
    expected_companies: int = 632,
    minimum_population: int = DEFAULT_MINIMUM_POPULATION,
) -> dict:
    """Audit per-indicator disclosed population used for industry baselines."""
    scoped = (
        [o for o in observations if o.company_code in universe_codes]
        if universe_codes is not None else list(observations)
    )
    observed_company_count = len({o.company_code for o in scoped})
    universe_company_count = (
        len(universe_codes) if universe_codes is not None else observed_company_count
    )
    confirmed = [
        o for o in scoped
        if o.status == ValueStatus.CONFIRMED and o.value is not None
    ]
    stats = ScoringEngine(methodology, minimum_population=minimum_population)._population_stats(
        confirmed, minimum_population=minimum_population,
    )
    rows = []
    for indicator in methodology.quantitative:
        stat = stats.get(indicator.code)
        count = stat.count if stat else 0
        rows.append({
            "indicator_code": indicator.code,
            "name": indicator.name,
            "weight": indicator.weight,
            "key_indicator": bool(indicator.key_indicator),
            "disclosed_company_count": count,
            "universe_company_count": universe_company_count,
            "observed_company_count": observed_company_count,
            "expected_company_count": expected_companies,
            "disclosure_rate_in_universe": (
                round(count / universe_company_count * 100, 2) if universe_company_count else 0.0
            ),
            "mean": None if not stat else round(stat.mean, 6),
            "stddev": None if not stat else round(stat.stddev, 6),
            "thin_population": True if not stat else bool(stat.thin_population),
            "baseline_usable_for_formal": count >= minimum_population,
        })
    rows.sort(key=lambda item: (item["disclosed_company_count"], item["indicator_code"]))
    thin = [row["indicator_code"] for row in rows if row["thin_population"]]
    return {
        "baseline_version": "universe-disclosed-population-v1",
        "policy": "industry_baseline_from_disclosed_in_universe_only",
        "expected_companies": expected_companies,
        "universe_company_count": universe_company_count,
        "observed_company_count": observed_company_count,
        "universe_codes_provided": universe_codes is not None,
        "minimum_population_threshold": minimum_population,
        "quantitative_indicator_count": len(rows),
        "thin_population_indicator_count": len(thin),
        "thin_population_indicator_codes": thin,
        "minimum_population_gate_passed": not thin,
        "formal_baseline_ready": (
            universe_codes is not None
            and universe_company_count >= expected_companies
            and not thin
        ),
        "indicators": rows,
        "notice": (
            "基准仅使用宇宙内已披露观测；未披露不进μ/σ。"
            "主体未达632或存在薄样本时不得宣称正式行业基准。"
        ),
    }
