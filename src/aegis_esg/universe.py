from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class UniverseCompany:
    stock_code: str
    company_name: str
    exchange: str
    sub_industry: str
    included: bool = True
    exclusion_reason: str = ""
    entity_id: str = ""
    source_url: str = ""
    as_of_date: str = ""


@dataclass(frozen=True)
class UniverseAudit:
    security_count: int
    included_security_count: int
    included_company_count: int
    completed_company_count: int
    expected_company_count: int
    universe_coverage_rate: float
    completed_coverage_rate: float
    exchanges: dict[str, int]
    missing_exchanges: tuple[str, ...]
    unclassified_count: int
    missing_source_count: int
    missing_date_count: int
    missing_entity_count: int
    duplicate_included_entity_count: int
    excluded_without_reason_count: int
    included_with_exclusion_reason_count: int
    publishable: bool

    def as_dict(self) -> dict:
        return {
            "security_count": self.security_count,
            "included_security_count": self.included_security_count,
            "included_company_count": self.included_company_count,
            "completed_company_count": self.completed_company_count,
            "expected_company_count": self.expected_company_count,
            "universe_coverage_rate": self.universe_coverage_rate,
            "completed_coverage_rate": self.completed_coverage_rate,
            "exchanges": self.exchanges,
            "missing_exchanges": list(self.missing_exchanges),
            "unclassified_count": self.unclassified_count,
            "missing_source_count": self.missing_source_count,
            "missing_date_count": self.missing_date_count,
            "missing_entity_count": self.missing_entity_count,
            "duplicate_included_entity_count": self.duplicate_included_entity_count,
            "excluded_without_reason_count": self.excluded_without_reason_count,
            "included_with_exclusion_reason_count": self.included_with_exclusion_reason_count,
            "publishable": self.publishable,
        }


def read_universe(path: str | Path) -> list[UniverseCompany]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    companies = []
    seen = set()
    for line, row in enumerate(rows, 2):
        code = row["stock_code"].strip().upper()
        if code in seen:
            raise ValueError(f"样本池第{line}行证券代码重复: {code}")
        seen.add(code)
        included = (row.get("included") or "true").strip().lower() in ("1", "true", "yes", "是")
        companies.append(UniverseCompany(
            stock_code=code,
            company_name=row["company_name"].strip(),
            exchange=(row.get("exchange") or _infer_exchange(code)).strip().upper(),
            sub_industry=(row.get("sub_industry") or "待分类").strip(),
            included=included,
            exclusion_reason=(row.get("exclusion_reason") or "").strip(),
            entity_id=(row.get("entity_id") or code).strip().upper(),
            source_url=(row.get("source_url") or "").strip(),
            as_of_date=(row.get("as_of_date") or "").strip(),
        ))
    return companies


def audit_universe(
    companies: Iterable[UniverseCompany], expected_company_count: int,
    completed_codes: Iterable[str] = (),
    required_exchanges: Iterable[str] = ("SSE", "SZSE", "BSE", "HKEX"),
) -> UniverseAudit:
    rows = list(companies)
    included = [item for item in rows if item.included]
    entity_keys = [item.entity_id or item.stock_code for item in included]
    entities = set(entity_keys)
    included_codes = {item.stock_code for item in included}
    completed = included_codes.intersection(code.strip().upper() for code in completed_codes)
    exchange_counts = dict(sorted(Counter(item.exchange for item in included).items()))
    missing = tuple(exchange for exchange in required_exchanges if exchange not in exchange_counts)
    unclassified = sum(item.sub_industry in ("", "待分类") for item in included)
    missing_source = sum(not item.source_url for item in included)
    missing_date = sum(not item.as_of_date for item in included)
    missing_entity = sum(not item.entity_id for item in included)
    duplicate_entities = len(entity_keys) - len(entities)
    excluded_without_reason = sum(not item.included and not item.exclusion_reason for item in rows)
    included_with_reason = sum(item.included and bool(item.exclusion_reason) for item in rows)
    evidence_issues = (
        missing_source, missing_date, missing_entity, duplicate_entities,
        excluded_without_reason, included_with_reason,
    )
    expected = max(expected_company_count, 0)
    universe_rate = len(entities) / expected if expected else 0.0
    completed_rate = len(completed) / expected if expected else 0.0
    return UniverseAudit(
        security_count=len(rows), included_security_count=len(included),
        included_company_count=len(entities), completed_company_count=len(completed),
        expected_company_count=expected, universe_coverage_rate=universe_rate,
        completed_coverage_rate=completed_rate, exchanges=exchange_counts,
        missing_exchanges=missing, unclassified_count=unclassified,
        missing_source_count=missing_source, missing_date_count=missing_date,
        missing_entity_count=missing_entity,
        duplicate_included_entity_count=duplicate_entities,
        excluded_without_reason_count=excluded_without_reason,
        included_with_exclusion_reason_count=included_with_reason,
        publishable=(
            len(entities) == expected and len(completed) == expected
            and not missing and not unclassified and not any(evidence_issues)
        ),
    )


def write_universe_audit(path: str | Path, audit: UniverseAudit) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _infer_exchange(code: str) -> str:
    if code.endswith(".SH"):
        return "SSE"
    if code.endswith(".SZ"):
        return "SZSE"
    if code.endswith(".HK"):
        return "HKEX"
    if code.endswith(".BJ"):
        return "BSE"
    return "UNKNOWN"
