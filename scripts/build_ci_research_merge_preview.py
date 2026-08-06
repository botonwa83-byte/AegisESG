#!/usr/bin/env python3
"""Preview which CI downloads would add coverage vs the research document index.

Never overwrites the research index. Output is audit-only and not scoring-authorized.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "data/raw/all_markets_document_index.csv"
CI = ROOT / "output/sync/official_document_index.csv"
OUTPUT = ROOT / "output/audit/ci_research_merge_preview_v1_2025.csv"
SUMMARY = ROOT / "output/audit/ci_research_merge_preview_v1_2025.json"
FIELDS = (
    "company_code", "company_name", "report_year", "document_type",
    "action", "research_status", "ci_source_url", "ci_local_path", "ci_sha256",
)


def _load(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    if not path.is_file():
        return {}
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (
                (row.get("company_code") or "").strip(),
                str(row.get("report_year") or "").strip(),
                (row.get("document_type") or "").strip(),
            )
            if not key[0] or not key[2]:
                continue
            try:
                year = int(key[1])
            except ValueError:
                continue
            if year < 1990 or year > 2100:
                continue
            rows[key] = row
    return rows


def build_merge_preview(
    research: dict[tuple[str, str, str], dict[str, str]],
    ci: dict[tuple[str, str, str], dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Compare CI vs research index; never mutates either side."""
    preview: list[dict[str, str]] = []
    for key, row in sorted(ci.items()):
        code, year, kind = key
        existing = research.get(key)
        if existing is None:
            action = "would_add"
            research_status = "missing"
        elif (existing.get("sha256") or "") == (row.get("sha256") or "") and existing.get("sha256"):
            action = "already_present_same_hash"
            research_status = "present"
        else:
            action = "conflict_or_different_hash"
            research_status = "present_different"
        if action == "already_present_same_hash":
            continue
        preview.append({
            "company_code": code,
            "company_name": row.get("company_name", ""),
            "report_year": year,
            "document_type": kind,
            "action": action,
            "research_status": research_status,
            "ci_source_url": row.get("source_url", ""),
            "ci_local_path": row.get("local_path", ""),
            "ci_sha256": row.get("sha256", ""),
        })
    by_action: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    for row in preview:
        by_action[row["action"]] += 1
        if row["action"] == "would_add":
            by_type[row["document_type"]] += 1
    summary: dict[str, object] = {
        "policy_version": "ci-research-merge-preview-v1",
        "preview_rows": len(preview),
        "would_add": by_action.get("would_add", 0),
        "would_add_by_type": dict(by_type),
        "conflict_or_different_hash": by_action.get("conflict_or_different_hash", 0),
        "research_index_mutated": False,
        "scoring_authorized": False,
        "formal_publishable": False,
    }
    return preview, summary


def main() -> None:
    research = _load(RESEARCH)
    ci = _load(CI)
    preview, summary = build_merge_preview(research, ci)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(preview)
    summary.update({
        "research_index": str(RESEARCH.relative_to(ROOT)),
        "ci_index": str(CI.relative_to(ROOT)),
        "output": str(OUTPUT.relative_to(ROOT)),
        "notice": "仅预览CI相对研究索引的增量；不合并、不覆盖、不授权评分。",
    })
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
