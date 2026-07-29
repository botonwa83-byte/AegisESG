from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .extraction import read_page_text_export


@dataclass(frozen=True)
class ContinuityEvidenceCandidate:
    company_code: str
    company_name: str
    evidence_category: str
    document_type: str
    report_year: int
    source_url: str
    source_file: str
    source_page: int
    evidence_text: str
    confidence: float
    review_status: str = "pending"


PATTERNS = {
    "issuer_history": (
        re.compile(r"\b(?:the company\s+)?was formerly known as\b", re.I),
        re.compile(r"\b(?:change|changed) (?:of |its )?(?:company )?name\b", re.I),
        re.compile(r"\bhistory and development\b|\bcorporate history\b", re.I),
    ),
    "principal_business": (
        re.compile(r"\bprincipal activities\b", re.I),
        re.compile(r"\bprincipal business(?:es)?\b", re.I),
        re.compile(r"\bprincipally engaged in\b", re.I),
    ),
    "ah_identity": (
        re.compile(r"\bA shares?\b", re.I),
        re.compile(r"\bH shares?\b", re.I),
        re.compile(r"\bjoint stock company incorporated in the People['’]s Republic of China\b", re.I),
        re.compile(r"\bunified social credit (?:identifier|code)\b", re.I),
    ),
}


def extract_continuity_evidence_candidates(
    document_index: str | Path, text_root: str | Path, max_per_category: int = 5,
) -> tuple[list[ContinuityEvidenceCandidate], dict]:
    if max_per_category < 1:
        raise ValueError("连续性证据每类候选上限必须大于0")
    with Path(document_index).open(encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    text_root = Path(text_root)
    candidates = []
    missing_text = []
    for line, row in enumerate(records, 2):
        try:
            local = Path(row["local_path"])
            relative = local.relative_to("data/raw")
            text_path = (text_root / relative).with_suffix(".txt")
            year = int(row["report_year"])
        except (KeyError, ValueError) as error:
            raise ValueError(f"连续性文档索引第{line}行格式错误") from error
        if not text_path.exists():
            missing_text.append(str(text_path))
            continue
        counts: Counter[str] = Counter()
        seen = set()
        for page in read_page_text_export(text_path):
            normalized = re.sub(r"\s+", " ", page.text).strip()
            for category, patterns in PATTERNS.items():
                if counts[category] >= max_per_category:
                    continue
                for pattern in patterns:
                    match = pattern.search(normalized)
                    if not match:
                        continue
                    start, end = max(0, match.start() - 180), min(len(normalized), match.end() + 360)
                    evidence = normalized[start:end]
                    identity = (category, evidence.lower())
                    if identity in seen:
                        break
                    seen.add(identity)
                    counts[category] += 1
                    candidates.append(ContinuityEvidenceCandidate(
                        row["company_code"].strip().upper(), row["company_name"].strip(), category,
                        row["document_type"].strip(), year, row["source_url"].strip(),
                        row["local_path"].strip(), page.page, evidence,
                        .94 if category == "issuer_history" else .88,
                    ))
                    break
    category_counts = Counter(item.evidence_category for item in candidates)
    company_coverage = {
        category: len({item.company_code for item in candidates if item.evidence_category == category})
        for category in PATTERNS
    }
    summary = {
        "document_count": len(records),
        "candidate_count": len(candidates),
        "category_counts": dict(sorted(category_counts.items())),
        "company_coverage": company_coverage,
        "missing_text_count": len(missing_text),
        "missing_text_files": missing_text,
        "applicable": False,
    }
    return candidates, summary


def write_continuity_evidence_candidates(
    output_path: str | Path, summary_path: str | Path,
    candidates: list[ContinuityEvidenceCandidate], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(ContinuityEvidenceCandidate.__annotations__))
        writer.writeheader()
        writer.writerows(asdict(item) for item in candidates)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
