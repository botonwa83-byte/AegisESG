from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BIDIRECTIONAL = "bidirectional"


class IndicatorKind(str, Enum):
    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"


class ValueStatus(str, Enum):
    CONFIRMED = "confirmed"
    PENDING = "pending"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Indicator:
    code: str
    dimension: str
    level2: str
    name: str
    kind: IndicatorKind
    weight: float
    direction: Direction = Direction.POSITIVE
    unit: str = ""
    formula: str = ""
    benchmark: float | None = None
    key_indicator: bool = False


@dataclass(frozen=True)
class Observation:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    value: float | None
    status: ValueStatus = ValueStatus.CONFIRMED
    source_url: str = ""
    source_file: str = ""
    source_page: int | None = None
    evidence_text: str = ""
    confidence: float = 1.0


@dataclass
class IndicatorResult:
    indicator_code: str
    raw_value: float | None
    normalized_score: float
    weighted_score: float
    weight: float
    status: ValueStatus
    population_count: int = 0
    mean: float | None = None
    stddev: float | None = None
    benchmark: float | None = None


@dataclass
class CompanyResult:
    company_code: str
    company_name: str
    report_year: int
    quantitative_score: float
    qualitative_score: float
    total_score: float
    dimension_scores: dict[str, float]
    disclosure_rate: float
    details: list[IndicatorResult] = field(default_factory=list)
    rank: int | None = None

    def to_dict(self, include_details: bool = True) -> dict[str, Any]:
        data = {
            "rank": self.rank,
            "company_code": self.company_code,
            "company_name": self.company_name,
            "report_year": self.report_year,
            "quantitative_score": self.quantitative_score,
            "qualitative_score": self.qualitative_score,
            "total_score": self.total_score,
            "dimension_scores": self.dimension_scores,
            "disclosure_rate": self.disclosure_rate,
        }
        if include_details:
            data["details"] = [
                {**vars(item), "status": item.status.value} for item in self.details
            ]
        return data
