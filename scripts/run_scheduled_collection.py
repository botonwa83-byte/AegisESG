#!/usr/bin/env python3
"""Run a resumable collection job for CI and emit a compact sync manifest."""
from __future__ import annotations

import json
import os
import csv
from datetime import datetime, timezone
from pathlib import Path

from aegis_esg.collector import collect_batch, dedupe_document_records, write_document_index

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(os.getenv("AEGIS_COLLECTION_MANIFEST", ROOT / "output/audit/scheduled_collection_manifest_v1_2025.csv"))
OUTPUT_ROOT = Path(os.getenv("AEGIS_COLLECTION_OUTPUT_ROOT", ROOT / "data/raw/ci_collection"))
INDEX = Path(os.getenv("AEGIS_COLLECTION_INDEX", ROOT / "output/sync/official_document_index.csv"))
FAILURES = Path(os.getenv("AEGIS_COLLECTION_FAILURES", ROOT / "output/sync/official_collection_failures.csv"))
SUMMARY = ROOT / "output/sync/collection_run_summary.json"


def main() -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.is_file():
        raise SystemExit(f"collection manifest not found: {MANIFEST}")
    _normalize_index_paths()
    _compact_index()
    manifest_urls = set()
    with MANIFEST.open(encoding="utf-8-sig", newline="") as stream:
        manifest_urls = {row.get("source_url", "").strip() for row in csv.DictReader(stream) if row.get("source_url", "").strip()}
    indexed_urls = set()
    if INDEX.is_file():
        with INDEX.open(encoding="utf-8-sig", newline="") as stream:
            indexed_urls = {row.get("source_url", "").strip() for row in csv.DictReader(stream) if row.get("source_url", "").strip()}
    new_urls = sorted(manifest_urls - indexed_urls)
    if not new_urls:
        result = {"policy_version": "scheduled-collection-v1", "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                  "manifest": str(MANIFEST.relative_to(ROOT)) if MANIFEST.is_relative_to(ROOT) else str(MANIFEST),
                  "manifest_rows": len(manifest_urls), "new_url_count": 0, "record_count": 0, "failure_count": 0,
                  "download_started": False, "reason": "no_new_source_urls", "scoring_authorized": False, "formal_publishable": False}
        SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return
    records, failures = collect_batch(
        MANIFEST, OUTPUT_ROOT, INDEX, FAILURES,
        delay_seconds=1.0, workers=2, reuse_existing=True,
        preserve_index=True,
        max_minutes=_time_budget_minutes(),
        document_priority=os.getenv("AEGIS_COLLECTION_DOC_PRIORITY", "esg"),
    )
    result = {
        "policy_version": "scheduled-collection-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest": str(MANIFEST.relative_to(ROOT)) if MANIFEST.is_relative_to(ROOT) else str(MANIFEST),
        "record_count": len(records), "failure_count": len(failures),
        "manifest_rows": len(manifest_urls), "new_url_count": len(new_urls),
        "index": str(INDEX.relative_to(ROOT)) if INDEX.is_relative_to(ROOT) else str(INDEX),
        "output_root": str(OUTPUT_ROOT.relative_to(ROOT)) if OUTPUT_ROOT.is_relative_to(ROOT) else str(OUTPUT_ROOT),
        "download_started": bool(failures) or any(record.source_url in set(new_urls) for record in records),
        "scoring_authorized": False,
        "formal_publishable": False,
        "time_budget_minutes": _time_budget_minutes(),
        "document_priority": os.getenv("AEGIS_COLLECTION_DOC_PRIORITY", "esg"),
        "stopped_on_budget": bool(
            _time_budget_minutes() is not None
            and len(new_urls) > 0
            and sum(1 for record in records if record.source_url in set(new_urls)) + len(failures) < len(new_urls)
        ),
    }
    SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


def _time_budget_minutes() -> float | None:
    """Soft wall-clock budget for a single collection run (env-overridable)."""
    raw = os.getenv("AEGIS_COLLECTION_TIME_BUDGET_MIN", "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _compact_index() -> None:
    """Drop invalid-year and identity-duplicate rows before launching downloads."""
    if not INDEX.is_file():
        return
    from aegis_esg.collector import _read_document_index
    records = list(_read_document_index(INDEX).values())
    compact = dedupe_document_records(records)
    if len(compact) != len(records):
        write_document_index(INDEX, compact)


def _normalize_index_paths() -> None:
    """Keep artifact indexes portable between GitHub runners and local Macs."""
    if not INDEX.is_file():
        return
    with INDEX.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return
    fields = list(rows[0])
    for row in rows:
        path = Path(row.get("local_path", ""))
        try:
            row["local_path"] = str(path.relative_to(ROOT)) if path.is_absolute() else str(path)
        except ValueError:
            row["local_path"] = str(path)
    with INDEX.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


if __name__ == "__main__":
    main()
