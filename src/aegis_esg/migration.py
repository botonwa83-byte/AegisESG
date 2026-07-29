from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .universe import UniverseCompany
from .universe_builder import read_exchange_snapshot


@dataclass(frozen=True)
class MigrationDecision:
    stock_code: str
    historical_name: str
    current_name: str
    exchange: str
    historical_rank: str
    historical_esg_score: str
    decision: str
    reason: str
    requires_review: bool


@dataclass(frozen=True)
class ProvenanceBinding:
    stock_code: str
    universe_name: str
    snapshot_name: str
    included: bool
    status: str
    source_action: str
    date_action: str
    entity_action: str
    reason: str


def plan_historical_migration(
    historical_registry: str | Path, snapshots: Iterable[UniverseCompany],
    code_aliases: dict[str, str] | None = None,
) -> tuple[list[MigrationDecision], dict]:
    with Path(historical_registry).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"stock_code", "company_name", "company_abbr", "exchange", "st_flag"}
    missing = required.difference(rows[0] if rows else ())
    if missing:
        raise ValueError(f"历史公司表缺少字段: {','.join(sorted(missing))}")
    snapshot_rows = list(snapshots)
    current = {item.stock_code.upper(): item for item in snapshot_rows}
    available_exchanges = {item.exchange.upper() for item in snapshot_rows}
    aliases = {key.upper(): value.upper() for key, value in (code_aliases or {}).items()}
    decisions = []
    for row in rows:
        historical_code = row["stock_code"].strip().upper()
        code = aliases.get(historical_code, historical_code)
        exchange = row["exchange"].strip().upper()
        if historical_code in aliases:
            exchange = _exchange_from_code(code)
        match = current.get(code)
        historical_st = _truthy(row.get("st_flag")) or _is_st(row.get("company_abbr", ""))
        current_st = bool(match and _is_st(match.company_name))
        if exchange == "UNKNOWN" or code in ("", "#N/A"):
            decision, reason, review = "manual_review", "证券代码缺失或格式异常", True
        elif current_st or (match is None and historical_st):
            decision, reason, review = "exclude", "ST/*ST排除", False
        elif exchange not in available_exchanges:
            decision, reason, review = "pending_snapshot", f"{exchange}官方快照尚未接入", True
        elif match is None:
            decision, reason, review = "manual_review", "未匹配当前沪深正常上市底表", True
        else:
            decision, reason, review = "provisional_include", "历史能源样本且当前仍正常上市", False
        decisions.append(MigrationDecision(
            code, row["company_name"].strip(), match.company_name if match else "", exchange,
            (row.get("historical_rank") or "").strip(),
            (row.get("historical_esg_score") or "").strip(), decision, reason, review,
        ))
    counts = Counter(item.decision for item in decisions)
    audit = {
        "historical_company_count": len(decisions),
        "decision_counts": dict(sorted(counts.items())),
        "provisional_company_count": counts["provisional_include"],
        "excluded_company_count": counts["exclude"],
        "requires_review_count": sum(item.requires_review for item in decisions),
        "snapshot_exchanges": sorted(available_exchanges),
        "warning": "迁移结果是候选计划；最新行业口径和A/H主体关系完成前不得冻结正式样本。",
    }
    return decisions, audit


def write_migration_plan(path: str | Path, audit_path: str | Path, rows, audit: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(MigrationDecision.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in rows)
    audit_output = Path(audit_path)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    audit_output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_candidate_universe(path: str | Path, rows: Iterable[MigrationDecision]) -> None:
    """Write a standard universe without promoting provisional rows to a final release."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "stock_code", "company_name", "exchange", "sub_industry", "included",
        "exclusion_reason", "entity_id", "source_url", "as_of_date",
    )
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in rows:
            included = item.decision == "provisional_include"
            writer.writerow({
                "stock_code": item.stock_code,
                "company_name": item.current_name or item.historical_name,
                "exchange": item.exchange,
                "sub_industry": "历史能源样本待复核",
                "included": "true" if included else "false",
                "exclusion_reason": "" if included else item.reason,
                "entity_id": item.stock_code,
                "source_url": "",
                "as_of_date": "",
            })


def augment_candidate_universe(
    base: Iterable[UniverseCompany], additions_path: str | Path,
    snapshot_path: str | Path,
) -> list[UniverseCompany]:
    rows = list(base)
    existing = {item.stock_code for item in rows}
    snapshot = {item.stock_code: item for item in read_exchange_snapshot(snapshot_path)}
    with Path(additions_path).open(encoding="utf-8-sig", newline="") as stream:
        additions = list(csv.DictReader(stream))
    required = {"stock_code", "evidence_url", "reason"}
    if not additions or not required.issubset(additions[0]):
        raise ValueError("新增候选表缺少stock_code/evidence_url/reason字段")
    seen: set[str] = set()
    for item in additions:
        code = item["stock_code"].strip().upper()
        if code in seen:
            raise ValueError(f"新增候选表代码重复: {code}")
        seen.add(code)
        security = snapshot.get(code)
        if security is None:
            raise ValueError(f"新增候选未匹配当前官方快照: {code}")
        if not item["evidence_url"].strip() or not item["reason"].strip():
            raise ValueError(f"新增候选缺少纳入证据: {code}")
        if code in existing:
            continue
        rows.append(UniverseCompany(
            code, security.company_name, security.exchange, "参考榜单能源种子待行业复核",
            True, "", code, item["evidence_url"].strip(), security.as_of_date,
        ))
        existing.add(code)
    return rows


def write_augmented_universe(path: str | Path, rows: Iterable[UniverseCompany]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(UniverseCompany.__annotations__)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(item) for item in rows)


def bind_snapshot_provenance(
    universe: Iterable[UniverseCompany], snapshot_path: str | Path,
) -> tuple[list[UniverseCompany], list[ProvenanceBinding], dict]:
    """Fill missing official provenance by exact security-code match only."""
    rows = list(universe)
    snapshot_rows = read_exchange_snapshot(snapshot_path)
    snapshot: dict[str, object] = {}
    for item in snapshot_rows:
        if item.stock_code in snapshot:
            raise ValueError(f"官方快照证券代码重复: {item.stock_code}")
        snapshot[item.stock_code] = item
    enriched: list[UniverseCompany] = []
    bindings: list[ProvenanceBinding] = []
    for item in rows:
        security = snapshot.get(item.stock_code)
        if security is None:
            enriched.append(item)
            bindings.append(ProvenanceBinding(
                item.stock_code, item.company_name, "", item.included, "unmatched", "unchanged",
                "unchanged", "unchanged", "证券代码未匹配官方快照",
            ))
            continue
        source = item.source_url or security.source_url
        as_of_date = item.as_of_date or security.as_of_date
        entity_id = item.entity_id or security.entity_id
        entity_conflict = (
            bool(item.entity_id and security.entity_id)
            and item.entity_id != item.stock_code
            and security.entity_id != item.stock_code
            and item.entity_id != security.entity_id
        )
        status = "entity_conflict" if entity_conflict else (
            "name_difference" if item.company_name != security.company_name else "matched"
        )
        reason = (
            f"主体标识冲突:{item.entity_id}!={security.entity_id}" if entity_conflict else
            ("证券代码精确匹配，名称不同需保留审计" if status == "name_difference" else "证券代码及名称匹配")
        )
        enriched.append(UniverseCompany(
            item.stock_code, item.company_name, item.exchange, item.sub_industry,
            item.included, item.exclusion_reason, entity_id, source, as_of_date,
        ))
        bindings.append(ProvenanceBinding(
            item.stock_code, item.company_name, security.company_name, item.included, status,
            "filled" if not item.source_url and source else "preserved",
            "filled" if not item.as_of_date and as_of_date else "preserved",
            "filled" if not item.entity_id and entity_id else "preserved", reason,
        ))
    counts = Counter(item.status for item in bindings)
    included_unmatched = sum(item.included and item.status == "unmatched" for item in bindings)
    included_conflicts = sum(item.included and item.status == "entity_conflict" for item in bindings)
    audit = {
        "universe_security_count": len(rows),
        "snapshot_security_count": len(snapshot_rows),
        "status_counts": dict(sorted(counts.items())),
        "matched_code_count": len(rows) - counts["unmatched"],
        "unmatched_count": counts["unmatched"],
        "included_unmatched_count": included_unmatched,
        "name_difference_count": counts["name_difference"],
        "entity_conflict_count": counts["entity_conflict"],
        "included_entity_conflict_count": included_conflicts,
        "source_filled_count": sum(item.source_action == "filled" for item in bindings),
        "date_filled_count": sum(item.date_action == "filled" for item in bindings),
        "complete": not included_unmatched and not included_conflicts,
    }
    return enriched, bindings, audit


def write_provenance_binding(
    universe_path: str | Path, audit_path: str | Path, summary_path: str | Path,
    universe: Iterable[UniverseCompany], bindings: Iterable[ProvenanceBinding], summary: dict,
) -> None:
    write_augmented_universe(universe_path, universe)
    audit_output = Path(audit_path)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    with audit_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(ProvenanceBinding.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in bindings)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "是")


def _is_st(name: str) -> bool:
    return bool(re.match(r"^\*?ST", str(name or "").strip(), re.IGNORECASE))


def _exchange_from_code(code: str) -> str:
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE", "HK": "HKEX"}.get(code[-2:], "UNKNOWN")
