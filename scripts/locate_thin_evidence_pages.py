#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_evidence_provenance_audit_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_evidence_page_located_v1_2025.csv"
SUMMARY = ROOT / "output/audit/thin_evidence_page_located_summary_v1_2025.json"


def locate(text_path: Path, excerpt: str) -> str:
    if not text_path.is_file():
        return ""
    text = text_path.read_text(encoding="utf-8", errors="replace")
    terms = [term for term in re.split(r"\s+", excerpt) if len(term) >= 5][:8]
    position = -1
    for term in terms:
        position = text.lower().find(term.lower())
        if position >= 0:
            break
    if position < 0:
        return ""
    before = text[:position]
    pages = re.findall(r"(?:===\s*PAGE\s*|第\s*)(\d+)(?:\s*===|\s*页)", before, re.I)
    return pages[-1] if pages else ""


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        raw = (row.get("source_file") or "").split("|")[0]
        row["located_page"] = locate(Path(raw), row.get("evidence_text", ""))
        row["page_location_status"] = "page_located" if row["located_page"] else "page_not_located"
        row["provenance_status"] = "ready_for_basis_review" if row["located_page"] and row.get("source_hash_ok") == "True" else "provenance_incomplete"
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    summary = {"policy_version": "thin-evidence-page-location-v1", "task_count": len(rows),
               "page_located": sum(r["page_location_status"] == "page_located" for r in rows),
               "page_not_located": sum(r["page_location_status"] == "page_not_located" for r in rows),
               "ready_for_basis_review": sum(r["provenance_status"] == "ready_for_basis_review" for r in rows),
               "scoring_authorized": False}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
