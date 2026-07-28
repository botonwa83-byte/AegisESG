from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .methodology import Methodology
from .models import Observation, ValueStatus


@dataclass(frozen=True)
class QualityIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class QualityReport:
    company_count: int
    observation_count: int
    confirmed_count: int
    issues: tuple[QualityIssue, ...]

    @property
    def publishable(self) -> bool:
        return not any(item.severity == "error" for item in self.issues)


def evaluate_quality(
    observations: list[Observation],
    methodology: Methodology,
    expected_companies: int | None = None,
    minimum_population: int = 20,
) -> QualityReport:
    issues = []
    companies = {(item.company_code, item.report_year) for item in observations}
    confirmed = [item for item in observations if item.status == ValueStatus.CONFIRMED]
    if expected_companies is not None and len(companies) != expected_companies:
        issues.append(QualityIssue("error", "UNIVERSE_MISMATCH", f"样本公司{len(companies)}家，预期{expected_companies}家"))
    duplicates = Counter((o.company_code, o.report_year, o.indicator_code) for o in observations)
    duplicate_keys = [key for key, count in duplicates.items() if count > 1]
    if duplicate_keys:
        issues.append(QualityIssue("error", "DUPLICATE_OBSERVATION", f"存在{len(duplicate_keys)}个重复公司指标"))
    unknown = sorted({item.indicator_code for item in observations} - methodology.by_code.keys())
    if unknown:
        issues.append(QualityIssue("error", "UNKNOWN_INDICATOR", f"未知指标: {unknown}"))
    no_evidence = [item for item in confirmed if not item.source_url and not item.source_file]
    if no_evidence:
        issues.append(QualityIssue("error", "MISSING_EVIDENCE", f"{len(no_evidence)}项已确认数据没有来源"))
    low_confidence = [item for item in confirmed if item.confidence < .8]
    if low_confidence:
        issues.append(QualityIssue("warning", "LOW_CONFIDENCE", f"{len(low_confidence)}项确认数据置信度低于0.8"))
    populations = defaultdict(set)
    for item in confirmed:
        populations[item.indicator_code].add(item.company_code)
    thin = [code for code in methodology.by_code if 0 < len(populations[code]) < minimum_population]
    if thin:
        issues.append(QualityIssue("warning", "THIN_POPULATION", f"{len(thin)}项指标有效样本少于{minimum_population}"))
    absent = [code for code in methodology.by_code if not populations[code]]
    if absent:
        issues.append(QualityIssue("error", "EMPTY_INDICATORS", f"{len(absent)}项指标没有任何已确认数据"))
    return QualityReport(len(companies), len(observations), len(confirmed), tuple(issues))

