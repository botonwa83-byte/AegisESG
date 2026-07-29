from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .universe import UniverseCompany, _is_unclassified
from .universe_builder import read_exchange_snapshot


@dataclass(frozen=True)
class UniverseEvidenceTask:
    stock_code: str
    company_name: str
    exchange: str
    current_sub_industry: str
    snapshot_industry: str
    entity_id: str
    industry_status: str
    entity_status: str
    priority: int
    next_action: str
    snapshot_source_url: str
    snapshot_as_of_date: str


@dataclass(frozen=True)
class AppliedEvidenceDecision:
    stock_code: str
    decision: str
    final_included: bool
    final_sub_industry: str
    final_entity_id: str
    action: str
    evidence_url: str
    evidence_date: str
    reviewer: str
    reviewed_at: str
    rationale: str


def plan_universe_evidence(
    universe: Iterable[UniverseCompany], snapshot_path: str | Path,
    exchanges: Iterable[str] = (),
) -> tuple[list[UniverseEvidenceTask], dict]:
    snapshot_rows = read_exchange_snapshot(snapshot_path)
    snapshot = {item.stock_code: item for item in snapshot_rows}
    if len(snapshot) != len(snapshot_rows):
        raise ValueError("官方快照存在重复证券代码")
    exchange_filter = {item.strip().upper() for item in exchanges if item.strip()}
    tasks = []
    for company in universe:
        if not company.included:
            continue
        if exchange_filter and company.exchange not in exchange_filter:
            continue
        security = snapshot.get(company.stock_code)
        if security is None:
            industry_status = "snapshot_unmatched"
            snapshot_industry = ""
            source_url = ""
            as_of_date = ""
        else:
            snapshot_industry = security.industry
            source_url = security.source_url
            as_of_date = security.as_of_date
            industry_status = "pending_evidence" if _is_unclassified(company.sub_industry) else "classified"
        entity_status = "security_id_only" if company.entity_id == company.stock_code else "explicit_entity"
        if industry_status == "snapshot_unmatched":
            priority, action = 0, "resolve_snapshot_match"
        elif industry_status == "pending_evidence" and company.exchange == "HKEX":
            priority, action = 1, "collect_hkex_industry_and_chinese_name_evidence"
        elif industry_status == "pending_evidence":
            priority, action = 2, "review_energy_sub_industry_evidence"
        elif entity_status == "security_id_only":
            priority, action = 3, "review_entity_and_ah_relationship"
        else:
            priority, action = 9, "complete"
        tasks.append(UniverseEvidenceTask(
            company.stock_code, company.company_name, company.exchange,
            company.sub_industry, snapshot_industry, company.entity_id,
            industry_status, entity_status, priority, action, source_url, as_of_date,
        ))
    tasks.sort(key=lambda item: (item.priority, item.exchange, item.stock_code))
    industry_counts = Counter(item.industry_status for item in tasks)
    entity_counts = Counter(item.entity_status for item in tasks)
    action_counts = Counter(item.next_action for item in tasks)
    summary = {
        "included_company_count": len(tasks),
        "exchange_filter": sorted(exchange_filter),
        "industry_status_counts": dict(sorted(industry_counts.items())),
        "entity_status_counts": dict(sorted(entity_counts.items())),
        "next_action_counts": dict(sorted(action_counts.items())),
        "pending_industry_count": industry_counts["pending_evidence"],
        "snapshot_unmatched_count": industry_counts["snapshot_unmatched"],
        "publishable": not industry_counts["pending_evidence"] and not industry_counts["snapshot_unmatched"],
    }
    return tasks, summary


LEDGER_FIELDS = (
    "decision_id", "batch_id", "operation", "supersedes", "stock_code",
    "decision", "sub_industry", "entity_id", "evidence_url", "evidence_date",
    "reviewer", "reviewed_at", "rationale",
)


def merge_universe_evidence_batches(
    batch_paths: Iterable[str | Path],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict]:
    """Build an append-only decision ledger and its current active projection."""
    ledger: list[dict[str, str]] = []
    by_id: dict[str, dict[str, str]] = {}
    current_by_code: dict[str, str] = {}
    seen_batches: set[str] = set()
    for batch_path in batch_paths:
        with Path(batch_path).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows or not set(LEDGER_FIELDS).issubset(rows[0]):
            raise ValueError(f"证据批次字段不完整: {batch_path}")
        file_batch_ids = {(row.get("batch_id") or "").strip() for row in rows}
        if "" in file_batch_ids or len(file_batch_ids) != 1:
            raise ValueError(f"单个证据批次必须使用唯一非空batch_id: {batch_path}")
        batch_id = next(iter(file_batch_ids))
        if batch_id in seen_batches:
            raise ValueError(f"证据批次ID重复: {batch_id}")
        seen_batches.add(batch_id)
        for line, raw in enumerate(rows, 2):
            item = {key: (raw.get(key) or "").strip() for key in LEDGER_FIELDS}
            item["stock_code"] = item["stock_code"].upper()
            item["operation"] = item["operation"].lower()
            item["decision"] = item["decision"].lower()
            decision_id = item["decision_id"]
            if not decision_id or decision_id in by_id:
                raise ValueError(f"证据决定ID为空或重复: {decision_id or f'{batch_path}:{line}'}")
            if item["operation"] not in {"upsert", "revoke"}:
                raise ValueError(f"证据批次第{line}行operation必须为upsert或revoke")
            current_id = current_by_code.get(item["stock_code"], "")
            if item["operation"] == "upsert":
                _validate_evidence_decision(item, line)
                if current_id and item["supersedes"] != current_id:
                    raise ValueError(f"证券{item['stock_code']}的新版本必须supersede当前决定{current_id}")
                if not current_id and item["supersedes"]:
                    raise ValueError(f"证券{item['stock_code']}首个决定不能声明supersedes")
                current_by_code[item["stock_code"]] = decision_id
            else:
                _validate_ledger_signature(item, line)
                if not current_id or item["supersedes"] != current_id:
                    raise ValueError(f"证券{item['stock_code']}撤销必须指向当前决定")
                current_by_code.pop(item["stock_code"])
            item["ledger_state"] = "active" if item["operation"] == "upsert" else "revoked"
            if item["supersedes"]:
                previous = by_id.get(item["supersedes"])
                if previous is None or previous["stock_code"] != item["stock_code"]:
                    raise ValueError(f"supersedes未指向同证券的既有决定: {item['supersedes']}")
                previous["ledger_state"] = "superseded" if item["operation"] == "upsert" else "revoked"
            ledger.append(item)
            by_id[decision_id] = item
    active_rows = []
    for code, decision_id in sorted(current_by_code.items()):
        item = by_id[decision_id]
        active_rows.append({key: item[key] for key in (
            "stock_code", "decision", "sub_industry", "entity_id", "evidence_url",
            "evidence_date", "reviewer", "reviewed_at", "rationale",
        )})
    states = Counter(item["ledger_state"] for item in ledger)
    summary = {
        "batch_count": len(seen_batches),
        "ledger_decision_count": len(ledger),
        "active_decision_count": len(active_rows),
        "ledger_state_counts": dict(sorted(states.items())),
        "complete": True,
    }
    return active_rows, ledger, summary


def write_universe_evidence_ledger(
    active_path: str | Path, ledger_path: str | Path, summary_path: str | Path,
    active_rows: Iterable[dict[str, str]], ledger: Iterable[dict[str, str]], summary: dict,
) -> None:
    active_output = Path(active_path)
    active_output.parent.mkdir(parents=True, exist_ok=True)
    active_fields = (
        "stock_code", "decision", "sub_industry", "entity_id", "evidence_url",
        "evidence_date", "reviewer", "reviewed_at", "rationale",
    )
    with active_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=active_fields)
        writer.writeheader()
        writer.writerows(active_rows)
    ledger_output = Path(ledger_path)
    ledger_output.parent.mkdir(parents=True, exist_ok=True)
    with ledger_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(*LEDGER_FIELDS, "ledger_state"))
        writer.writeheader()
        writer.writerows(ledger)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_universe_evidence_plan(
    output_path: str | Path, summary_path: str | Path,
    tasks: Iterable[UniverseEvidenceTask], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(UniverseEvidenceTask.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in tasks)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_universe_evidence(
    universe: Iterable[UniverseCompany], decisions_path: str | Path,
) -> tuple[list[UniverseCompany], list[AppliedEvidenceDecision], dict]:
    rows = list(universe)
    by_code = {item.stock_code: item for item in rows}
    if len(by_code) != len(rows):
        raise ValueError("公司池存在重复证券代码")
    with Path(decisions_path).open(encoding="utf-8-sig", newline="") as stream:
        decisions = list(csv.DictReader(stream))
    required = {
        "stock_code", "decision", "sub_industry", "entity_id", "evidence_url",
        "evidence_date", "reviewer", "reviewed_at", "rationale",
    }
    if not decisions or not required.issubset(decisions[0]):
        raise ValueError("证据决定表字段不完整")
    normalized: dict[str, dict[str, str]] = {}
    for line, raw in enumerate(decisions, 2):
        item = {key: (raw.get(key) or "").strip() for key in required}
        code = item["stock_code"].upper()
        if code in normalized:
            raise ValueError(f"证据决定表证券代码重复: {code}")
        if code not in by_code:
            raise ValueError(f"证据决定未匹配公司池: {code}")
        item["stock_code"] = code
        item["decision"] = item["decision"].lower()
        _validate_evidence_decision(item, line)
        normalized[code] = item
    updated = []
    for company in rows:
        decision = normalized.get(company.stock_code)
        if not decision:
            updated.append(company)
            continue
        included = decision["decision"] == "include"
        updated.append(UniverseCompany(
            company.stock_code, company.company_name, company.exchange,
            decision["sub_industry"] or company.sub_industry, included,
            "" if included else decision["rationale"],
            decision["entity_id"].upper() or company.entity_id,
            company.source_url, company.as_of_date,
        ))
    updated = _deduplicate_explicit_ah_entities(updated, set(normalized))
    final = {item.stock_code: item for item in updated}
    audit_rows = []
    for code, decision in normalized.items():
        company = final[code]
        action = "include" if company.included else "exclude"
        if decision["decision"] == "include" and not company.included:
            action = "ah_duplicate_exclude"
        audit_rows.append(AppliedEvidenceDecision(
            code, decision["decision"], company.included, company.sub_industry,
            company.entity_id, action, decision["evidence_url"], decision["evidence_date"],
            decision["reviewer"], decision["reviewed_at"], decision["rationale"],
        ))
    audit_rows.sort(key=lambda item: item.stock_code)
    actions = Counter(item.action for item in audit_rows)
    summary = {
        "decision_count": len(audit_rows),
        "action_counts": dict(sorted(actions.items())),
        "included_security_count": sum(item.included for item in updated),
        "included_entity_count": len({item.entity_id for item in updated if item.included}),
        "ah_duplicate_excluded_count": actions["ah_duplicate_exclude"],
        "complete": True,
    }
    return updated, audit_rows, summary


def write_applied_universe_evidence(
    universe_path: str | Path, audit_path: str | Path, summary_path: str | Path,
    universe: Iterable[UniverseCompany], audit_rows: Iterable[AppliedEvidenceDecision], summary: dict,
) -> None:
    from .migration import write_augmented_universe

    write_augmented_universe(universe_path, universe)
    audit_output = Path(audit_path)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    with audit_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(AppliedEvidenceDecision.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in audit_rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_evidence_decision(item: dict[str, str], line: int) -> None:
    if item["decision"] not in {"include", "exclude"}:
        raise ValueError(f"证据决定表第{line}行decision必须为include或exclude")
    if not item["evidence_url"] or not item["reviewer"] or not item["rationale"]:
        raise ValueError(f"证据决定表第{line}行缺少证据、审核人或理由")
    if not re.match(r"^(https?://|data/|output/)", item["evidence_url"], re.I):
        raise ValueError(f"证据决定表第{line}行证据地址格式无效")
    try:
        date.fromisoformat(item["evidence_date"])
    except ValueError as error:
        raise ValueError(f"证据决定表第{line}行证据日期无效") from error
    try:
        reviewed = datetime.fromisoformat(item["reviewed_at"])
    except ValueError as error:
        raise ValueError(f"证据决定表第{line}行审核时间无效") from error
    if reviewed.tzinfo is None:
        raise ValueError(f"证据决定表第{line}行审核时间必须含时区")
    if item["decision"] == "include" and _is_unclassified(item["sub_industry"]):
        raise ValueError(f"证据决定表第{line}行纳入决定必须给出明确细分行业")
    if item["entity_id"] and re.search(r"\s", item["entity_id"]):
        raise ValueError(f"证据决定表第{line}行主体标识不能含空格")


def _validate_ledger_signature(item: dict[str, str], line: int) -> None:
    if not item["evidence_url"] or not item["reviewer"] or not item["rationale"]:
        raise ValueError(f"证据批次第{line}行撤销缺少证据、审核人或理由")
    if not re.match(r"^(https?://|data/|output/)", item["evidence_url"], re.I):
        raise ValueError(f"证据批次第{line}行证据地址格式无效")
    try:
        date.fromisoformat(item["evidence_date"])
        reviewed = datetime.fromisoformat(item["reviewed_at"])
    except ValueError as error:
        raise ValueError(f"证据批次第{line}行日期或审核时间无效") from error
    if reviewed.tzinfo is None:
        raise ValueError(f"证据批次第{line}行审核时间必须含时区")


def _deduplicate_explicit_ah_entities(
    rows: list[UniverseCompany], reviewed_codes: set[str],
) -> list[UniverseCompany]:
    groups: dict[str, list[UniverseCompany]] = {}
    for item in rows:
        if item.included and item.entity_id != item.stock_code:
            groups.setdefault(item.entity_id, []).append(item)
    replacements: dict[str, UniverseCompany] = {}
    order = {"SSE": 0, "SZSE": 1, "BSE": 2, "HKEX": 3}
    for entity_id, group in groups.items():
        if len(group) < 2:
            continue
        exchanges = {item.exchange for item in group}
        if "HKEX" not in exchanges or not exchanges.intersection({"SSE", "SZSE", "BSE"}):
            raise ValueError(f"重复主体不是可识别A/H组合: {entity_id}")
        if not {item.stock_code for item in group}.issubset(reviewed_codes):
            raise ValueError(f"A/H主体映射必须同时审核全部证券: {entity_id}")
        primary = min(group, key=lambda item: (order.get(item.exchange, 9), item.stock_code))
        for item in group:
            if item.stock_code == primary.stock_code:
                continue
            replacements[item.stock_code] = UniverseCompany(
                item.stock_code, item.company_name, item.exchange, item.sub_industry,
                False, f"同一主体重复上市，保留{primary.stock_code}", item.entity_id,
                item.source_url, item.as_of_date,
            )
    return [replacements.get(item.stock_code, item) for item in rows]
