#!/usr/bin/env python3
"""Extract indicator candidates from the locally synchronized CI document index."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from aegis_locks import acquire_lock, release_lock  # noqa: E402

INDEX = ROOT / "output/sync/official_document_index.csv"
TEXT_ROOT = ROOT / "data/text/ci_collection"
OUTPUT = ROOT / "output/audit/ci_incremental_candidates_v1_2025.csv"
COVERAGE = ROOT / "output/audit/ci_incremental_candidate_coverage_v1_2025.json"
REVIEW = ROOT / "output/audit/ci_incremental_review_summary_v1_2025.csv"
SUMMARY = ROOT / "output/audit/ci_incremental_extraction_summary_v1.json"
LOCK = Path(os.getenv("AEGIS_INDICATOR_EXTRACTION_LOCK", "/tmp/aegisesp-indicator-extraction.lock"))
MIN_TEXT = int(os.getenv("AEGIS_INDICATOR_MIN_TEXT", "20"))


def main() -> None:
    TEXT_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text_count = sum(1 for _ in TEXT_ROOT.rglob("*.txt")) if TEXT_ROOT.is_dir() else 0
    if not INDEX.is_file() or text_count < MIN_TEXT:
        result = {
            "status": "waiting_for_text_exports",
            "candidate_count": 0,
            "text_count": text_count,
            "min_text": MIN_TEXT,
            "scoring_authorized": False,
        }
        SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return

    if not acquire_lock(LOCK):
        result = {
            "status": "previous_indicator_extraction_still_running",
            "text_count": text_count,
            "scoring_authorized": False,
            "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return

    try:
        command = [
            sys.executable, "-m", "aegis_esg.cli", "extract-batch-text",
            str(INDEX), str(TEXT_ROOT),
            "--report-year", "2025",
            "--output", str(OUTPUT),
            "--coverage", str(COVERAGE),
            "--review-summary", str(REVIEW),
        ]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        if completed.returncode:
            raise SystemExit(completed.stderr or completed.stdout)
        count = 0
        if OUTPUT.is_file():
            count = max(0, sum(1 for _ in OUTPUT.open(encoding="utf-8-sig")) - 1)
        result = {
            "status": "extracted",
            "candidate_count": count,
            "text_count": text_count,
            "output": str(OUTPUT.relative_to(ROOT)),
            "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "scoring_authorized": False,
            "notice": "可在文本抽取未全部完成时对已有 txt 跑增量候选；结果待审核。",
        }
        SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    finally:
        release_lock(LOCK)


if __name__ == "__main__":
    main()
