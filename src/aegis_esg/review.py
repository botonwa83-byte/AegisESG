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


REVIEW_COLUMNS = (
    "company_code", "company_name", "report_year", "indicator_code", "candidate_count",
    "distinct_values", "source_pages", "recommended_value", "review_reason",
    "action", "selected_value", "reviewer", "reviewed_at", "note",
)


def write_review_template(path: str | Path, candidates: list[Observation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS)
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
            if action != "confirm":
                raise ValueError(f"不支持的复核动作: {action}")
            reviewer = (row.get("reviewer") or "").strip()
            reviewed_at = (row.get("reviewed_at") or "").strip()
            selected = (row.get("selected_value") or "").strip()
            if not reviewer or not reviewed_at or not selected:
                raise ValueError("confirm必须填写selected_value、reviewer和reviewed_at")
            try:
                datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"reviewed_at不是ISO-8601时间: {reviewed_at}") from error
            result.append(ReviewInstruction(
                company_code=row["company_code"].strip(), report_year=int(row["report_year"]),
                indicator_code=row["indicator_code"].strip(), action=action,
                selected_value=selected, reviewer=reviewer, reviewed_at=reviewed_at,
                note=(row.get("note") or "").strip(),
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
