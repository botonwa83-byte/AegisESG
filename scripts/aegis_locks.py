#!/usr/bin/env python3
"""PID-aware directory locks for long-running collection/text/indicator jobs."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

PROCESS_HINTS = {
    "aegisesp-data-collection.lock": (
        "run_scheduled_collection.py",
        "run_local_data_scheduler.sh",
    ),
    "aegisesp-text-extraction.lock": (
        "run_ci_text_extraction.py",
        "extract_pdf_batch.swift",
    ),
    "aegisesp-indicator-extraction.lock": (
        "run_incremental_indicator_extraction.py",
        "extract-batch-text",
    ),
}


class LockStatus(NamedTuple):
    path: Path
    held: bool
    pid: Optional[int]
    alive: bool
    stale: bool
    reclaimable: bool
    reason: str


def lock_status(lock_dir: str | Path) -> LockStatus:
    path = Path(lock_dir)
    if not path.is_dir():
        return LockStatus(
            path=path, held=False, pid=None, alive=False, stale=False,
            reclaimable=False, reason="absent",
        )
    pid = _read_pid(path)
    if pid is not None:
        alive = _pid_alive(pid)
        if alive:
            return LockStatus(
                path=path, held=True, pid=pid, alive=True, stale=False,
                reclaimable=False, reason="pid_alive",
            )
        return LockStatus(
            path=path, held=True, pid=pid, alive=False, stale=True,
            reclaimable=True, reason="pid_dead",
        )
    # Legacy lock dirs without pid: infer from related process names.
    if _hint_process_alive(path.name):
        return LockStatus(
            path=path, held=True, pid=None, alive=True, stale=False,
            reclaimable=False, reason="legacy_process_alive",
        )
    return LockStatus(
        path=path, held=True, pid=None, alive=False, stale=True,
        reclaimable=True, reason="legacy_no_owner",
    )


def acquire_lock(lock_dir: str | Path, *, pid: int | None = None) -> bool:
    """Create lock dir with owner pid. Returns False if a live owner holds it."""
    path = Path(lock_dir)
    owner = pid if pid is not None else os.getpid()
    try:
        path.mkdir(exist_ok=False)
    except FileExistsError:
        status = lock_status(path)
        if not status.reclaimable:
            return False
        if not reclaim_lock(path):
            return False
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError:
            return False
    (path / "pid").write_text(str(owner) + "\n", encoding="utf-8")
    (path / "acquired_at_utc").write_text(
        datetime.now(timezone.utc).replace(microsecond=0).isoformat() + "\n",
        encoding="utf-8",
    )
    return True


def release_lock(lock_dir: str | Path) -> None:
    path = Path(lock_dir)
    if not path.is_dir():
        return
    for name in ("pid", "acquired_at_utc"):
        try:
            (path / name).unlink()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass


def reclaim_lock(lock_dir: str | Path, *, force: bool = False) -> bool:
    status = lock_status(lock_dir)
    if not status.held:
        return False
    if not force and not status.reclaimable:
        return False
    path = Path(lock_dir)
    for child in list(path.iterdir()):
        try:
            child.unlink()
        except OSError:
            pass
    try:
        path.rmdir()
        return True
    except OSError:
        return False


def audit_locks(lock_dirs: list[str | Path]) -> dict:
    rows = []
    for item in lock_dirs:
        status = lock_status(item)
        rows.append({
            "lock": str(status.path),
            "held": status.held,
            "pid": status.pid,
            "alive": status.alive,
            "stale": status.stale,
            "reclaimable": status.reclaimable,
            "reason": status.reason,
        })
    return {
        "policy_version": "aegis-lock-audit-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "locks": rows,
        "stale_count": sum(1 for row in rows if row["stale"]),
        "scoring_authorized": False,
    }


def _read_pid(lock_dir: Path) -> int | None:
    pid_path = lock_dir / "pid"
    if not pid_path.is_file():
        return None
    raw = pid_path.read_text(encoding="utf-8").strip()
    try:
        return int(raw)
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _hint_process_alive(lock_name: str) -> bool:
    for hint in PROCESS_HINTS.get(lock_name, ()):
        completed = subprocess.run(
            ["pgrep", "-f", hint],
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return True
    return False


if __name__ == "__main__":
    default_locks = [
        "/tmp/aegisesp-data-collection.lock",
        "/tmp/aegisesp-text-extraction.lock",
        "/tmp/aegisesp-indicator-extraction.lock",
    ]
    print(json.dumps(audit_locks(default_locks), ensure_ascii=False, indent=2))
