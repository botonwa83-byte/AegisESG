#!/usr/bin/env python3
"""Bind research-ranking artifacts into a reproducible, non-formal snapshot."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "output/research/2025"
AUDIT = ROOT / "output/audit"
OUTPUT = AUDIT / "research_snapshot_manifest_v1_2025.json"
FILES = {
    "ranking": RESEARCH / "ranking.json",
    "ranking_metadata": RESEARCH / "ranking_metadata.json",
    "ranking_sensitivity": RESEARCH / "ranking_sensitivity.json",
    "observations": RESEARCH / "full_auto_observations_v19.csv",
    "observation_summary": RESEARCH / "full_auto_observations_summary_v8.json",
    "gap_baseline": AUDIT / "data_gap_baseline_summary_v1_2025.json",
    "auto_review": AUDIT / "thin_basis_review_application_v1_2025.json",
    "stability_gate": AUDIT / "research_stability_gate_v1_2025.json",
    "stability_priority_queue": AUDIT / "research_stability_priority_queue_v1_2025.csv",
    "stability_priority_summary": AUDIT / "research_stability_priority_queue_v1_2025_summary.json",
    "stability_priority_packet": AUDIT / "research_stability_priority_packet_v1_2025.html",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in FILES.values() if not path.is_file()]
    artifacts = {key: {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
                 for key, path in FILES.items() if path.is_file()}
    ranking = json.loads(FILES["ranking"].read_text(encoding="utf-8")) if FILES["ranking"].is_file() else []
    review = json.loads(FILES["auto_review"].read_text(encoding="utf-8")) if FILES["auto_review"].is_file() else {}
    result = {
        "policy_version": "research-snapshot-manifest-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "report_year": 2025,
        "snapshot_type": "research_preview_only",
        "ranking_rows": len(ranking) if isinstance(ranking, list) else None,
        "artifacts": artifacts,
        "missing_artifacts": missing,
        "review_gate": {"status": review.get("status", "unknown"), "scoring_authorized": False},
        "formal_publishable": False,
        "reproducible": not missing,
        "write_to_formal_ranking": False,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "ranking_rows": result["ranking_rows"], "reproducible": result["reproducible"], "formal_publishable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
