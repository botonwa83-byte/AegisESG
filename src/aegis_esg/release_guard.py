from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


FORMAL_ALGORITHM_VERSION = "formal_rank_fixed_v1"
RELEASE_MANIFEST_VERSION = "release-authorization-v1"
REQUIRED_ROLES = {"methodology_owner", "data_reviewer"}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_release_authorization(
    manifest_path: str | Path, input_path: str | Path, methodology_path: str | Path,
    missing_strategy: str,
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
    if manifest.get("scope") != "official_release":
        raise ValueError("授权清单不得从研究或预览域提升为正式发布")
    approvals = manifest.get("approvals")
    if not isinstance(approvals, list):
        raise ValueError("正式发布授权清单缺少双人审批")
    identities = set()
    roles = set()
    for approval in approvals:
        identity = str(approval.get("reviewer", "")).strip()
        role = str(approval.get("role", "")).strip()
        note = str(approval.get("note", "")).strip()
        if not identity or identity.lower() in {"pending", "todo", "system", "auto"}:
            raise ValueError("正式发布审批人不得为空、占位或机器身份")
        if not note:
            raise ValueError("正式发布审批必须填写理由")
        try:
            reviewed_at = datetime.fromisoformat(str(approval.get("reviewed_at", "")))
        except ValueError as error:
            raise ValueError("正式发布审批时间格式无效") from error
        if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
            raise ValueError("正式发布审批时间必须包含时区")
        identities.add(identity)
        roles.add(role)
    if len(identities) < 2 or not REQUIRED_ROLES.issubset(roles):
        raise ValueError("正式发布需要不同人员完成方法论和数据双重审批")
    return {
        "manifest_version": RELEASE_MANIFEST_VERSION,
        "algorithm_version": FORMAL_ALGORITHM_VERSION,
        "manifest_sha256": sha256_file(manifest_path),
        "approval_count": len(approvals),
        "authorized": True,
    }


def prepare_release_authorization(
    input_path: str | Path, methodology_path: str | Path, missing_strategy: str,
) -> dict:
    return {
        "manifest_version": RELEASE_MANIFEST_VERSION,
        "algorithm_version": FORMAL_ALGORITHM_VERSION,
        "scope": "official_release",
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "methodology_path": str(methodology_path),
        "methodology_sha256": sha256_file(methodology_path),
        "missing_strategy_version": missing_strategy,
        "approvals": [
            {"reviewer": "", "role": "methodology_owner", "reviewed_at": "", "note": ""},
            {"reviewer": "", "role": "data_reviewer", "reviewed_at": "", "note": ""},
        ],
        "authorized": False,
        "notice": "未签名模板；系统不得填写审核人或提升为正式发布",
    }
