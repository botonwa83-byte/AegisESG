from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .registry import normalize_company_name


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
