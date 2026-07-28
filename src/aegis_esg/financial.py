from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Observation, ValueStatus


@dataclass(frozen=True)
class FinancialFact:
    company_code: str
    company_name: str
    report_year: int
    fact_code: str
    value: Decimal
    source_url: str = ""
    source_file: str = ""
    source_page: int | None = None


FACT_COLUMNS = (
    "company_code", "company_name", "report_year", "fact_code", "value",
    "source_url", "source_file", "source_page",
)


def read_financial_facts(path: str | Path) -> list[FinancialFact]:
    result = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            try:
                value = Decimal(row["value"].replace(",", ""))
            except (InvalidOperation, KeyError) as error:
                raise ValueError(f"财务事实第{line}行数值无效") from error
            result.append(FinancialFact(
                company_code=row["company_code"].strip(), company_name=row["company_name"].strip(),
                report_year=int(row["report_year"]), fact_code=row["fact_code"].strip(), value=value,
                source_url=(row.get("source_url") or "").strip(),
                source_file=(row.get("source_file") or "").strip(),
                source_page=int(row["source_page"]) if (row.get("source_page") or "").strip() else None,
            ))
    return result


def derive_financial_observations(facts: list[FinancialFact]) -> list[Observation]:
    grouped: dict[tuple[str, int], dict[str, FinancialFact]] = defaultdict(dict)
    names: dict[tuple[str, int], str] = {}
    for fact in facts:
        key = (fact.company_code, fact.report_year)
        if fact.fact_code in grouped[key]:
            raise ValueError(f"财务事实重复: {fact.company_code}/{fact.report_year}/{fact.fact_code}")
        grouped[key][fact.fact_code] = fact
        names[key] = fact.company_name
    result = []
    for (code, year), company_facts in grouped.items():
        for indicator_code, required, calculator in DERIVATIONS:
            if not all(name in company_facts for name in required):
                continue
            values = {name: company_facts[name].value for name in required}
            try:
                derived = calculator(values)
            except (ZeroDivisionError, InvalidOperation):
                continue
            sources = [company_facts[name] for name in required]
            source_url = next((item.source_url for item in sources if item.source_url), "")
            source_file = next((item.source_file for item in sources if item.source_file), "")
            pages = sorted({item.source_page for item in sources if item.source_page is not None})
            result.append(Observation(
                company_code=code, company_name=names[(code, year)], report_year=year,
                indicator_code=indicator_code, value=float(derived), status=ValueStatus.CONFIRMED,
                source_url=source_url, source_file=source_file,
                source_page=pages[0] if len(pages) == 1 else None,
                evidence_text="由财务事实自动计算: " + ",".join(required), confidence=1.0,
            ))
    return result


def _avg(values: dict[str, Decimal], left: str, right: str) -> Decimal:
    return (values[left] + values[right]) / Decimal(2)


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        raise ZeroDivisionError
    return numerator / denominator * Decimal(100)


DERIVATIONS = (
    ("Q_S_ENV_INVEST_RATE", ("environmental_investment", "revenue"), lambda v: _percent(v["environmental_investment"], v["revenue"])),
    ("Q_S_RD_RATE", ("rd_investment", "revenue"), lambda v: _percent(v["rd_investment"], v["revenue"])),
    ("Q_S_DONATION_RATE", ("public_welfare_investment", "revenue"), lambda v: _percent(v["public_welfare_investment"], v["revenue"])),
    ("Q_S_DIVIDEND_PER_SHARE", ("cash_dividend_total", "total_shares"), lambda v: v["cash_dividend_total"] / v["total_shares"]),
    ("Q_G_ROE", ("net_profit", "equity_begin", "equity_end"), lambda v: _percent(v["net_profit"], _avg(v, "equity_begin", "equity_end"))),
    ("Q_G_ROA", ("ebit", "assets_begin", "assets_end"), lambda v: _percent(v["ebit"], _avg(v, "assets_begin", "assets_end"))),
    ("Q_G_OPERATING_MARGIN", ("operating_profit", "revenue"), lambda v: _percent(v["operating_profit"], v["revenue"])),
    ("Q_G_EBITDA_MARGIN", ("net_profit", "income_tax", "interest_expense", "depreciation", "amortization", "revenue"), lambda v: _percent(v["net_profit"] + v["income_tax"] + v["interest_expense"] + v["depreciation"] + v["amortization"], v["revenue"])),
    ("Q_G_CASH_REALIZATION", ("cash_received_operating", "revenue"), lambda v: _percent(v["cash_received_operating"], v["revenue"])),
    ("Q_G_COST_REVENUE_RATE", ("cost_expense_total", "revenue"), lambda v: _percent(v["cost_expense_total"], v["revenue"])),
    ("Q_G_ASSET_TURNOVER", ("revenue", "assets_begin", "assets_end"), lambda v: v["revenue"] / _avg(v, "assets_begin", "assets_end")),
    ("Q_G_AR_TURNOVER", ("revenue", "accounts_receivable_gross_begin", "accounts_receivable_gross_end"), lambda v: v["revenue"] / _avg(v, "accounts_receivable_gross_begin", "accounts_receivable_gross_end")),
    ("Q_G_CURRENT_ASSET_TURNOVER", ("revenue", "current_assets_begin", "current_assets_end"), lambda v: v["revenue"] / _avg(v, "current_assets_begin", "current_assets_end")),
    ("Q_G_TWO_FUNDS_RATE", ("accounts_receivable_end", "inventory_end", "current_assets_end"), lambda v: _percent(v["accounts_receivable_end"] + v["inventory_end"], v["current_assets_end"])),
    ("Q_G_DEBT_ASSET_RATE", ("liabilities_end", "assets_end"), lambda v: _percent(v["liabilities_end"], v["assets_end"])),
    ("Q_G_EBITDA_INTEREST", ("ebit", "interest_expense"), lambda v: v["ebit"] / v["interest_expense"]),
    ("Q_G_QUICK_RATIO", ("quick_assets_end", "current_liabilities_end"), lambda v: _percent(v["quick_assets_end"], v["current_liabilities_end"])),
    ("Q_G_CASH_CURRENT_LIABILITY", ("operating_cashflow_net", "current_liabilities_end"), lambda v: _percent(v["operating_cashflow_net"], v["current_liabilities_end"])),
    ("Q_G_REVENUE_GROWTH", ("revenue", "revenue_previous"), lambda v: _percent(v["revenue"] - v["revenue_previous"], v["revenue_previous"])),
    ("Q_G_OPERATING_PROFIT_GROWTH", ("operating_profit", "operating_profit_previous"), lambda v: _percent(v["operating_profit"] - v["operating_profit_previous"], v["operating_profit_previous"])),
    ("Q_G_CAPITAL_ACCUMULATION", ("equity_begin", "equity_end"), lambda v: _percent(v["equity_end"] - v["equity_begin"], v["equity_begin"])),
)
