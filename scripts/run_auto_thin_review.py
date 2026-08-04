#!/usr/bin/env python3
"""Run the read-only thin-population review pipeline in a deterministic order."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = (
    "validate_thin_basis_review_template.py",
    "apply_thin_basis_review.py",
    "build_thin_basis_review_manifest.py",
    "build_thin_basis_review_status.py",
)


def main() -> None:
    results = []
    for name in STEPS:
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / name)], cwd=ROOT,
                                   text=True, capture_output=True, check=True)
        results.append({"script": name, "output": completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""})
    application = json.loads((ROOT / "output/audit/thin_basis_review_application_v1_2025.json").read_text(encoding="utf-8"))
    summary = {"policy_version": "auto-thin-review-runner-v1", "steps": results,
               "status": application["status"], "scoring_authorized": False,
               "candidate_observations_written": False}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
