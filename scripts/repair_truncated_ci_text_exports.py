#!/usr/bin/env python3
"""Force re-extract CI text exports that look truncated (few page markers, large PDF).

Does not enable OCR and never authorizes scoring. Safe to run after normal extraction.
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "output/sync/official_document_index.csv"
PDF_ROOT = ROOT / "data/raw/ci_collection"
TEXT_ROOT = ROOT / "data/text/ci_collection"
SWIFT = ROOT / "scripts/extract_pdf_batch.swift"
SUMMARY = ROOT / "output/audit/ci_truncated_text_repair_v1_2025.json"
MAX_PAGE_MARKERS = 2
MIN_PDF_BYTES = 1_000_000
MAX_NON_WS = 2000


def _stats(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    text = path.read_text(encoding="utf-8", errors="replace")
    markers = text.count("=== PAGE ")
    prose = "\n".join(line for line in text.splitlines() if not line.startswith("=== PAGE "))
    non_ws = sum(1 for ch in prose if not ch.isspace())
    return markers, non_ws


def _is_truncated(pdf: Path, txt: Path) -> bool:
    if not pdf.is_file():
        return False
    if pdf.stat().st_size < MIN_PDF_BYTES:
        return False
    markers, non_ws = _stats(txt)
    if not txt.is_file():
        return True
    return markers <= MAX_PAGE_MARKERS and non_ws < MAX_NON_WS


def main() -> None:
    targets: list[dict[str, object]] = []
    if INDEX.is_file():
        rows = list(csv.DictReader(INDEX.open(encoding="utf-8-sig")))
    else:
        rows = []
    for row in rows:
        year = str(row.get("report_year") or "")
        if year != "2025":
            continue
        code = row["company_code"]
        local = Path(row["local_path"])
        pdf = local if local.is_file() else ROOT / local
        if not pdf.is_file():
            pdf = PDF_ROOT / code / year / local.name
        txt = TEXT_ROOT / code / year / f"{pdf.stem}.txt"
        if not _is_truncated(pdf, txt):
            continue
        markers, non_ws = _stats(txt)
        try:
            pdf_rel = str(pdf.relative_to(ROOT))
        except ValueError:
            pdf_rel = str(pdf)
        targets.append({
            "company_code": code,
            "document_type": row.get("document_type", ""),
            "pdf": pdf_rel,
            "txt": str(txt.relative_to(ROOT)),
            "pdf_bytes": pdf.stat().st_size,
            "page_markers_before": markers,
            "non_ws_before": non_ws,
        })

    repaired = []
    if targets and SWIFT.is_file() and shutil.which("swift"):
        with tempfile.TemporaryDirectory(prefix="aegis_trunc_repair_") as tmp:
            stage_in = Path(tmp) / "in"
            stage_out = Path(tmp) / "out"
            for item in targets:
                code = str(item["company_code"])
                year = "2025"
                src = ROOT / str(item["pdf"]) if not Path(str(item["pdf"])).is_absolute() else Path(str(item["pdf"]))
                dest = stage_in / code / year / src.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            completed = subprocess.run(
                ["swift", str(SWIFT), str(stage_in), str(stage_out), "--force"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            for item in targets:
                code = str(item["company_code"])
                src_txt = stage_out / code / "2025" / Path(str(item["txt"])).name
                dst_txt = ROOT / str(item["txt"])
                if not src_txt.is_file():
                    item["status"] = "extract_missing_output"
                    item["extractor_tail"] = (completed.stdout or "")[-240:]
                    continue
                markers, non_ws = _stats(src_txt)
                item["page_markers_after"] = markers
                item["non_ws_after"] = non_ws
                if non_ws > item["non_ws_before"] and markers > MAX_PAGE_MARKERS:
                    dst_txt.parent.mkdir(parents=True, exist_ok=True)
                    dst_txt.write_text(src_txt.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                    item["status"] = "repaired"
                    repaired.append(item)
                else:
                    item["status"] = "still_thin_after_reextract"

    summary = {
        "policy_version": "ci-truncated-text-repair-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "candidate_truncated_rows": len(targets),
        "repaired_count": len(repaired),
        "rows": targets,
        "scoring_authorized": False,
        "formal_publishable": False,
        "ocr_authorized": False,
        "notice": "仅修复页标记过少的截断文本导出；扫描件仍保持薄文本并由分诊包观测。",
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
