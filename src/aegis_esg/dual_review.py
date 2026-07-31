from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .models import Observation, ValueStatus
from .qualitative_review import (
    QualitativeReviewAudit,
    QualitativeReviewPacket,
)


@dataclass(frozen=True)
class DualReviewCase:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    suggested_score: int
    first_action: str
    first_score: str
    first_reviewer: str
    first_reviewed_at: str
    first_note: str
    representative_source_url: str
    representative_source_file: str
    representative_page: int
    representative_evidence: str


@dataclass(frozen=True)
class DualReviewDecision:
    company_code: str
    report_year: int
    indicator_code: str
    second_action: str
    second_score: str
    second_reviewer: str
    second_reviewed_at: str
    second_note: str


@dataclass(frozen=True)
class DualReviewOutcome:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    first_action: str
    first_score: str
    first_reviewer: str
    second_action: str
    second_score: str
    second_reviewer: str
    second_reviewed_at: str
    outcome: str


@dataclass(frozen=True)
class ArbitrationCase:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    suggested_score: int
    first_action: str
    first_score: str
    first_reviewer: str
    first_reviewed_at: str
    first_note: str
    second_action: str
    second_score: str
    second_reviewer: str
    second_reviewed_at: str
    second_note: str
    representative_source_url: str
    representative_source_file: str
    representative_page: int
    representative_evidence: str


@dataclass(frozen=True)
class ArbitrationDecision:
    company_code: str
    report_year: int
    indicator_code: str
    final_action: str
    final_score: str
    arbiter: str
    arbitrated_at: str
    note: str


@dataclass(frozen=True)
class ArbitrationAudit:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    first_action: str
    first_score: str
    first_reviewer: str
    second_action: str
    second_score: str
    second_reviewer: str
    final_action: str
    final_score: str
    arbiter: str
    arbitrated_at: str
    note: str


DUAL_REVIEW_TEMPLATE_COLUMNS = tuple(DualReviewCase.__annotations__) + (
    "second_action", "second_score", "second_reviewer", "second_reviewed_at", "second_note",
)
ARBITRATION_TEMPLATE_COLUMNS = tuple(ArbitrationCase.__annotations__) + (
    "final_action", "final_score", "arbiter", "arbitrated_at", "note",
)


def read_qualitative_review_audits(path: str | Path) -> list[QualitativeReviewAudit]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = set(QualitativeReviewAudit.__annotations__)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"定性复核审计缺少字段: {','.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, 2):
            try:
                rows.append(QualitativeReviewAudit(
                    row["company_code"].strip().upper(), row["company_name"].strip(),
                    int(row["report_year"]), row["indicator_code"].strip(),
                    int(row["suggested_score"]), row["action"].strip(), row["selected_score"].strip(),
                    int(row["representative_page"]), row["reviewer"].strip(),
                    row["reviewed_at"].strip(), row["note"].strip(),
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"定性复核审计第{line}行格式错误: {error}") from error
    keys = {(item.company_code, item.report_year, item.indicator_code) for item in rows}
    if len(keys) != len(rows):
        raise ValueError("定性复核审计存在重复公司指标")
    return rows


def requires_dual_review(audit: QualitativeReviewAudit) -> bool:
    if audit.action == "confirm":
        if audit.selected_score in {"80", "100"}:
            return True
        return int(audit.selected_score) != audit.suggested_score
    if audit.action == "reject":
        return audit.suggested_score >= 80
    raise ValueError(f"未知复核动作: {audit.action}")


def select_dual_review_cases(
    packets: list[QualitativeReviewPacket], audits: list[QualitativeReviewAudit],
) -> list[DualReviewCase]:
    packet_index = {
        (item.company_code, item.report_year, item.indicator_code): item for item in packets
    }
    cases = []
    for audit in audits:
        if not requires_dual_review(audit):
            continue
        key = (audit.company_code, audit.report_year, audit.indicator_code)
        packet = packet_index.get(key)
        if packet is None:
            raise ValueError(f"复核审计找不到复核包: {audit.company_code}/{audit.indicator_code}")
        cases.append(DualReviewCase(
            audit.company_code, audit.company_name, audit.report_year, audit.indicator_code,
            audit.suggested_score, audit.action, audit.selected_score, audit.reviewer,
            audit.reviewed_at, audit.note, packet.representative_source_url,
            packet.representative_source_file, packet.representative_page,
            packet.representative_evidence,
        ))
    cases.sort(key=lambda item: (item.company_code, item.indicator_code))
    return cases


def write_dual_review_template(path: str | Path, cases: list[DualReviewCase]) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=DUAL_REVIEW_TEMPLATE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in cases:
            writer.writerow(asdict(item) | {
                "second_action": "", "second_score": "", "second_reviewer": "",
                "second_reviewed_at": "", "second_note": "",
            })
    return len(cases)


def _validate_signature(action: str, score: str, reviewer: str, signed_at: str, note: str, role: str) -> None:
    if action not in {"confirm", "reject"}:
        raise ValueError(f"{role}动作只能是confirm或reject")
    if not reviewer or not signed_at or not note:
        raise ValueError(f"{role}必须填写签名、带时区时间和理由")
    try:
        parsed = datetime.fromisoformat(signed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{role}时间不是ISO-8601: {signed_at}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{role}时间必须包含时区")
    if action == "confirm":
        if score not in {"0", "20", "50", "80", "100"}:
            raise ValueError(f"{role}分值只能是0/20/50/80/100")
        if score == "100" and not re.search(r"领先|标杆|leading|benchmark", note, re.I):
            raise ValueError(f"{role}确认100分必须说明行业领先或标杆证据")
    elif score:
        raise ValueError(f"{role}拒绝时禁止填写分值")


def read_dual_review_decisions(path: str | Path) -> list[DualReviewDecision]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(DUAL_REVIEW_TEMPLATE_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"双人复核决定缺少字段: {','.join(sorted(missing))}")
        decisions = []
        for line, row in enumerate(reader, 2):
            action = row["second_action"].strip().lower()
            if not action:
                continue
            try:
                _validate_signature(
                    action, row["second_score"].strip(), row["second_reviewer"].strip(),
                    row["second_reviewed_at"].strip(), row["second_note"].strip(), "第二审核人",
                )
                decisions.append(DualReviewDecision(
                    row["company_code"].strip().upper(), int(row["report_year"]),
                    row["indicator_code"].strip(), action, row["second_score"].strip(),
                    row["second_reviewer"].strip(), row["second_reviewed_at"].strip(),
                    row["second_note"].strip(),
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"双人复核决定第{line}行: {error}") from error
    keys = {(item.company_code, item.report_year, item.indicator_code) for item in decisions}
    if len(keys) != len(decisions):
        raise ValueError("双人复核决定存在重复公司指标")
    return decisions


def _confirmed_observation(
    company_code: str, company_name: str, report_year: int, indicator_code: str,
    score: str, source_url: str, source_file: str, source_page: int, evidence: str, tag: str,
) -> Observation:
    return Observation(
        company_code, company_name, report_year, indicator_code, float(score),
        ValueStatus.CONFIRMED, source_url=source_url, source_file=source_file,
        source_page=source_page, evidence_text=f"{evidence} [{tag}]", confidence=1.0,
    )


def apply_dual_review_decisions(
    cases: list[DualReviewCase], decisions: list[DualReviewDecision],
) -> tuple[list[Observation], list[DualReviewOutcome], list[ArbitrationCase], list[DualReviewCase]]:
    case_index = {(item.company_code, item.report_year, item.indicator_code): item for item in cases}
    if len(case_index) != len(cases):
        raise ValueError("双人复核案例存在重复公司指标")
    decision_index = {(item.company_code, item.report_year, item.indicator_code): item for item in decisions}
    unknown = set(decision_index) - set(case_index)
    if unknown:
        key = sorted(unknown)[0]
        raise ValueError(f"双人复核决定找不到案例: {key[0]}/{key[2]}")
    confirmed, outcomes, arbitrations, open_cases = [], [], [], []
    for key, case in sorted(case_index.items()):
        decision = decision_index.get(key)
        if decision is None:
            open_cases.append(case)
            continue
        if decision.second_reviewer.casefold() == case.first_reviewer.casefold():
            raise ValueError(f"第二审核人必须与第一审核人不同: {case.company_code}/{case.indicator_code}")
        agreement = (
            decision.second_action == case.first_action
            and (case.first_action != "confirm" or decision.second_score == case.first_score)
        )
        outcomes.append(DualReviewOutcome(
            case.company_code, case.company_name, case.report_year, case.indicator_code,
            case.first_action, case.first_score, case.first_reviewer,
            decision.second_action, decision.second_score, decision.second_reviewer,
            decision.second_reviewed_at, "closed_agreement" if agreement else "arbitration_required",
        ))
        if agreement:
            if case.first_action == "confirm":
                confirmed.append(_confirmed_observation(
                    case.company_code, case.company_name, case.report_year, case.indicator_code,
                    case.first_score, case.representative_source_url, case.representative_source_file,
                    case.representative_page, case.representative_evidence,
                    f"qualitative-dual-review:{case.first_reviewer}+{decision.second_reviewer}/{decision.second_reviewed_at}",
                ))
        else:
            arbitrations.append(ArbitrationCase(
                case.company_code, case.company_name, case.report_year, case.indicator_code,
                case.suggested_score, case.first_action, case.first_score, case.first_reviewer,
                case.first_reviewed_at, case.first_note, decision.second_action,
                decision.second_score, decision.second_reviewer, decision.second_reviewed_at,
                decision.second_note, case.representative_source_url,
                case.representative_source_file, case.representative_page,
                case.representative_evidence,
            ))
    return confirmed, outcomes, arbitrations, open_cases


def write_dual_review_results(
    outcome_path: str | Path, arbitration_path: str | Path, open_path: str | Path,
    outcomes: list[DualReviewOutcome], arbitrations: list[ArbitrationCase], open_cases: list[DualReviewCase],
) -> None:
    for path, rows, fields, blanks in (
        (outcome_path, outcomes, tuple(DualReviewOutcome.__annotations__), {}),
        (arbitration_path, arbitrations, ARBITRATION_TEMPLATE_COLUMNS, {
            "final_action": "", "final_score": "", "arbiter": "", "arbitrated_at": "", "note": "",
        }),
        (open_path, open_cases, DUAL_REVIEW_TEMPLATE_COLUMNS, {
            "second_action": "", "second_score": "", "second_reviewer": "",
            "second_reviewed_at": "", "second_note": "",
        }),
    ):
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for item in rows:
                writer.writerow(asdict(item) | blanks)


def read_arbitration_cases(path: str | Path) -> list[ArbitrationCase]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(ARBITRATION_TEMPLATE_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"仲裁队列缺少字段: {','.join(sorted(missing))}")
        cases = []
        for line, row in enumerate(reader, 2):
            try:
                cases.append(ArbitrationCase(
                    row["company_code"].strip().upper(), row["company_name"].strip(),
                    int(row["report_year"]), row["indicator_code"].strip(), int(row["suggested_score"]),
                    row["first_action"].strip(), row["first_score"].strip(), row["first_reviewer"].strip(),
                    row["first_reviewed_at"].strip(), row["first_note"].strip(),
                    row["second_action"].strip(), row["second_score"].strip(),
                    row["second_reviewer"].strip(), row["second_reviewed_at"].strip(),
                    row["second_note"].strip(), row["representative_source_url"].strip(),
                    row["representative_source_file"].strip(), int(row["representative_page"]),
                    row["representative_evidence"].strip(),
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"仲裁队列第{line}行格式错误: {error}") from error
    keys = {(item.company_code, item.report_year, item.indicator_code) for item in cases}
    if len(keys) != len(cases):
        raise ValueError("仲裁队列存在重复公司指标")
    return cases


def read_arbitration_decisions(path: str | Path) -> list[ArbitrationDecision]:
    cases = read_arbitration_cases(path)
    decisions = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            action = (row.get("final_action") or "").strip().lower()
            if not action:
                continue
            try:
                _validate_signature(
                    action, (row.get("final_score") or "").strip(), (row.get("arbiter") or "").strip(),
                    (row.get("arbitrated_at") or "").strip(), (row.get("note") or "").strip(), "仲裁人",
                )
                decisions.append(ArbitrationDecision(
                    row["company_code"].strip().upper(), int(row["report_year"]),
                    row["indicator_code"].strip(), action, (row.get("final_score") or "").strip(),
                    row["arbiter"].strip(), row["arbitrated_at"].strip(), row["note"].strip(),
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"仲裁决定第{line}行: {error}") from error
    case_keys = {(item.company_code, item.report_year, item.indicator_code) for item in cases}
    decision_keys = {(item.company_code, item.report_year, item.indicator_code) for item in decisions}
    if len(decision_keys) != len(decisions):
        raise ValueError("仲裁决定存在重复公司指标")
    unknown = decision_keys - case_keys
    if unknown:
        key = sorted(unknown)[0]
        raise ValueError(f"仲裁决定找不到仲裁案例: {key[0]}/{key[2]}")
    return decisions


def apply_arbitration_decisions(
    cases: list[ArbitrationCase], decisions: list[ArbitrationDecision],
) -> tuple[list[Observation], list[ArbitrationCase], list[ArbitrationAudit]]:
    case_index = {(item.company_code, item.report_year, item.indicator_code): item for item in cases}
    decision_index = {(item.company_code, item.report_year, item.indicator_code): item for item in decisions}
    unknown = set(decision_index) - set(case_index)
    if unknown:
        key = sorted(unknown)[0]
        raise ValueError(f"仲裁决定找不到仲裁案例: {key[0]}/{key[2]}")
    confirmed, unresolved, audits = [], [], []
    for key, case in sorted(case_index.items()):
        decision = decision_index.get(key)
        if decision is None:
            unresolved.append(case)
            continue
        participants = {case.first_reviewer.casefold(), case.second_reviewer.casefold()}
        if decision.arbiter.casefold() in participants:
            raise ValueError(f"仲裁人必须区别于两名审核人: {case.company_code}/{case.indicator_code}")
        audits.append(ArbitrationAudit(
            case.company_code, case.company_name, case.report_year, case.indicator_code,
            case.first_action, case.first_score, case.first_reviewer,
            case.second_action, case.second_score, case.second_reviewer,
            decision.final_action, decision.final_score, decision.arbiter,
            decision.arbitrated_at, decision.note,
        ))
        if decision.final_action == "confirm":
            confirmed.append(_confirmed_observation(
                case.company_code, case.company_name, case.report_year, case.indicator_code,
                decision.final_score, case.representative_source_url, case.representative_source_file,
                case.representative_page, case.representative_evidence,
                f"qualitative-arbitration:{case.first_reviewer}+{case.second_reviewer}->{decision.arbiter}/{decision.arbitrated_at}",
            ))
    return confirmed, unresolved, audits


def write_arbitration_results(
    unresolved_path: str | Path, audit_path: str | Path,
    unresolved: list[ArbitrationCase], audits: list[ArbitrationAudit],
) -> None:
    output = Path(unresolved_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ARBITRATION_TEMPLATE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in unresolved:
            writer.writerow(asdict(item) | {
                "final_action": "", "final_score": "", "arbiter": "", "arbitrated_at": "", "note": "",
            })
    audit_output = Path(audit_path)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    with audit_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(ArbitrationAudit.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(item) for item in audits)
