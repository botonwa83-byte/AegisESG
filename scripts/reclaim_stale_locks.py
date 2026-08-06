#!/usr/bin/env python3
"""Audit and optionally reclaim stale AegisESP job locks."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from aegis_locks import audit_locks, reclaim_lock  # noqa: E402

DEFAULT = [
    "/tmp/aegisesp-data-collection.lock",
    "/tmp/aegisesp-text-extraction.lock",
    "/tmp/aegisesp-indicator-extraction.lock",
]
SUMMARY = ROOT / "output/audit/stale_lock_audit_v1.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reclaim-stale", action="store_true", help="remove reclaimable stale locks")
    parser.add_argument("--lock", action="append", default=[], help="extra lock path")
    args = parser.parse_args()
    locks = DEFAULT + args.lock
    report = audit_locks(locks)
    reclaimed = []
    if args.reclaim_stale:
        for row in report["locks"]:
            if row["reclaimable"]:
                if reclaim_lock(row["lock"]):
                    reclaimed.append(row["lock"])
        report = audit_locks(locks)
        report["reclaimed"] = reclaimed
    report["scoring_authorized"] = False
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
