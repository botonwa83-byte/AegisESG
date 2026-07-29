from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .registry import normalize_company_name
from .universe import UniverseCompany


@dataclass(frozen=True)
class IssuerContinuityReview:
    stock_code: str
    historical_stock_code: str
    historical_name: str
    historical_abbr: str
    current_chinese_name: str
    current_chinese_short_name: str
    hsic_sub_sector: str
    continuity_status: str
    industry_review_status: str
    h_share_clue: bool
    priority: int
    next_action: str
    evidence_url: str
    resolution_evidence_url: str
    reason: str


@dataclass(frozen=True)
class AppliedContinuityDecision:
    decision_id: str
    stock_code: str
    outcome: str
    related_a_code: str
    final_entity_id: str
    final_included: bool
    action: str
    evidence_url: str
    evidence_date: str
    reviewer: str
    reviewed_at: str
    rationale: str


def audit_hkex_issuer_continuity(
    historical_registry_path: str | Path, profiles_path: str | Path,
    drafts_path: str | Path, code_map_paths: Iterable[str | Path] = (),
) -> tuple[list[IssuerContinuityReview], dict]:
    historical = _read_csv(historical_registry_path)
    profiles = _read_csv(profiles_path)
    drafts = _read_csv(drafts_path)
    aliases, alias_evidence = _read_code_maps(code_map_paths)
    historical_by_code = {}
    for row in historical:
        old_code = row.get("stock_code", "").strip().upper()
        code = aliases.get(old_code, old_code)
        if row.get("exchange", "").strip().upper() != "HKEX" and not code.endswith(".HK"):
            continue
        if code in historical_by_code:
            raise ValueError(f"历史港股代码映射后重复: {code}")
        historical_by_code[code] = (old_code, row)
    draft_by_code = {row["stock_code"].strip().upper(): row for row in drafts}
    if len(draft_by_code) != len(drafts):
        raise ValueError("港股审核草案证券代码重复")
    result = []
    seen: set[str] = set()
    for profile in profiles:
        code = profile["stock_code"].strip().upper()
        if code in seen:
            raise ValueError(f"港交所发行人资料证券代码重复: {code}")
        seen.add(code)
        match = historical_by_code.get(code)
        old_code, history = match if match else ("", {})
        historical_name = history.get("company_name", "").strip()
        historical_abbr = history.get("company_abbr", "").strip()
        current_name = profile["chinese_name"].strip()
        current_short = profile["chinese_short_name"].strip()
        if not match:
            continuity = "missing_historical_match"
        elif old_code in aliases:
            continuity = "signed_code_resolution"
        elif _continuity_name(historical_name) == _continuity_name(current_name):
            continuity = "exact_name"
        elif historical_abbr and _continuity_name(historical_abbr) == _continuity_name(current_short):
            continuity = "exact_short_name"
        else:
            continuity = "name_difference"
        draft = draft_by_code.get(code, {})
        industry_status = draft.get("review_status", "missing_draft").strip()
        h_share = bool(re.search(r"(?:-|－)\s*H股$", current_name, re.I))
        if industry_status == "manual_review":
            priority, action = 0, "review_issuer_identity_and_industry"
        elif continuity == "missing_historical_match":
            priority, action = 1, "verify_signed_code_resolution"
        elif continuity == "name_difference":
            priority, action = 2, "verify_name_continuity"
        elif h_share:
            priority, action = 3, "review_ah_relationship"
        else:
            priority, action = 9, "continuity_name_check_complete"
        reason = {
            "missing_historical_match": "当前代码未直接匹配历史港股记录",
            "signed_code_resolution": "当前代码由带官方证据的历史代码解析确认",
            "exact_name": "去除组织形式和H股后缀后名称字符级一致",
            "exact_short_name": "公司简称字符级一致",
            "name_difference": "历史与当前名称不做简繁或模糊自动归并，需证据复核",
        }[continuity]
        result.append(IssuerContinuityReview(
            code, old_code, historical_name, historical_abbr, current_name, current_short,
            profile["hsic_sub_sector"].strip(), continuity, industry_status, h_share,
            priority, action, profile["source_url"].strip(), alias_evidence.get(old_code, ""), reason,
        ))
    result.sort(key=lambda item: (item.priority, item.stock_code))
    continuity_counts = Counter(item.continuity_status for item in result)
    action_counts = Counter(item.next_action for item in result)
    summary = {
        "profile_count": len(profiles),
        "review_count": len(result),
        "continuity_status_counts": dict(sorted(continuity_counts.items())),
        "next_action_counts": dict(sorted(action_counts.items())),
        "h_share_clue_count": sum(item.h_share_clue for item in result),
        "manual_industry_review_count": sum(item.industry_review_status == "manual_review" for item in result),
        "unresolved_continuity_count": sum(item.continuity_status in {"name_difference", "missing_historical_match"} for item in result),
        "auto_merged_count": 0,
        "complete": False,
    }
    return result, summary


def write_issuer_continuity_audit(
    output_path: str | Path, summary_path: str | Path,
    rows: Iterable[IssuerContinuityReview], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(IssuerContinuityReview.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_issuer_continuity_decisions(
    universe: Iterable[UniverseCompany], continuity_audit_path: str | Path,
    decisions_path: str | Path,
) -> tuple[list[UniverseCompany], list[AppliedContinuityDecision], dict]:
    companies = list(universe)
    by_code = {item.stock_code: item for item in companies}
    if len(by_code) != len(companies):
        raise ValueError("公司池存在重复证券代码")
    review_rows = _read_csv(continuity_audit_path)
    review_by_code = {row["stock_code"].strip().upper(): row for row in review_rows}
    if len(review_by_code) != len(review_rows):
        raise ValueError("发行人连续性审计证券代码重复")
    decisions = _read_csv(decisions_path)
    required = {
        "decision_id", "stock_code", "outcome", "related_a_code", "entity_id",
        "evidence_url", "evidence_date", "reviewer", "reviewed_at", "rationale",
    }
    if not decisions or not required.issubset(decisions[0]):
        raise ValueError("发行人连续性决定字段不完整")
    normalized = {}
    decision_ids = set()
    for line, raw in enumerate(decisions, 2):
        item = {key: (raw.get(key) or "").strip() for key in required}
        item["stock_code"] = item["stock_code"].upper()
        item["related_a_code"] = item["related_a_code"].upper()
        item["entity_id"] = item["entity_id"].upper()
        item["outcome"] = item["outcome"].lower()
        _validate_continuity_decision(item, line, review_by_code, by_code)
        if item["decision_id"] in decision_ids:
            raise ValueError(f"发行人连续性决定ID重复: {item['decision_id']}")
        if item["stock_code"] in normalized:
            raise ValueError(f"发行人连续性决定证券代码重复: {item['stock_code']}")
        decision_ids.add(item["decision_id"])
        normalized[item["stock_code"]] = item
    updated = dict(by_code)
    applied = []
    for code, item in normalized.items():
        company = updated[code]
        outcome = item["outcome"]
        action = "continuity_confirmed"
        if outcome == "new_issuer":
            company = UniverseCompany(
                company.stock_code, company.company_name, company.exchange, company.sub_industry,
                False, f"发行人变更，历史纳入依据失效:{item['rationale']}", company.entity_id,
                company.source_url, company.as_of_date,
            )
            updated[code] = company
            action = "exclude_historical_carryover"
        elif outcome == "ah_same_entity":
            related = updated[item["related_a_code"]]
            entity_id = item["entity_id"]
            updated[item["related_a_code"]] = UniverseCompany(
                related.stock_code, related.company_name, related.exchange, related.sub_industry,
                related.included, related.exclusion_reason, entity_id, related.source_url, related.as_of_date,
            )
            company = UniverseCompany(
                company.stock_code, company.company_name, company.exchange, company.sub_industry,
                False, f"同一主体重复上市，保留{related.stock_code}", entity_id,
                company.source_url, company.as_of_date,
            )
            updated[code] = company
            action = "exclude_h_share_keep_a_share"
        applied.append(AppliedContinuityDecision(
            item["decision_id"], code, outcome, item["related_a_code"],
            updated[code].entity_id, updated[code].included, action,
            item["evidence_url"], item["evidence_date"], item["reviewer"],
            item["reviewed_at"], item["rationale"],
        ))
    required_review_codes = {
        code for code, row in review_by_code.items()
        if row.get("next_action") != "continuity_name_check_complete"
    }
    unresolved = required_review_codes.difference(normalized)
    actions = Counter(item.action for item in applied)
    result = [updated[item.stock_code] for item in companies]
    summary = {
        "decision_count": len(applied),
        "action_counts": dict(sorted(actions.items())),
        "required_review_count": len(required_review_codes),
        "unresolved_review_count": len(unresolved),
        "unresolved_stock_codes": sorted(unresolved),
        "included_security_count": sum(item.included for item in result),
        "complete": not unresolved,
    }
    return result, sorted(applied, key=lambda item: item.stock_code), summary


def write_applied_continuity_decisions(
    universe_path: str | Path, audit_path: str | Path, summary_path: str | Path,
    universe: Iterable[UniverseCompany], decisions: Iterable[AppliedContinuityDecision], summary: dict,
) -> None:
    from .migration import write_augmented_universe

    write_augmented_universe(universe_path, universe)
    audit_output = Path(audit_path)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    with audit_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(AppliedContinuityDecision.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in decisions)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_continuity_decision(item, line, review_by_code, company_by_code) -> None:
    if not item["decision_id"] or not item["reviewer"] or not item["rationale"] or not item["evidence_url"]:
        raise ValueError(f"连续性决定第{line}行缺少决定ID、证据、审核人或理由")
    if item["stock_code"] not in review_by_code or item["stock_code"] not in company_by_code:
        raise ValueError(f"连续性决定第{line}行证券未匹配审计和公司池")
    if item["outcome"] not in {"same_issuer", "new_issuer", "ah_same_entity"}:
        raise ValueError(f"连续性决定第{line}行outcome无效")
    if not re.match(r"^(https?://|data/|output/)", item["evidence_url"], re.I):
        raise ValueError(f"连续性决定第{line}行证据地址无效")
    try:
        date.fromisoformat(item["evidence_date"])
        reviewed_at = datetime.fromisoformat(item["reviewed_at"])
    except ValueError as error:
        raise ValueError(f"连续性决定第{line}行日期无效") from error
    if reviewed_at.tzinfo is None:
        raise ValueError(f"连续性决定第{line}行审核时间必须含时区")
    if item["outcome"] == "ah_same_entity":
        related = company_by_code.get(item["related_a_code"])
        if related is None or related.exchange not in {"SSE", "SZSE", "BSE"} or not related.included:
            raise ValueError(f"连续性决定第{line}行A股代码未匹配当前纳入证券")
        if not item["entity_id"] or item["entity_id"] in {item["stock_code"], item["related_a_code"]}:
            raise ValueError(f"连续性决定第{line}行A/H映射必须提供独立主体标识")
    elif item["related_a_code"] or item["entity_id"]:
        raise ValueError(f"连续性决定第{line}行非A/H结论不能填写A股代码或主体标识")


def _continuity_name(value: str) -> str:
    value = re.sub(r"\s*(?:-|－)\s*H股$", "", value.strip(), flags=re.I)
    return normalize_company_name(value)


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _read_code_maps(paths: Iterable[str | Path]) -> tuple[dict[str, str], dict[str, str]]:
    aliases = {}
    evidence = {}
    for path in paths:
        for row in _read_csv(path):
            old = (row.get("old_code") or row.get("old_stock_code") or "").strip().upper()
            new = (row.get("new_code") or row.get("new_stock_code") or "").strip().upper()
            if not old or not new:
                raise ValueError(f"代码映射缺少old_code/new_code: {path}")
            if old in aliases and aliases[old] != new:
                raise ValueError(f"代码映射冲突: {old}")
            aliases[old] = new
            evidence[old] = (row.get("evidence_url") or "").strip()
    return aliases, evidence
