#!/usr/bin/env python3
"""Bind the thin-population review inputs into an auditable, non-authorizing manifest."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "output/audit/thin_basis_review_template_v1_2025.csv"
VALIDATION = ROOT / "output/audit/thin_basis_review_template_validation_v1_2025.json"
CONSISTENCY = ROOT / "output/audit/thin_basis_consistency_audit_v1_2025.csv"
DOCUMENT_INDEX = ROOT / "data/raw/all_markets_document_index.csv"
OUTPUT = ROOT / "output/audit/thin_basis_review_manifest_v1_2025.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    manifest = {
        "policy_version": "thin-basis-review-manifest-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": {"report_year": 2025, "purpose": "薄样本证据口径复核，不产生正式评分"},
        "inputs": {
            "review_template": {"path": str(TEMPLATE.relative_to(ROOT)), "sha256": sha256(TEMPLATE)},
            "template_validation": {"path": str(VALIDATION.relative_to(ROOT)), "sha256": sha256(VALIDATION)},
            "consistency_audit": {"path": str(CONSISTENCY.relative_to(ROOT)), "sha256": sha256(CONSISTENCY)},
            "document_index": {"path": str(DOCUMENT_INDEX.relative_to(ROOT)), "sha256": sha256(DOCUMENT_INDEX)},
        },
        "validation": validation,
        "review_status": {
            "row_count": validation.get("row_count", 0),
            "completed_signed_rows": validation.get("partially_filled_rows", 0),
            "status": "blocked_external_review",
            "scoring_authorized": False,
            "required_external_action": "由具备权限的审核人补全每条证据的值、单位、分母、边界、审核人、时间和理由，并复核未定位页码项",
        },
        "integrity": {
            "source_chain_bound": True,
            "hash_algorithm": "SHA-256",
            "formal_ranking_write": False,
            "publishable": False,
        },
    }
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "scoring_authorized": False, "status": "blocked_external_review"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
