#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_evidence_preview_v1_2025.csv"
INDEX = ROOT / "data/raw/all_markets_document_index.csv"
OUTPUT = ROOT / "output/audit/thin_evidence_provenance_audit_v1_2025.csv"
SUMMARY = ROOT / "output/audit/thin_evidence_provenance_audit_summary_v1_2025.json"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with INDEX.open(encoding="utf-8-sig", newline="") as stream:
        index = {(r["company_code"], r["local_path"]): r for r in csv.DictReader(stream)}
    audited = []
    for row in rows:
        paths = [p for p in row.get("source_file", "").split("|") if p]
        checks = []
        for raw in paths:
            path = Path(raw)
            # Diagnostic text paths map back to the downloaded PDF path used by the document index.
            pdf_raw = raw.replace("data/text/", "data/raw/").replace(".txt", ".pdf")
            path = Path(pdf_raw)
            doc = index.get((row["company_code"], pdf_raw))
            exists = path.is_file()
            hash_ok = bool(doc and exists and hashlib.sha256(path.read_bytes()).hexdigest() == doc.get("sha256"))
            checks.append({"path": raw, "exists": exists, "hash_ok": hash_ok})
        page_ok = bool(row.get("source_pages", "").strip())
        text_ok = bool(row.get("evidence_text", "").strip())
        provenance_ok = bool(checks) and all(item["exists"] and item["hash_ok"] for item in checks) and page_ok and text_ok
        audited.append({**row, "source_file_count": len(checks), "source_exists": all(item["exists"] for item in checks) if checks else False,
                        "source_hash_ok": all(item["hash_ok"] for item in checks) if checks else False,
                        "page_present": page_ok, "evidence_present": text_ok,
                        "provenance_status": "ready_for_basis_review" if provenance_ok else "provenance_incomplete"})
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audited[0])); writer.writeheader(); writer.writerows(audited)
    summary = {"policy_version": "thin-evidence-provenance-audit-v1", "task_count": len(audited),
               "ready_for_basis_review": sum(r["provenance_status"] == "ready_for_basis_review" for r in audited),
               "provenance_incomplete": sum(r["provenance_status"] == "provenance_incomplete" for r in audited),
               "scoring_authorized": False}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
