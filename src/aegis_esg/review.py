from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .extraction import summarize_review_candidates
from .models import Observation, ValueStatus


@dataclass(frozen=True)
class ReviewInstruction:
    company_code: str
    report_year: int
    indicator_code: str
    action: str
    selected_value: str
    reviewer: str
    reviewed_at: str
    note: str


@dataclass(frozen=True)
class ReviewAudit:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    action: str
    selected_value: str
    candidate_values: str
    source_pages: str
    reviewer: str
    reviewed_at: str
    note: str


REVIEW_COLUMNS = (
    "company_code", "company_name", "report_year", "indicator_code", "candidate_count",
    "distinct_values", "source_pages", "recommended_value", "review_reason",
    "action", "selected_value", "reviewer", "reviewed_at", "note",
)


def write_review_template(path: str | Path, candidates: list[Observation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in summarize_review_candidates(candidates):
            row = vars(item) | {"action": "", "selected_value": "", "reviewer": "", "reviewed_at": "", "note": ""}
            writer.writerow(row)


def read_review_instructions(path: str | Path) -> list[ReviewInstruction]:
    result = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            action = (row.get("action") or "").strip().lower()
            if not action:
                continue
            if action not in {"confirm", "reject"}:
                raise ValueError(f"不支持的复核动作: {action}")
            reviewer = (row.get("reviewer") or "").strip()
            reviewed_at = (row.get("reviewed_at") or "").strip()
            selected = (row.get("selected_value") or "").strip()
            note = (row.get("note") or "").strip()
            if not reviewer or not reviewed_at or not note:
                raise ValueError("复核决定必须填写reviewer、reviewed_at和note")
            if action == "confirm" and not selected:
                raise ValueError("confirm必须填写selected_value")
            if action == "reject" and selected:
                raise ValueError("reject禁止填写selected_value")
            try:
                parsed_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"reviewed_at不是ISO-8601时间: {reviewed_at}") from error
            if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                raise ValueError("reviewed_at必须包含时区")
            result.append(ReviewInstruction(
                company_code=row["company_code"].strip(), report_year=int(row["report_year"]),
                indicator_code=row["indicator_code"].strip(), action=action,
                selected_value=selected, reviewer=reviewer, reviewed_at=reviewed_at,
                note=note,
            ))
    return result


def apply_review_instructions(
    candidates: list[Observation], instructions: list[ReviewInstruction],
) -> tuple[list[Observation], list[Observation]]:
    decisions = {(item.company_code, item.report_year, item.indicator_code): item for item in instructions}
    if len(decisions) != len(instructions):
        raise ValueError("复核指令存在重复公司指标")
    groups: dict[tuple[str, int, str], list[Observation]] = {}
    for item in candidates:
        groups.setdefault((item.company_code, item.report_year, item.indicator_code), []).append(item)
    confirmed, unresolved = [], []
    for key, items in groups.items():
        instruction = decisions.get(key)
        if instruction is None:
            unresolved.extend(items)
            continue
        selected_value = float(instruction.selected_value)
        matches = [item for item in items if item.value is not None and abs(item.value - selected_value) < 1e-8]
        if not matches:
            raise ValueError(f"复核值不在候选中: {key}/{selected_value}")
        selected = sorted(matches, key=lambda item: (-item.confidence, item.source_page or 10**9))[0]
        confirmed.append(Observation(
            company_code=selected.company_code, company_name=selected.company_name,
            report_year=selected.report_year, indicator_code=selected.indicator_code,
            value=selected.value, status=ValueStatus.CONFIRMED, source_url=selected.source_url,
            source_file=selected.source_file, source_page=selected.source_page,
            evidence_text=(selected.evidence_text +
                f" [manual-review:{instruction.reviewer}/{instruction.reviewed_at}/{instruction.note}]"),
            confidence=1.0,
        ))
    unknown = set(decisions) - set(groups)
    if unknown:
        raise ValueError(f"复核指令找不到候选: {sorted(unknown)}")
    return confirmed, unresolved


def apply_conflict_review_instructions(
    candidates: list[Observation], instructions: list[ReviewInstruction],
) -> tuple[list[Observation], list[Observation], list[ReviewAudit]]:
    groups: dict[tuple[str, int, str], list[Observation]] = {}
    for item in candidates:
        groups.setdefault((item.company_code, item.report_year, item.indicator_code), []).append(item)
    decisions = {(item.company_code, item.report_year, item.indicator_code): item for item in instructions}
    if len(decisions) != len(instructions):
        raise ValueError("复核指令存在重复公司指标")
    for key in decisions:
        if key not in groups:
            raise ValueError(f"复核指令找不到候选: {key}")
        values = {round(float(item.value), 8) for item in groups[key] if item.value is not None}
        if len(values) < 2:
            raise ValueError(f"冲突复核指令指向非冲突候选: {key}")

    confirmed, unresolved, audits = [], [], []
    for key, items in sorted(groups.items()):
        instruction = decisions.get(key)
        if instruction is None:
            unresolved.extend(items)
            continue
        values = sorted({round(float(item.value), 8) for item in items if item.value is not None})
        pages = sorted({item.source_page for item in items if item.source_page is not None})
        selected_value = ""
        if instruction.action == "confirm":
            numeric = float(instruction.selected_value)
            matches = [item for item in items if item.value is not None and abs(item.value - numeric) < 1e-8]
            if not matches:
                raise ValueError(f"复核值不在候选中: {key}/{numeric}")
            selected = sorted(matches, key=lambda item: (-item.confidence, item.source_page or 10**9))[0]
            selected_value = f"{float(selected.value):g}"
            confirmed.append(Observation(
                company_code=selected.company_code, company_name=selected.company_name,
                report_year=selected.report_year, indicator_code=selected.indicator_code,
                value=selected.value, status=ValueStatus.CONFIRMED, source_url=selected.source_url,
                source_file=selected.source_file, source_page=selected.source_page,
                evidence_text=(selected.evidence_text +
                    f" [manual-review:{instruction.reviewer}/{instruction.reviewed_at}/{instruction.note}]"),
                confidence=1.0,
            ))
        audits.append(ReviewAudit(
            company_code=key[0], company_name=items[0].company_name, report_year=key[1],
            indicator_code=key[2], action=instruction.action, selected_value=selected_value,
            candidate_values="|".join(f"{value:g}" for value in values),
            source_pages="|".join(str(page) for page in pages), reviewer=instruction.reviewer,
            reviewed_at=instruction.reviewed_at, note=instruction.note,
        ))
    return confirmed, unresolved, audits


def write_review_audit(path: str | Path, audits: list[ReviewAudit]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(ReviewAudit.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(vars(item) for item in audits)
