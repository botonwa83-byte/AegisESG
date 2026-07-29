from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .extraction import read_page_text_export
from .planning import read_document_records


@dataclass(frozen=True)
class AnnualESGEvidence:
    stock_code: str
    company_name: str
    source_url: str
    source_file: str
    source_page: int
    matched_term: str
    evidence_text: str
    review_status: str = "pending"


ESG_PATTERNS = (
    re.compile(r"environmental,? social and governance", re.I),
    re.compile(r"\bESG (?:report|section|disclosure|information)\b", re.I),
    re.compile(r"\bsustainability report\b", re.I),
    re.compile(r"環境、?社會及管治|环境、?社会及管治"),
)


def scan_annual_esg_disclosure(
    coverage_path: str | Path, document_index: str | Path, text_root: str | Path,
    max_per_company: int = 5,
) -> tuple[list[AnnualESGEvidence], dict]:
    if max_per_company < 1:
        raise ValueError("年报ESG证据上限必须大于0")
    with Path(coverage_path).open(encoding="utf-8-sig", newline="") as stream:
        coverage = list(csv.DictReader(stream))
    required = {"stock_code", "company_name", "next_action"}
    if not coverage or not required.issubset(coverage[0]):
        raise ValueError("文档覆盖审计字段不完整")
    targets = {
        row["stock_code"].strip().upper(): row["company_name"].strip()
        for row in coverage if row["next_action"].strip() == "scan_annual_for_esg"
    }
    annuals = {
        item.company_code: item for item in read_document_records(document_index)
        if item.document_type == "annual_report" and item.company_code in targets
    }
    text_root = Path(text_root)
    evidence = []
    missing_text = []
    for code in sorted(targets):
        record = annuals.get(code)
        if record is None:
            continue
        try:
            relative = Path(record.local_path).relative_to("data/raw")
        except ValueError as error:
            raise ValueError(f"年报路径不在data/raw下: {record.local_path}") from error
        text_path = (text_root / relative).with_suffix(".txt")
        if not text_path.exists():
            missing_text.append(str(text_path))
            continue
        found = 0
        for page in read_page_text_export(text_path):
            normalized = re.sub(r"\s+", " ", page.text).strip()
            match = next((pattern.search(normalized) for pattern in ESG_PATTERNS if pattern.search(normalized)), None)
            if match is None:
                continue
            start, end = max(0, match.start() - 180), min(len(normalized), match.end() + 360)
            evidence.append(AnnualESGEvidence(
                code, targets[code], record.source_url, record.local_path, page.page,
                match.group(0), normalized[start:end],
            ))
            found += 1
            if found >= max_per_company:
                break
    covered = {item.stock_code for item in evidence}
    summary = {
        "target_company_count": len(targets),
        "annual_document_count": len(annuals),
        "candidate_count": len(evidence),
        "candidate_company_count": len(covered),
        "codes_without_candidates": sorted(set(targets).difference(covered)),
        "missing_text_count": len(missing_text),
        "missing_text_files": missing_text,
        "applicable": False,
    }
    return evidence, summary


def write_annual_esg_evidence(
    output_path: str | Path, summary_path: str | Path,
    rows: list[AnnualESGEvidence], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(AnnualESGEvidence.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
