#!/usr/bin/env python3
"""Refresh coverage/retry/merge previews without holding the collection lock.

Safe to run while a long download or text extraction is in progress.
Never starts downloads and never authorizes scoring.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "output/audit/live_collection_status_v1.json"
PDF_ROOT = ROOT / "data/raw/ci_collection"
TEXT_ROOT = ROOT / "data/text/ci_collection"
COLLECTION_LOCK = Path("/tmp/aegisesp-data-collection.lock")
TEXT_LOCK = Path("/tmp/aegisesp-text-extraction.lock")


def _count(pattern: str, root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob(pattern))


def _run(script: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    payload = {}
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            payload = {"raw_tail": completed.stdout.strip()[-300:]}
    return {
        "script": script,
        "ok": completed.returncode == 0,
        "payload": payload,
        "stderr_tail": (completed.stderr or "")[-300:],
    }


def main() -> None:
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    steps = [
        _run("reclaim_stale_locks.py"),
        _run("audit_workspace_permissions.py"),
        _run("classify_collection_failures.py"),
        _run("build_collection_retry_manifest.py"),
        _run("build_collection_coverage_report.py"),
        _run("build_ci_research_merge_preview.py"),
        _run("build_ci_incremental_coverage_packet.py"),
        _run("build_ci_thin_text_packet.py"),
        _run("build_scan_esg_annual_fallback_packet.py"),
        _run("build_remaining_identity_gaps.py"),
    ]
    pdf_count = _count("*.pdf", PDF_ROOT)
    text_count = _count("*.txt", TEXT_ROOT)
    result = {
        "policy_version": "live-collection-status-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "collection_lock_held": COLLECTION_LOCK.is_dir(),
        "text_lock_held": TEXT_LOCK.is_dir(),
        "pdf_count": pdf_count,
        "text_count": text_count,
        "text_pending_estimate": max(0, pdf_count - text_count),
        "steps": [{"script": s["script"], "ok": s["ok"]} for s in steps],
        "coverage": next((s["payload"] for s in steps if s["script"].startswith("build_collection_coverage")), {}),
        "merge_preview": next((s["payload"] for s in steps if "merge_preview" in s["script"]), {}),
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "长下载占锁时仍可刷新覆盖/重试/合并预览；不启动下载、不授权评分。",
    }
    SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if not all(step["ok"] for step in steps):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
