"""DL/T 2971—2025 表1 ESG级别映射与不予评级(NA)规则。"""

from __future__ import annotations

from dataclasses import dataclass


GRADE_RULE_VERSION = "dlt2971-2025-table1-v1"
DISCLOSURE_HALF_THRESHOLD = 50.0


@dataclass(frozen=True)
class GradeFlags:
    """行标8.2.4.3中需显式确认的不予评级情形；默认不猜测。"""

    major_safety_incident: bool = False
    major_environment_incident: bool = False
    major_hazard_unrectified: bool = False
    accident_misreport: bool = False

    @property
    def forces_na(self) -> bool:
        return any((
            self.major_safety_incident,
            self.major_environment_incident,
            self.major_hazard_unrectified,
            self.accident_misreport,
        ))

    def na_reason(self) -> str:
        if self.major_safety_incident:
            return "major_safety_incident"
        if self.major_environment_incident:
            return "major_environment_incident"
        if self.major_hazard_unrectified:
            return "major_hazard_unrectified"
        if self.accident_misreport:
            return "accident_misreport"
        return ""


@dataclass(frozen=True)
class GradeResult:
    grade: str
    reason: str
    rule_version: str = GRADE_RULE_VERSION


def map_esg_grade(
    total_score: float,
    disclosure_rate: float,
    flags: GradeFlags | None = None,
) -> GradeResult:
    """按 DL/T 2971—2025 表1确定级别；NA 优先于分值档。

    分值区间：AAA[90,100]、AA[75,90)、A[60,75)、BBB[50,60)、
    BB[40,50)、B[30,40)、C[20,30)、NA(0,20)（实现为[0,20)）。
    披露率低于一半（<50%）或事故/瞒报等 flag 触发时强制 NA。
    """
    active = flags or GradeFlags()
    if active.forces_na:
        return GradeResult("NA", active.na_reason())
    if disclosure_rate < DISCLOSURE_HALF_THRESHOLD:
        return GradeResult("NA", "disclosure_below_half")
    score = float(total_score)
    if score >= 90:
        return GradeResult("AAA", "score_band")
    if score >= 75:
        return GradeResult("AA", "score_band")
    if score >= 60:
        return GradeResult("A", "score_band")
    if score >= 50:
        return GradeResult("BBB", "score_band")
    if score >= 40:
        return GradeResult("BB", "score_band")
    if score >= 30:
        return GradeResult("B", "score_band")
    if score >= 20:
        return GradeResult("C", "score_band")
    return GradeResult("NA", "score_band")
