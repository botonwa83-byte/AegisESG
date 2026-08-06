#!/usr/bin/env python3
"""Extract text from CI-collected PDFs using a lock separate from downloads."""
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

PDF_ROOT = ROOT / "data/raw/ci_collection"
TEXT_ROOT = ROOT / "data/text/ci_collection"
SUMMARY = ROOT / "output/audit/ci_text_extraction_summary_v1.json"
LOCK = Path(os.getenv("AEGIS_TEXT_EXTRACTION_LOCK", "/tmp/aegisesp-text-extraction.lock"))
SWIFT = ROOT / "scripts/extract_pdf_batch.swift"
HEARTBEAT_EVERY = int(os.getenv("AEGIS_TEXT_HEARTBEAT_EVERY", "10"))


def _count_txt() -> int:
    return sum(1 for _ in TEXT_ROOT.rglob("*.txt")) if TEXT_ROOT.is_dir() else 0


def _write_summary(payload: dict) -> None:
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    TEXT_ROOT.mkdir(parents=True, exist_ok=True)
    if not PDF_ROOT.is_dir():
        result = {
            "policy_version": "ci-text-extraction-v1",
            "status": "waiting_for_pdfs",
            "pdf_count": 0,
            "text_count": 0,
            "scoring_authorized": False,
        }
        _write_summary(result)
        print(json.dumps(result, ensure_ascii=False))
        return

    if not acquire_lock(LOCK):
        result = {
            "policy_version": "ci-text-extraction-v1",
            "status": "previous_extraction_still_running",
            "text_count_current": _count_txt(),
            "scoring_authorized": False,
            "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        _write_summary(result)
        print(json.dumps(result, ensure_ascii=False))
        return

    try:
        pdf_count = sum(1 for _ in PDF_ROOT.rglob("*.pdf"))
        before = _count_txt()
        if not SWIFT.is_file():
            raise SystemExit(f"missing extractor: {SWIFT}")
        if subprocess.run(["which", "swift"], capture_output=True).returncode != 0:
            result = {
                "policy_version": "ci-text-extraction-v1",
                "status": "swift_unavailable",
                "pdf_count": pdf_count,
                "text_count": before,
                "scoring_authorized": False,
            }
            _write_summary(result)
            print(json.dumps(result, ensure_ascii=False))
            return
        running = {
            "policy_version": "ci-text-extraction-v1",
            "status": "running",
            "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "pdf_count": pdf_count,
            "text_count_before": before,
            "text_count_current": before,
            "heartbeat_events": 0,
            "scoring_authorized": False,
            "notice": "可与定时下载并行；已存在的 txt 会跳过；进度会写入 summary。",
        }
        _write_summary(running)
        print(json.dumps(running, ensure_ascii=False), flush=True)

        proc = subprocess.Popen(
            ["swift", str(SWIFT), str(PDF_ROOT), str(TEXT_ROOT)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdout is not None
        lines: list[str] = []
        ok_events = 0
        for line in proc.stdout:
            lines.append(line.rstrip())
            if line.startswith("ok ") or line.startswith("failed ") or line.startswith("completed "):
                ok_events += 1
            if ok_events and ok_events % HEARTBEAT_EVERY == 0:
                current = _count_txt()
                running.update({
                    "text_count_current": current,
                    "heartbeat_events": running.get("heartbeat_events", 0) + 1,
                    "last_heartbeat_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "last_extractor_line": lines[-1][:240],
                })
                _write_summary(running)
        returncode = proc.wait()
        repair = {"repaired_count": 0}
        if returncode in {0, 2}:
            repair_proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts/repair_truncated_ci_text_exports.py")],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            if repair_proc.stdout.strip():
                try:
                    repair = json.loads(repair_proc.stdout.strip().splitlines()[-1])
                except json.JSONDecodeError:
                    repair = {"raw_tail": repair_proc.stdout.strip()[-200:]}
        after = _count_txt()
        status = "extracted" if returncode in {0, 2} else "extractor_failed"
        result = {
            "policy_version": "ci-text-extraction-v2",
            "status": status,
            "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "pdf_count": pdf_count,
            "text_count_before": before,
            "text_count_current": after,
            "text_count_after": after,
            "text_added": max(0, after - before),
            "truncated_repaired": repair.get("repaired_count", 0),
            "extractor_exit_code": returncode,
            "extractor_tail": "\n".join(lines[-20:])[-500:],
            "scoring_authorized": False,
            "notice": "可与定时下载并行；已存在的 txt 会跳过；截断导出会强制复抽；失败项下次重试。",
        }
        _write_summary(result)
        print(json.dumps(result, ensure_ascii=False))
        if returncode not in {0, 2}:
            raise SystemExit(result["extractor_tail"] or "text extraction failed")
    finally:
        release_lock(LOCK)


if __name__ == "__main__":
    main()
