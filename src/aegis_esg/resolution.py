from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import csv
import json
from pathlib import Path

from .models import Observation, ValueStatus


AUTO_POLICY_VERSION = "public-disclosure-v6"
AUTO_INDICATORS = {
    "Q_G_ROE", "Q_G_REVENUE_GROWTH", "Q_S_DIVIDEND_PER_SHARE", "Q_S_RD_RATE",
    "Q_G_DEBT_ASSET_RATE", "Q_G_ASSET_TURNOVER", "Q_G_AR_TURNOVER",
    "Q_G_CURRENT_ASSET_TURNOVER", "Q_G_TWO_FUNDS_RATE", "Q_G_CAPITAL_ACCUMULATION",
    "Q_G_ROA", "Q_G_OPERATING_MARGIN", "Q_G_CASH_REALIZATION",
    "Q_G_COST_REVENUE_RATE", "Q_G_EBITDA_INTEREST", "Q_G_CASH_CURRENT_LIABILITY",
    "Q_G_OPERATING_PROFIT_GROWTH",
}
ESG_AUTO_INDICATORS = {"Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY"}
STRICT_EVIDENCE_PREFIXES = {
    "Q_E_ALTERNATIVE_WATER_RATE": (
        "Alternative-water direct group rate:",
        "Alternative-water explicit-year table:",
        "Alternative-water explicit-year vertical table:",
    ),
    "Q_S_RD_RATE": ("中文研发占收比显式年份表: ",),
    "Q_E_CLEAN_ENERGY_INTENSITY": ("English same-table renewable energy intensity derived:",),
    "Q_E_GHG_INTENSITY": (
        "English current-first direct intensity row:", "English current-first Million Yuan row:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_ENERGY_INTENSITY": (
        "English current-first revenue resource row:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_WATER_INTENSITY": (
        "English current-first direct intensity row:", "English current-first Million Yuan row:",
        "English current-first revenue resource row:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_GHG_REDUCTION_RATE": (
        "English same-scope GHG table derived:", "English total-GHG YoY direct: ",
        "中文两期总量表派生: ", "中文减排率直接披露: ",
    ),
    "Q_E_NOX_INTENSITY": (
        "English revenue intensity:", "English current-first environmental table derived:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_SO2_INTENSITY": (
        "English revenue intensity:", "English current-first environmental table derived:",
        "Chinese explicit-year split pollutant intensity row:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_PM_INTENSITY": (
        "English revenue intensity:", "English current-first Million Yuan row:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_WASTEWATER_INTENSITY": (
        "English revenue intensity:", "English current-first environmental table derived:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_SOLID_WASTE_INTENSITY": (
        "English revenue intensity:", "English current-first environmental table derived:", "English current-first direct intensity row:", "English current-year interleaved waste row:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_E_HAZ_WASTE_INTENSITY": (
        "English revenue intensity:", "English current-first environmental table derived:", "English current-first direct intensity row:",
        "Chinese current-first environmental table row:",
        "Chinese current-last environmental table row:",
        "Chinese current-first-postfix-unit environmental table row:",
        "Chinese current-last-postfix-unit environmental table row:",
        "Chinese single-year environmental table row:",
        "Chinese single-value-revenue-unit environmental table row:",
        "中文跨表派生: ", "English cross-document derived: ",
    ),
    "Q_S_ENV_INVEST_RATE": (
        "English environmental investment table:", "English current-first direct intensity row:",
        "中文投入占比派生: ",
    ),
    "Q_S_SAFETY_INVEST_RATE": ("中文投入占比派生: ",),
    "Q_S_DONATION_RATE": ("中文投入占比派生: ",),
    "Q_S_PAY_PER_EMPLOYEE": ("English same-group RMB staff cost derived:", "中文应付职工薪酬附注派生: "),
    "Q_S_BENEFIT_PER_EMPLOYEE": ("English RMB employee note derived:", "中文应付职工薪酬附注派生: "),
    "Q_S_EDU_PER_EMPLOYEE": ("English RMB employee note derived:", "中文应付职工薪酬附注派生: "),
    "Q_G_EBITDA_MARGIN": ("English consolidated statements derived:", "合并利润/现金流量表自动派生: "),
    "Q_G_QUICK_RATIO": ("English consolidated statement derived:", "合并报表自动派生: "),
}


@dataclass(frozen=True)
class ResolutionDecision:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    decision: str
    candidate_count: int
    distinct_values: str
    selected_value: str
    policy_version: str
    reason: str


@dataclass(frozen=True)
class ReviewTier:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    candidate_count: int
    distinct_values: str
    source_pages: str
    max_confidence: float
    tier: str
    next_action: str
    reason: str


def resolve_pending_candidates(
    candidates: list[Observation],
) -> tuple[list[Observation], list[Observation], list[ResolutionDecision]]:
    """Confirm only unambiguous direct metrics from official annual reports."""
    grouped: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    for item in candidates:
        grouped[(item.company_code, item.report_year, item.indicator_code)].append(item)
    confirmed: list[Observation] = []
    unresolved: list[Observation] = []
    decisions: list[ResolutionDecision] = []
    for key, items in sorted(grouped.items()):
        eligible = []
        for item in items:
            annual_eligible = (
                item.indicator_code in AUTO_INDICATORS
                and item.source_file.endswith("annual_report.pdf") and item.confidence >= .9
            )
            esg_eligible = (
                item.indicator_code in ESG_AUTO_INDICATORS
                and item.source_file.endswith("esg_report.pdf") and item.confidence >= .82
            )
            strict_prefixes = STRICT_EVIDENCE_PREFIXES.get(item.indicator_code, ())
            strict_eligible = (
                bool(strict_prefixes)
                and item.source_file.endswith(("annual_report.pdf", "esg_report.pdf"))
                and item.confidence >= .9
                and item.evidence_text.startswith(strict_prefixes)
            )
            if item.value is not None and (annual_eligible or esg_eligible or strict_eligible):
                eligible.append(item)
        values = sorted({round(float(item.value), 8) for item in eligible})
        tolerance = .01 if key[2] == "Q_G_DEBT_ASSET_RATE" else 0
        consistent = bool(values) and max(values) - min(values) <= tolerance
        derived_debt = [
            item for item in eligible
            if key[2] == "Q_G_DEBT_ASSET_RATE" and item.evidence_text.startswith("合并报表自动派生:")
        ]
        if derived_debt:
            selected = sorted(derived_debt, key=lambda item: (-item.confidence, item.source_page or 10**9))[0]
            agreeing = [item for item in eligible if abs(float(item.value) - float(selected.value)) <= tolerance]
            consistent = bool(agreeing)
            eligible = agreeing
        if eligible and consistent:
            selected = sorted(
                eligible,
                key=lambda item: (-item.confidence, item.source_page or 10**9, item.source_file),
            )[0]
            confirmed.append(Observation(
                company_code=selected.company_code, company_name=selected.company_name,
                report_year=selected.report_year, indicator_code=selected.indicator_code,
                value=selected.value, status=ValueStatus.CONFIRMED,
                source_url=selected.source_url, source_file=selected.source_file,
                source_page=selected.source_page,
                evidence_text=selected.evidence_text + f" [auto-confirm:{AUTO_POLICY_VERSION}]",
                confidence=selected.confidence,
            ))
            if key[2] in ESG_AUTO_INDICATORS:
                reason = "official_esg_direct_consistent"
            elif key[2] in STRICT_EVIDENCE_PREFIXES:
                reason = "strict_extraction_evidence_consistent"
            elif derived_debt:
                reason = "consolidated_statement_year_end_derived"
            else:
                reason = "official_annual_direct_consistent"
            decision, selected_value = "auto_confirmed", f"{float(selected.value):g}"
        else:
            unresolved.extend(items)
            decision = "manual_required"
            auto_codes = AUTO_INDICATORS | ESG_AUTO_INDICATORS | set(STRICT_EVIDENCE_PREFIXES)
            reason = "indicator_not_auto_eligible" if key[2] not in auto_codes else "conflicting_or_ineligible_sources"
            selected_value = ""
        all_values = sorted({round(float(item.value), 8) for item in items if item.value is not None})
        decisions.append(ResolutionDecision(
            company_code=key[0], company_name=items[0].company_name, report_year=key[1],
            indicator_code=key[2], decision=decision, candidate_count=len(items),
            distinct_values="|".join(f"{value:g}" for value in all_values),
            selected_value=selected_value, policy_version=AUTO_POLICY_VERSION, reason=reason,
        ))
    return confirmed, unresolved, decisions


def plan_review_tiers(candidates: list[Observation]) -> tuple[list[ReviewTier], dict]:
    grouped: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    for item in candidates:
        grouped[(item.company_code, item.report_year, item.indicator_code)].append(item)
    _, _, decisions = resolve_pending_candidates(candidates)
    decision_by_key = {
        (item.company_code, item.report_year, item.indicator_code): item for item in decisions
    }
    rows = []
    for key, items in sorted(grouped.items()):
        values = sorted({round(float(item.value), 8) for item in items if item.value is not None})
        decision = decision_by_key[key]
        if len(values) > 1:
            tier, action, reason = (
                "manual_signature_required", "review_conflict_candidates", "conflicting_values",
            )
        elif decision.decision == "auto_confirmed":
            tier, action, reason = (
                "auto_policy_eligible", "run_resolve_pending", decision.reason,
            )
        elif len(items) > 1:
            tier, action, reason = (
                "consistent_multi_review", "manual_spot_check", "consistent_but_not_auto_eligible",
            )
        else:
            tier, action, reason = (
                "single_candidate_review", "manual_spot_check", decision.reason,
            )
        rows.append(ReviewTier(
            company_code=key[0], company_name=items[0].company_name, report_year=key[1],
            indicator_code=key[2], candidate_count=len(items),
            distinct_values="|".join(f"{value:g}" for value in values),
            source_pages="|".join(str(page) for page in sorted({
                item.source_page for item in items if item.source_page is not None
            })),
            max_confidence=max(item.confidence for item in items), tier=tier,
            next_action=action, reason=reason,
        ))
    order = {
        "manual_signature_required": 0, "consistent_multi_review": 1,
        "single_candidate_review": 2, "auto_policy_eligible": 3,
    }
    rows.sort(key=lambda item: (order[item.tier], item.company_code, item.indicator_code))
    counts = defaultdict(int)
    for item in rows:
        counts[item.tier] += 1
    summary = {
        "candidate_group_count": len(rows),
        "candidate_observation_count": len(candidates),
        "tier_counts": {name: counts[name] for name in order},
        "auto_policy_version": AUTO_POLICY_VERSION,
        "applicable": False,
    }
    return rows, summary


def write_review_tiers(
    output_path: str | Path, summary_path: str | Path, rows: list[ReviewTier], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(ReviewTier.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(vars(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_resolution_decisions(path: str | Path) -> list[ResolutionDecision]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = set(ResolutionDecision.__annotations__)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"resolution decision file missing columns: {','.join(sorted(missing))}")
        rows = []
        for number, row in enumerate(reader, start=2):
            try:
                rows.append(ResolutionDecision(
                    company_code=row["company_code"], company_name=row["company_name"],
                    report_year=int(row["report_year"]), indicator_code=row["indicator_code"],
                    decision=row["decision"], candidate_count=int(row["candidate_count"]),
                    distinct_values=row["distinct_values"], selected_value=row["selected_value"],
                    policy_version=row["policy_version"], reason=row["reason"],
                ))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid resolution decision at row {number}: {exc}") from exc
    return rows


def read_review_tiers(path: str | Path) -> list[ReviewTier]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = set(ReviewTier.__annotations__)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"review tier file missing columns: {','.join(sorted(missing))}")
        rows = []
        for number, row in enumerate(reader, start=2):
            try:
                rows.append(ReviewTier(
                    company_code=row["company_code"], company_name=row["company_name"],
                    report_year=int(row["report_year"]), indicator_code=row["indicator_code"],
                    candidate_count=int(row["candidate_count"]), distinct_values=row["distinct_values"],
                    source_pages=row["source_pages"], max_confidence=float(row["max_confidence"]),
                    tier=row["tier"], next_action=row["next_action"], reason=row["reason"],
                ))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid review tier at row {number}: {exc}") from exc
    return rows


def select_manual_review_candidates(
    candidates: list[Observation], tiers: list[ReviewTier],
) -> list[Observation]:
    """Select only candidate groups that the frozen tier plan sends to human review."""
    key = lambda item: (item.company_code, item.report_year, item.indicator_code)
    grouped: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    tier_by_key = {}
    for item in candidates:
        grouped[key(item)].append(item)
    for item in tiers:
        item_key = key(item)
        if item_key in tier_by_key:
            raise ValueError(f"duplicate review tier: {item_key}")
        tier_by_key[item_key] = item
    if set(tier_by_key) != set(grouped):
        raise ValueError("review tiers do not exactly match candidate groups")
    selected = []
    for item_key, items in sorted(grouped.items()):
        tier = tier_by_key[item_key]
        if tier.candidate_count != len(items):
            raise ValueError(f"review tier candidate count drift: {item_key}")
        if tier.tier != "auto_policy_eligible":
            selected.extend(items)
    return selected


def audit_resolution_preview(
    candidates: list[Observation], confirmed: list[Observation], unresolved: list[Observation],
    decisions: list[ResolutionDecision],
) -> dict:
    """Verify that a resolution preview closes every candidate group without data drift."""
    key = lambda item: (item.company_code, item.report_year, item.indicator_code)
    grouped: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    confirmed_by_key: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    unresolved_by_key: dict[tuple[str, int, str], list[Observation]] = defaultdict(list)
    decision_by_key = {}
    for item in candidates:
        grouped[key(item)].append(item)
    for item in confirmed:
        confirmed_by_key[key(item)].append(item)
    for item in unresolved:
        unresolved_by_key[key(item)].append(item)
    for item in decisions:
        item_key = key(item)
        if item_key in decision_by_key:
            raise ValueError(f"duplicate resolution decision: {item_key}")
        decision_by_key[item_key] = item
    if set(decision_by_key) != set(grouped):
        raise ValueError("resolution decisions do not exactly match candidate groups")
    if (set(confirmed_by_key) | set(unresolved_by_key)) - set(grouped):
        raise ValueError("preview contains unknown candidate groups")
    if set(confirmed_by_key) & set(unresolved_by_key):
        raise ValueError("confirmed and unresolved preview groups overlap")

    def signature(item: Observation) -> tuple:
        return (
            item.value, item.source_url, item.source_file, item.source_page,
            item.evidence_text, item.confidence,
        )

    auto_count = manual_count = 0
    for item_key, original in grouped.items():
        decision = decision_by_key[item_key]
        if decision.policy_version != AUTO_POLICY_VERSION:
            raise ValueError(f"unexpected policy version for {item_key}: {decision.policy_version}")
        if decision.candidate_count != len(original):
            raise ValueError(f"candidate count drift for {item_key}")
        if decision.decision == "auto_confirmed":
            auto_count += 1
            selected = confirmed_by_key.get(item_key, [])
            if len(selected) != 1 or unresolved_by_key.get(item_key):
                raise ValueError(f"auto-confirmed group is not closed: {item_key}")
            selected_item = selected[0]
            if selected_item.status != ValueStatus.CONFIRMED:
                raise ValueError(f"auto-confirmed preview has invalid status: {item_key}")
            if f"[auto-confirm:{AUTO_POLICY_VERSION}]" not in selected_item.evidence_text:
                raise ValueError(f"auto-confirm marker missing: {item_key}")
            try:
                float(decision.selected_value)
            except ValueError as exc:
                raise ValueError(f"invalid selected value for {item_key}") from exc
            if selected_item.value is None or f"{float(selected_item.value):g}" != decision.selected_value:
                raise ValueError(f"selected value drift for {item_key}")
            if not any(
                candidate.value is not None and float(candidate.value) == float(selected_item.value)
                for candidate in original
            ):
                raise ValueError(f"selected value is not an original candidate: {item_key}")
        elif decision.decision == "manual_required":
            manual_count += 1
            if confirmed_by_key.get(item_key):
                raise ValueError(f"manual group unexpectedly confirmed: {item_key}")
            if sorted(map(signature, unresolved_by_key.get(item_key, [])), key=repr) != sorted(map(signature, original), key=repr):
                raise ValueError(f"manual unresolved candidates drifted: {item_key}")
        else:
            raise ValueError(f"unknown resolution decision for {item_key}: {decision.decision}")
    return {
        "policy_version": AUTO_POLICY_VERSION,
        "candidate_group_count": len(grouped),
        "candidate_observation_count": len(candidates),
        "decision_count": len(decisions),
        "auto_confirmed_group_count": auto_count,
        "manual_required_group_count": manual_count,
        "confirmed_preview_count": len(confirmed),
        "unresolved_observation_count": len(unresolved),
        "freeze_ready": manual_count == 0,
        "valid": True,
        "applicable": False,
    }
