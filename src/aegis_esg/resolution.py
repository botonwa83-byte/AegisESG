from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .models import Observation, ValueStatus


AUTO_POLICY_VERSION = "public-disclosure-v3"
AUTO_INDICATORS = {
    "Q_G_ROE", "Q_G_REVENUE_GROWTH", "Q_S_DIVIDEND_PER_SHARE", "Q_S_RD_RATE",
    "Q_G_DEBT_ASSET_RATE", "Q_G_ASSET_TURNOVER", "Q_G_AR_TURNOVER",
    "Q_G_CURRENT_ASSET_TURNOVER", "Q_G_TWO_FUNDS_RATE", "Q_G_CAPITAL_ACCUMULATION",
    "Q_G_ROA", "Q_G_OPERATING_MARGIN", "Q_G_CASH_REALIZATION",
    "Q_G_COST_REVENUE_RATE", "Q_G_EBITDA_INTEREST", "Q_G_CASH_CURRENT_LIABILITY",
    "Q_G_OPERATING_PROFIT_GROWTH",
}
ESG_AUTO_INDICATORS = {"Q_E_GHG_INTENSITY", "Q_E_ENERGY_INTENSITY", "Q_E_WATER_INTENSITY"}


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
            if item.value is not None and (annual_eligible or esg_eligible):
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
            elif derived_debt:
                reason = "consolidated_statement_year_end_derived"
            else:
                reason = "official_annual_direct_consistent"
            decision, selected_value = "auto_confirmed", f"{float(selected.value):g}"
        else:
            unresolved.extend(items)
            decision = "manual_required"
            reason = "indicator_not_auto_eligible" if key[2] not in AUTO_INDICATORS | ESG_AUTO_INDICATORS else "conflicting_or_ineligible_sources"
            selected_value = ""
        all_values = sorted({round(float(item.value), 8) for item in items if item.value is not None})
        decisions.append(ResolutionDecision(
            company_code=key[0], company_name=items[0].company_name, report_year=key[1],
            indicator_code=key[2], decision=decision, candidate_count=len(items),
            distinct_values="|".join(f"{value:g}" for value in all_values),
            selected_value=selected_value, policy_version=AUTO_POLICY_VERSION, reason=reason,
        ))
    return confirmed, unresolved, decisions
