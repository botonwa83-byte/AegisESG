"""正式发布授权门禁，对齐 DL/T 2971—2025 评价实施要求。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .grade import GRADE_RULE_VERSION


FORMAL_ALGORITHM_VERSION = "formal_rank_fixed_v1"
RELEASE_MANIFEST_VERSION = "release-authorization-v1"
REQUIRED_ROLES = {"methodology_owner", "data_reviewer"}
DLT_STANDARD_REF = "DL/T 2971—2025"
DLT_EVALUATION_MODE = "third_party_active"
RESULT_VALIDITY_DAYS = 365
ALLOWED_GRADES = frozenset({"AAA", "AA", "A", "BBB", "BB", "B", "C", "NA"})
COMMITTEE_ROLE = "evaluation_lead"


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seal_release_validity(valid_from: datetime | None = None) -> dict[str, str | int]:
    """按行标8.2.5将评价结果有效期定为一年。"""
    start = valid_from or datetime.now(timezone.utc)
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("评价结果生效时间必须包含时区")
    end = start + timedelta(days=RESULT_VALIDITY_DAYS)
    return {
        "valid_from": start.isoformat(),
        "valid_until": end.isoformat(),
        "result_validity_days": RESULT_VALIDITY_DAYS,
    }


def check_release_effective(
    manifest: dict[str, Any], as_of: datetime | None = None,
) -> dict[str, Any]:
    """检查授权清单是否仍在一年有效期内。"""
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("有效性检查时间必须包含时区")
    valid_from = _parse_aware(manifest.get("valid_from"), "valid_from")
    valid_until = _parse_aware(manifest.get("valid_until"), "valid_until")
    if valid_from is None or valid_until is None:
        raise ValueError("正式发布清单缺少一年有效期字段valid_from/valid_until")
    expected_until = valid_from + timedelta(days=int(manifest.get("result_validity_days") or RESULT_VALIDITY_DAYS))
    if abs((valid_until - expected_until).total_seconds()) > 1:
        raise ValueError("valid_until必须等于valid_from加一年有效期")
    effective = valid_from <= as_of <= valid_until
    return {
        "standard_ref": manifest.get("standard_ref", DLT_STANDARD_REF),
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "as_of": as_of.isoformat(),
        "effective": effective,
        "expired": as_of > valid_until,
        "not_yet_effective": as_of < valid_from,
    }


def validate_graded_ranking(results: list[Any]) -> dict[str, Any]:
    """正式发布前确认每家公司已按表1挂接级别。"""
    if not results:
        raise ValueError("正式发布排名结果不得为空")
    missing: list[str] = []
    counts: dict[str, int] = {grade: 0 for grade in sorted(ALLOWED_GRADES)}
    for item in results:
        if hasattr(item, "company_code"):
            code = str(item.company_code)
            grade = str(getattr(item, "grade", "") or "")
        else:
            code = str(item.get("company_code", ""))
            grade = str(item.get("grade") or "")
        if grade not in ALLOWED_GRADES:
            missing.append(code or "<unknown>")
            continue
        counts[grade] += 1
    if missing:
        preview = "、".join(missing[:5])
        raise ValueError(f"正式发布排名缺少DL/T 2971级别: {preview}")
    return {
        "grade_rule_version": GRADE_RULE_VERSION,
        "graded_company_count": len(results),
        "grade_counts": counts,
        "na_count": counts["NA"],
        "complete": True,
    }


def validate_release_authorization(
    manifest_path: str | Path, input_path: str | Path, methodology_path: str | Path,
    missing_strategy: str, completion_report_path: str | Path | None = None,
    require_dlt_process: bool = False,
    as_of: datetime | None = None,
) -> dict:
    with Path(manifest_path).open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("manifest_version") != RELEASE_MANIFEST_VERSION:
        raise ValueError("正式发布授权清单版本无效或已过期")
    if manifest.get("algorithm_version") != FORMAL_ALGORITHM_VERSION:
        raise ValueError("正式发布算法版本未授权或已过期")
    expected = {
        "input_sha256": sha256_file(input_path),
        "methodology_sha256": sha256_file(methodology_path),
        "missing_strategy_version": missing_strategy,
    }
    for field, actual in expected.items():
        if manifest.get(field) != actual:
            raise ValueError(f"正式发布授权清单{field}不匹配")
    if completion_report_path is not None:
        completion_path = Path(completion_report_path)
        try:
            with completion_path.open(encoding="utf-8") as stream:
                completion = json.load(stream)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("正式发布完成度报告无效") from error
        gates = completion.get("gates") if isinstance(completion, dict) else None
        if not isinstance(completion, dict) or completion.get("publishable") is not True:
            raise ValueError("六道完成门禁未全部通过，不得授权正式发布")
        if not isinstance(gates, dict) or len(gates) != 6 or not all(
            isinstance(gate, dict) and gate.get("complete") is True for gate in gates.values()
        ):
            raise ValueError("六道完成门禁未全部通过，不得授权正式发布")
        if manifest.get("completion_report_sha256") != sha256_file(completion_path):
            raise ValueError("正式发布授权清单completion_report_sha256不匹配")
    if manifest.get("scope") != "official_release":
        raise ValueError("授权清单不得从研究或预览域提升为正式发布")
    approvals = manifest.get("approvals")
    if not isinstance(approvals, list):
        raise ValueError("正式发布授权清单缺少双人审批")
    identities = set()
    roles = set()
    for approval in approvals:
        identity, role = _validate_approval_entry(approval, "正式发布审批")
        identities.add(identity)
        roles.add(role)
    if len(identities) < 2 or not REQUIRED_ROLES.issubset(roles):
        raise ValueError("正式发布需要不同人员完成方法论和数据双重审批")

    validity = None
    has_validity = bool(str(manifest.get("valid_from") or "").strip() and str(manifest.get("valid_until") or "").strip())
    if require_dlt_process or has_validity:
        validity = check_release_effective(manifest, as_of=as_of)
        if require_dlt_process and not validity["effective"]:
            raise ValueError("正式发布不在DL/T 2971一年有效期内")
        standard_ref = str(manifest.get("standard_ref") or "").strip()
        if require_dlt_process and standard_ref and standard_ref != DLT_STANDARD_REF:
            raise ValueError("正式发布标准引用必须为DL/T 2971—2025")

    committee = manifest.get("committee_approvals")
    committee_count = 0
    if isinstance(committee, list):
        filled = [item for item in committee if str(item.get("reviewer", "")).strip()]
        if require_dlt_process and not filled:
            raise ValueError("DL/T 2971评价程序要求评价工作组组长(evaluation_lead)签名")
        for approval in filled:
            identity, role = _validate_approval_entry(approval, "评价委员会审批")
            if role != COMMITTEE_ROLE:
                raise ValueError("评价委员会角色必须为evaluation_lead")
            if identity in identities:
                raise ValueError("评价工作组组长不得与方法论/数据审批人为同一人")
            committee_count += 1
    elif require_dlt_process:
        raise ValueError("DL/T 2971评价程序要求committee_approvals")

    report = {
        "manifest_version": RELEASE_MANIFEST_VERSION,
        "algorithm_version": FORMAL_ALGORITHM_VERSION,
        "manifest_sha256": sha256_file(manifest_path),
        "approval_count": len(approvals),
        "authorized": True,
        "require_dlt_process": require_dlt_process,
        "standard_ref": manifest.get("standard_ref") or DLT_STANDARD_REF,
        "evaluation_mode": manifest.get("evaluation_mode") or DLT_EVALUATION_MODE,
        "committee_approval_count": committee_count,
        "grade_rule_version": GRADE_RULE_VERSION,
    }
    if validity is not None:
        report["validity"] = validity
    return report


def prepare_release_authorization(
    input_path: str | Path, methodology_path: str | Path, missing_strategy: str,
    completion_report_path: str | Path | None = None,
    seal_validity: bool = False,
    valid_from: datetime | None = None,
) -> dict:
    manifest = {
        "manifest_version": RELEASE_MANIFEST_VERSION,
        "algorithm_version": FORMAL_ALGORITHM_VERSION,
        "scope": "official_release",
        "standard_ref": DLT_STANDARD_REF,
        "evaluation_mode": DLT_EVALUATION_MODE,
        "result_validity_days": RESULT_VALIDITY_DAYS,
        "valid_from": "",
        "valid_until": "",
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "methodology_path": str(methodology_path),
        "methodology_sha256": sha256_file(methodology_path),
        "missing_strategy_version": missing_strategy,
        "approvals": [
            {"reviewer": "", "role": "methodology_owner", "reviewed_at": "", "note": ""},
            {"reviewer": "", "role": "data_reviewer", "reviewed_at": "", "note": ""},
        ],
        "committee_approvals": [
            {"reviewer": "", "role": COMMITTEE_ROLE, "reviewed_at": "", "note": ""},
        ],
        "authorized": False,
        "notice": (
            "未签名模板；系统不得填写审核人或提升为正式发布。"
            "行标默认评价形式为第三方主动评价(third_party_active)；"
            "结果有效期一年，启用require_dlt_process前须填写valid_from/valid_until与evaluation_lead。"
        ),
    }
    if seal_validity:
        manifest.update(seal_release_validity(valid_from))
    if completion_report_path is not None:
        manifest["completion_report_path"] = str(completion_report_path)
        manifest["completion_report_sha256"] = sha256_file(completion_report_path)
    return manifest


def _parse_aware(value: Any, field: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"正式发布{field}时间格式无效") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"正式发布{field}必须包含时区")
    return parsed


def _validate_approval_entry(approval: Any, label: str) -> tuple[str, str]:
    if not isinstance(approval, dict):
        raise ValueError(f"{label}格式无效")
    identity = str(approval.get("reviewer", "")).strip()
    role = str(approval.get("role", "")).strip()
    note = str(approval.get("note", "")).strip()
    if not identity or identity.lower() in {"pending", "todo", "system", "auto"}:
        raise ValueError(f"{label}人不得为空、占位或机器身份")
    if not note:
        raise ValueError(f"{label}必须填写理由")
    try:
        reviewed_at = datetime.fromisoformat(str(approval.get("reviewed_at", "")))
    except ValueError as error:
        raise ValueError(f"{label}时间格式无效") from error
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError(f"{label}时间必须包含时区")
    return identity, role
