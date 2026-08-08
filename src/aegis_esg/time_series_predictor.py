"""时间序列预测引擎：使用历史数据预测缺失指标值

本模块通过2022-2024年历史观测数据，预测2025年缺失的指标值。
适用于历史稳定、同比波动小的指标。

预测方法：
1. 线性趋势外推：适用于单调变化（如排放强度逐年下降）
2. 移动平均：适用于波动稳定的指标
3. 同比增长率：适用于规模指标

所有预测值标注为PREDICTED状态，仅用于研究排名。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .models import Observation, ValueStatus


class PredictionMethod(str, Enum):
    """预测方法"""
    LINEAR_TREND = "linear_trend"  # 线性趋势外推
    MOVING_AVERAGE = "moving_average"  # 移动平均
    YOY_GROWTH = "yoy_growth"  # 同比增长率
    LAST_VALUE = "last_value"  # 使用最近一年值（保守策略）


@dataclass
class HistoricalSeries:
    """历史时间序列"""
    company_code: str
    company_name: str
    indicator_code: str
    years: list[int]  # 年份列表（升序）
    values: list[float]  # 对应的值

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        return statistics.mean(self.values)

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.values) if len(self.values) >= 2 else 0.0

    @property
    def cv(self) -> float:
        """变异系数（标准差/均值）"""
        if self.mean == 0:
            return float('inf')
        return abs(self.stdev / self.mean)

    @property
    def is_monotonic_increasing(self) -> bool:
        """是否单调递增"""
        return all(v2 >= v1 for v1, v2 in zip(self.values, self.values[1:]))

    @property
    def is_monotonic_decreasing(self) -> bool:
        """是否单调递减"""
        return all(v2 <= v1 for v1, v2 in zip(self.values, self.values[1:]))


@dataclass
class PredictionResult:
    """预测结果"""
    predicted_observation: Observation | None
    success: bool
    method: PredictionMethod | None
    confidence: float  # 0.0-1.0
    historical_series: HistoricalSeries
    predicted_value: float | None
    failure_reason: str | None = None


class TimeSeriesPredictor:
    """时间序列预测器"""

    def __init__(
        self,
        min_historical_points: int = 2,
        max_cv: float = 0.5,  # 最大变异系数（超过则认为不稳定）
        enable_auto_method_selection: bool = True,
    ):
        self.min_historical_points = min_historical_points
        self.max_cv = max_cv
        self.enable_auto_method_selection = enable_auto_method_selection

    def build_historical_series(
        self,
        observations: list[Observation],
        target_year: int,
    ) -> dict[tuple[str, str], HistoricalSeries]:
        """从观测数据构建历史时间序列

        Args:
            observations: 历史观测数据（应包含target_year之前的年份）
            target_year: 目标预测年份

        Returns:
            (company_code, indicator_code) -> HistoricalSeries
        """
        # 按公司×指标分组
        groups: dict[tuple[str, str], dict[int, float]] = {}
        names: dict[str, str] = {}

        for obs in observations:
            # 只使用target_year之前的确认观测
            if obs.report_year >= target_year:
                continue
            if obs.status != ValueStatus.CONFIRMED or obs.value is None:
                continue

            key = (obs.company_code, obs.indicator_code)
            if key not in groups:
                groups[key] = {}

            # 同一年有多个观测时，取最新的
            groups[key][obs.report_year] = float(obs.value)
            names[obs.company_code] = obs.company_name

        # 构建时间序列
        series_dict = {}
        for (company_code, indicator_code), year_values in groups.items():
            sorted_items = sorted(year_values.items())  # 按年份排序
            years = [year for year, _ in sorted_items]
            values = [value for _, value in sorted_items]

            series = HistoricalSeries(
                company_code=company_code,
                company_name=names.get(company_code, ""),
                indicator_code=indicator_code,
                years=years,
                values=values,
            )
            series_dict[(company_code, indicator_code)] = series

        return series_dict

    def select_method(self, series: HistoricalSeries) -> PredictionMethod:
        """自动选择预测方法

        规则：
        1. 单调趋势 → 线性趋势
        2. CV < 0.2 → 移动平均（稳定）
        3. CV < 0.5 → 同比增长率
        4. 其他 → 使用最近一年值
        """
        if series.is_monotonic_increasing or series.is_monotonic_decreasing:
            return PredictionMethod.LINEAR_TREND

        if series.cv < 0.2:
            return PredictionMethod.MOVING_AVERAGE

        if series.cv < self.max_cv:
            return PredictionMethod.YOY_GROWTH

        return PredictionMethod.LAST_VALUE

    def predict_linear_trend(self, series: HistoricalSeries, target_year: int) -> tuple[float, float]:
        """线性趋势外推

        Returns:
            (predicted_value, confidence)
        """
        if series.count < 2:
            raise ValueError("线性趋势至少需要2个历史点")

        # 简单线性回归：y = a + b*x
        x = series.years
        y = series.values
        n = len(x)

        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)

        # 计算斜率b和截距a
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denominator = sum((xi - x_mean) ** 2 for xi in x)

        if denominator == 0:
            # 所有年份相同（不应该发生）
            return y[-1], 0.5

        b = numerator / denominator
        a = y_mean - b * x_mean

        # 预测
        predicted = a + b * target_year

        # 计算R²（拟合优度）作为置信度
        y_pred = [a + b * xi for xi in x]
        ss_res = sum((yi - y_pred_i) ** 2 for yi, y_pred_i in zip(y, y_pred))
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        # 置信度：R²越高越好，但外推距离会降低置信度
        last_year = series.years[-1]
        extrapolation_distance = target_year - last_year
        confidence = max(0.3, min(0.9, r_squared * (1 - 0.1 * extrapolation_distance)))

        return predicted, confidence

    def predict_moving_average(self, series: HistoricalSeries, target_year: int) -> tuple[float, float]:
        """移动平均（加权最近年份）

        Returns:
            (predicted_value, confidence)
        """
        # 使用指数加权：最近的年份权重更高
        weights = [2 ** i for i in range(series.count)]  # 最近的权重是最远的2^(n-1)倍
        weighted_sum = sum(w * v for w, v in zip(weights, series.values))
        weight_sum = sum(weights)

        predicted = weighted_sum / weight_sum

        # 置信度：CV越小越好
        confidence = max(0.4, min(0.9, 1 - series.cv))

        return predicted, confidence

    def predict_yoy_growth(self, series: HistoricalSeries, target_year: int) -> tuple[float, float]:
        """同比增长率外推

        Returns:
            (predicted_value, confidence)
        """
        if series.count < 2:
            raise ValueError("同比增长率至少需要2个历史点")

        # 计算历史同比增长率
        growth_rates = []
        for i in range(1, series.count):
            if series.values[i-1] != 0:
                rate = (series.values[i] - series.values[i-1]) / abs(series.values[i-1])
                growth_rates.append(rate)

        if not growth_rates:
            return series.values[-1], 0.3

        # 平均增长率
        avg_growth = statistics.mean(growth_rates)

        # 从最近一年外推
        last_value = series.values[-1]
        last_year = series.years[-1]
        years_to_predict = target_year - last_year

        predicted = last_value * ((1 + avg_growth) ** years_to_predict)

        # 置信度：增长率CV越小越好
        growth_cv = statistics.stdev(growth_rates) / abs(statistics.mean(growth_rates)) if statistics.mean(growth_rates) != 0 else float('inf')
        confidence = max(0.3, min(0.8, 1 - growth_cv / 2))

        return predicted, confidence

    def predict_last_value(self, series: HistoricalSeries, target_year: int) -> tuple[float, float]:
        """使用最近一年值（保守策略）

        Returns:
            (predicted_value, confidence)
        """
        predicted = series.values[-1]

        # 低置信度（因为没有趋势分析）
        confidence = 0.4

        return predicted, confidence

    def predict_one(
        self,
        series: HistoricalSeries,
        target_year: int,
        method: PredictionMethod | None = None,
    ) -> PredictionResult:
        """预测单个时间序列

        Args:
            series: 历史时间序列
            target_year: 目标年份
            method: 指定预测方法（None则自动选择）

        Returns:
            预测结果
        """
        # 检查最小数据点
        if series.count < self.min_historical_points:
            return PredictionResult(
                predicted_observation=None,
                success=False,
                method=None,
                confidence=0.0,
                historical_series=series,
                predicted_value=None,
                failure_reason=f"历史数据点不足: {series.count} < {self.min_historical_points}"
            )

        # 检查稳定性
        if series.cv > self.max_cv:
            return PredictionResult(
                predicted_observation=None,
                success=False,
                method=None,
                confidence=0.0,
                historical_series=series,
                predicted_value=None,
                failure_reason=f"历史数据不稳定: CV={series.cv:.2f} > {self.max_cv}"
            )

        # 选择方法
        if method is None and self.enable_auto_method_selection:
            method = self.select_method(series)
        elif method is None:
            method = PredictionMethod.MOVING_AVERAGE

        # 执行预测
        try:
            if method == PredictionMethod.LINEAR_TREND:
                predicted_value, confidence = self.predict_linear_trend(series, target_year)
            elif method == PredictionMethod.MOVING_AVERAGE:
                predicted_value, confidence = self.predict_moving_average(series, target_year)
            elif method == PredictionMethod.YOY_GROWTH:
                predicted_value, confidence = self.predict_yoy_growth(series, target_year)
            elif method == PredictionMethod.LAST_VALUE:
                predicted_value, confidence = self.predict_last_value(series, target_year)
            else:
                raise ValueError(f"未知预测方法: {method}")
        except Exception as e:
            return PredictionResult(
                predicted_observation=None,
                success=False,
                method=method,
                confidence=0.0,
                historical_series=series,
                predicted_value=None,
                failure_reason=f"预测计算错误: {e}"
            )

        # 创建预测观测
        predicted_obs = Observation(
            company_code=series.company_code,
            company_name=series.company_name,
            report_year=target_year,
            indicator_code=series.indicator_code,
            value=predicted_value,
            status=ValueStatus.PREDICTED,  # 需要添加到models.py
            source_type="time_series_predicted",
            confidence=confidence,
            note=f"基于{series.count}年历史数据预测(方法:{method.value}, CV:{series.cv:.3f})",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )

        return PredictionResult(
            predicted_observation=predicted_obs,
            success=True,
            method=method,
            confidence=confidence,
            historical_series=series,
            predicted_value=predicted_value,
            failure_reason=None
        )

    def predict_batch(
        self,
        historical_observations: list[Observation],
        target_year: int,
        target_companies: set[str] | None = None,
        target_indicators: set[str] | None = None,
    ) -> tuple[list[Observation], list[PredictionResult]]:
        """批量预测

        Args:
            historical_observations: 历史观测数据
            target_year: 目标年份
            target_companies: 目标公司代码集合（None表示全部）
            target_indicators: 目标指标代码集合（None表示全部）

        Returns:
            (成功预测的观测列表, 所有预测结果)
        """
        # 构建历史时间序列
        series_dict = self.build_historical_series(historical_observations, target_year)

        # 过滤目标
        if target_companies is not None or target_indicators is not None:
            filtered_dict = {}
            for (company_code, indicator_code), series in series_dict.items():
                if target_companies is not None and company_code not in target_companies:
                    continue
                if target_indicators is not None and indicator_code not in target_indicators:
                    continue
                filtered_dict[(company_code, indicator_code)] = series
            series_dict = filtered_dict

        # 批量预测
        all_predicted = []
        all_results = []

        for series in series_dict.values():
            result = self.predict_one(series, target_year)
            all_results.append(result)

            if result.success and result.predicted_observation is not None:
                all_predicted.append(result.predicted_observation)

        return all_predicted, all_results
