from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


VERSION = "thin-population-methodology-review-v1"
ALLOWED_ACTIONS = {
    "retain_threshold_with_thin_sample_warning",
    "commission_additional_data",
    "revise_indicator_definition",
    "revise_minimum_population",
}
PLACEHOLDER_REVIEWERS = {"", "todo", "tbd", "reviewer", "system", "machine", "自动", "待定"}


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_diagnostics(path: str | Path) -> list[dict]:
    # Extracted PDF text can contain NUL bytes. They are not evidence characters and must not
    # make the frozen diagnostic ledger unreadable.
    payload = Path(path).read_bytes().replace(b"\x00", b"").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(payload)))


def prepare_thin_population_methodology_review(
    quantitative_summary_path: str | Path, diagnostics_path: str | Path,
) -> tuple[list[dict], dict]:
    with Path(quantitative_summary_path).open(encoding="utf-8") as stream:
        summary = json.load(stream)
    diagnostics = _read_diagnostics(diagnostics_path)
    thin_codes = sorted(summary.get("below_minimum_population_indicator_codes", []))
    populations = summary.get("indicator_population", {})
    threshold = int(summary.get("minimum_population_threshold", 0))
    if not thin_codes or threshold <= 0:
        raise ValueError("定量摘要没有待裁决的薄样本指标")
    by_indicator: dict[str, list[dict]] = defaultdict(list)
    for row in diagnostics:
        by_indicator[row.get("indicator_code", "")].append(row)
    missing = [code for code in thin_codes if code not in by_indicator]
    if missing:
        raise ValueError("诊断文件未覆盖薄样本指标: " + ",".join(missing))
    summary_hash = _sha256(quantitative_summary_path)
    diagnostics_hash = _sha256(diagnostics_path)
    rows = []
    for code in thin_codes:
        indicator_rows = by_indicator[code]
        categories = Counter(row.get("diagnostic_category", "") for row in indicator_rows)
        population = int(populations.get(code, 0))
        review_id = hashlib.sha256(
            f"{VERSION}\x1f{code}\x1f{summary_hash}\x1f{diagnostics_hash}".encode("utf-8")
        ).hexdigest()
        rows.append({
            "review_id": review_id,
            "indicator_code": code,
            "current_population": population,
            "minimum_population_threshold": threshold,
            "population_deficit": max(0, threshold - population),
            "diagnosed_task_count": len(indicator_rows),
            "diagnostic_category_counts": json.dumps(dict(sorted(categories.items())), ensure_ascii=False),
            "quantitative_summary_sha256": summary_hash,
            "diagnostics_sha256": diagnostics_hash,
            "decision": "",
            "proposed_change": "",
            "reviewer": "",
            "reviewed_at": "",
            "rationale": "",
        })
    manifest = {
        "review_version": VERSION,
        "quantitative_summary_path": str(quantitative_summary_path),
        "quantitative_summary_sha256": summary_hash,
        "diagnostics_path": str(diagnostics_path),
        "diagnostics_sha256": diagnostics_hash,
        "minimum_population_threshold": threshold,
        "review_count": len(rows),
        "indicator_codes": thin_codes,
        "review_ids": sorted(row["review_id"] for row in rows),
        "allowed_decisions": sorted(ALLOWED_ACTIONS),
        "signed_count": 0,
        "methodology_change_authorized": False,
        "scoring_authorized": False,
        "applicable": False,
    }
    return rows, manifest


def evaluate_thin_population_methodology_review(
    decisions_path: str | Path, manifest_path: str | Path,
) -> dict:
    with Path(manifest_path).open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("review_version") != VERSION:
        raise ValueError("薄样本裁决清单版本无效")
    with Path(decisions_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected_ids = sorted(manifest.get("review_ids", []))
    actual_ids = [row.get("review_id", "") for row in rows]
    if len(actual_ids) != len(set(actual_ids)) or sorted(actual_ids) != expected_ids:
        raise ValueError("薄样本裁决行与冻结清单不一致")
    reviewers = set()
    decision_counts = Counter()
    changes_requested = []
    for number, row in enumerate(rows, 2):
        decision = row.get("decision", "").strip()
        if decision not in ALLOWED_ACTIONS:
            raise ValueError(f"薄样本裁决第{number}行决定无效")
        reviewer = row.get("reviewer", "").strip()
        if reviewer.lower() in PLACEHOLDER_REVIEWERS:
            raise ValueError(f"薄样本裁决第{number}行缺少真实审核人")
        reviewed_at = row.get("reviewed_at", "").strip()
        try:
            timestamp = datetime.fromisoformat(reviewed_at)
        except ValueError as exc:
            raise ValueError(f"薄样本裁决第{number}行时间格式无效") from exc
        if timestamp.tzinfo is None:
            raise ValueError(f"薄样本裁决第{number}行时间必须带时区")
        rationale = row.get("rationale", "").strip()
        if len(rationale) < 10:
            raise ValueError(f"薄样本裁决第{number}行理由不足")
        proposed_change = row.get("proposed_change", "").strip()
        if decision.startswith("revise_") and not proposed_change:
            raise ValueError(f"薄样本裁决第{number}行缺少拟议变更")
        reviewers.add(reviewer)
        decision_counts[decision] += 1
        if decision.startswith("revise_"):
            changes_requested.append(row["indicator_code"])
    return {
        "review_version": VERSION,
        "decision_input_sha256": _sha256(decisions_path),
        "manifest_sha256": _sha256(manifest_path),
        "review_count": len(rows),
        "signed_count": len(rows),
        "reviewer_count": len(reviewers),
        "decision_counts": dict(sorted(decision_counts.items())),
        "methodology_change_requested": bool(changes_requested),
        "change_requested_indicator_codes": sorted(changes_requested),
        "all_decisions_signed": True,
        # Evaluation records decisions only. A separate versioned methodology amendment and
        # release authorization are still required before scoring can change.
        "methodology_change_authorized": False,
        "scoring_authorized": False,
        "applicable": True,
    }


def write_methodology_review_packet(
    output_path: str | Path, manifest_path: str | Path, rows: list[dict], manifest: dict,
) -> None:
    output = Path(output_path); output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    target = Path(manifest_path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

