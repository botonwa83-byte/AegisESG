#!/usr/bin/env python3
"""Extract indicator candidates from the locally synchronized CI document index."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "output/sync/official_document_index.csv"
TEXT_ROOT = ROOT / "data/text/ci_collection"
OUTPUT = ROOT / "output/audit/ci_incremental_candidates_v1_2025.csv"
COVERAGE = ROOT / "output/audit/ci_incremental_candidate_coverage_v1_2025.json"
REVIEW = ROOT / "output/audit/ci_incremental_review_summary_v1_2025.csv"


def main() -> None:
    if not INDEX.is_file() or not TEXT_ROOT.is_dir():
        print(json.dumps({"status": "waiting_for_text_exports", "candidate_count": 0}, ensure_ascii=False))
        return
    command = [sys.executable, "-m", "aegis_esg.cli", "extract-batch-text", str(INDEX), str(TEXT_ROOT),
               "--report-year", "2025", "--output", str(OUTPUT), "--coverage", str(COVERAGE), "--review-summary", str(REVIEW)]
    env = dict(os.environ); env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    if completed.returncode:
        raise SystemExit(completed.stderr or completed.stdout)
    count = 0
    if OUTPUT.is_file():
        count = max(0, sum(1 for _ in OUTPUT.open(encoding="utf-8-sig")) - 1)
    print(json.dumps({"status": "extracted", "candidate_count": count, "output": str(OUTPUT.relative_to(ROOT)), "scoring_authorized": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
