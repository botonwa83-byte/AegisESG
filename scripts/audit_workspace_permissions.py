#!/usr/bin/env python3
"""Audit root-owned workspace artifacts that can break LaunchAgent writers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "output/audit/workspace_permission_audit_v1.json"
TARGETS = (
    ROOT / "output/audit",
    ROOT / "output/sync",
    ROOT / "data/raw/ci_collection",
    ROOT / "data/text/ci_collection",
    ROOT / "var/local-data-collection",
)


def main() -> None:
    bad = []
    for root in TARGETS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_uid == 0:
                bad.append(str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path))
                if len(bad) >= 50:
                    break
        if len(bad) >= 50:
            break
    report = {
        "policy_version": "workspace-permission-audit-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "root_owned_count": len(bad),
        "root_owned_examples": bad[:20],
        "expected_uid": os.stat(ROOT).st_uid,
        "scoring_authorized": False,
        "notice": "若存在root属主文件，LaunchAgent(用户态)可能无法覆写；用chown修复，勿继续用root跑采集。",
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
