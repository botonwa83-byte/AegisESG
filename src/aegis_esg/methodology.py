from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import Direction, Indicator, IndicatorKind


@dataclass(frozen=True)
class Methodology:
    version: str
    name: str
    quantitative_ratio: float
    qualitative_ratio: float
    missing_policy: str
    indicators: tuple[Indicator, ...]

    @property
    def by_code(self) -> dict[str, Indicator]:
        return {item.code: item for item in self.indicators}

    @property
    def quantitative(self) -> tuple[Indicator, ...]:
        return tuple(i for i in self.indicators if i.kind == IndicatorKind.QUANTITATIVE)

    @property
    def qualitative(self) -> tuple[Indicator, ...]:
        return tuple(i for i in self.indicators if i.kind == IndicatorKind.QUALITATIVE)


def load_methodology(path: str | Path) -> Methodology:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    indicators = tuple(
        Indicator(
            code=item["code"],
            dimension=item["dimension"],
            level2=item["level2"],
            name=item["name"],
            kind=IndicatorKind(item["kind"]),
            weight=float(item["weight"]),
            direction=Direction(item.get("direction", "positive")),
            unit=item.get("unit", ""),
            formula=item.get("formula", ""),
            benchmark=item.get("benchmark"),
            key_indicator=bool(item.get("key_indicator", False)),
        )
        for item in raw["indicators"]
    )
    result = Methodology(
        version=raw["version"],
        name=raw["name"],
        quantitative_ratio=float(raw.get("quantitative_ratio", 0.8)),
        qualitative_ratio=float(raw.get("qualitative_ratio", 0.2)),
        missing_policy=raw.get("missing_policy", "zero"),
        indicators=indicators,
    )
    _validate(result)
    return result


def _validate(methodology: Methodology) -> None:
    codes = [item.code for item in methodology.indicators]
    if len(codes) != len(set(codes)):
        raise ValueError("指标编码必须唯一")
    for kind, items in (
        ("定量", methodology.quantitative),
        ("定性", methodology.qualitative),
    ):
        total = sum(item.weight for item in items)
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"{kind}指标权重合计应为100，当前为{total}")

