#!/usr/bin/env python3
"""Merge CI would-add documents into the research document index.

Only adds identities missing from research. Never overwrites existing research
rows (conflicts stay as-is). Does not authorize formal scoring.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "data/raw/all_markets_document_index.csv"
CI = ROOT / "output/sync/official_document_index.csv"
PREVIEW = ROOT / "output/audit/ci_research_merge_preview_v1_2025.csv"
SUMMARY = ROOT / "output/audit/ci_research_merge_apply_v1_2025.json"
FIELDS = (
    "company_code", "company_name", "report_year", "document_type",
    "source_url", "retrieval_url", "local_path", "sha256", "size",
)


def _rel(path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(ROOT))
        except ValueError:
            return str(p)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--copy-files", action="store_true", help="Copy CI PDFs into data/raw/all_markets/... tree")
    parser.add_argument("--types", default="esg_report,annual_report")
    args = parser.parse_args()
    allowed = {item.strip() for item in args.types.split(",") if item.strip()}

    research_rows = list(csv.DictReader(RESEARCH.open(encoding="utf-8-sig")))
    research_keys = {
        (
            (row.get("company_code") or "").strip(),
            str(row.get("report_year") or "").strip(),
            (row.get("document_type") or "").strip(),
        )
        for row in research_rows
    }
    ci_by_key = {}
    for row in csv.DictReader(CI.open(encoding="utf-8-sig")):
        key = (
            (row.get("company_code") or "").strip(),
            str(row.get("report_year") or "").strip(),
            (row.get("document_type") or "").strip(),
        )
        ci_by_key[key] = row

    added = []
    for key, row in sorted(ci_by_key.items()):
        code, year, kind = key
        if kind not in allowed:
            continue
        if key in research_keys:
            continue
        local = _rel(row.get("local_path") or "")
        src = ROOT / local if not Path(local).is_absolute() else Path(local)
        if not src.is_file():
            # try absolute path from CI as-is
            alt = Path(row.get("local_path") or "")
            if alt.is_file():
                src = alt
                local = _rel(str(alt))
            else:
                continue
        if args.copy_files:
            dest = ROOT / "data/raw/all_markets" / code / year / f"{kind}.pdf"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file():
                shutil.copy2(src, dest)
            local = str(dest.relative_to(ROOT))
        new_row = {
            "company_code": code,
            "company_name": row.get("company_name") or "",
            "report_year": year,
            "document_type": kind,
            "source_url": row.get("source_url") or "",
            "retrieval_url": row.get("retrieval_url") or row.get("source_url") or "",
            "local_path": local,
            "sha256": row.get("sha256") or "",
            "size": row.get("size") or "",
        }
        research_rows.append(new_row)
        research_keys.add(key)
        added.append(new_row)

    research_rows.sort(key=lambda r: (r["company_code"], r["report_year"], r["document_type"]))
    with RESEARCH.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(research_rows)

    summary = {
        "policy_version": "ci-research-merge-apply-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "added_rows": len(added),
        "added_by_type": {
            kind: sum(1 for row in added if row["document_type"] == kind)
            for kind in sorted({row["document_type"] for row in added})
        },
        "research_index_rows": len(research_rows),
        "copy_files": bool(args.copy_files),
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "仅并入CI相对研究索引缺失的身份行；冲突行未覆盖；不授权正式评分。",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
