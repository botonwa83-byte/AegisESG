from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .esg_disclosure import QualitativeEvidenceCandidate
from .methodology import Methodology


FEATURE_PATTERNS = {
    "system": re.compile(r"制度|体系|政策|机制|委员会|管理办法|policy|system|framework|committee", re.I),
    "target": re.compile(r"目标|计划|承诺|力争|到20\d{2}|target|goal|commit|by 20\d{2}", re.I),
    "action": re.compile(r"开展|实施|建立|制定|培训|投入|采用|推进|action|implement|establish|training|invest", re.I),
    "result": re.compile(r"完成|实现|达到|通过|减少|提升|同比|零事故|获证|achiev|complet|reduc|increase|certif|no (?:case|incident)", re.I),
}


@dataclass(frozen=True)
class QualitativeReviewPacket:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    indicator_name: str
    indicator_weight: float
    candidate_count: int
    unique_evidence_count: int
    source_pages: str
    max_confidence: float
    has_system: bool
    has_target: bool
    has_action: bool
    has_result: bool
    feature_count: int
    suggested_score: int
    evidence_quality: str
    review_priority: int
    representative_page: int
    representative_evidence: str
    suggestion_reason: str
    review_status: str = "pending"
    scoring_authorized: bool = False


@dataclass(frozen=True)
class QualitativeEvidenceGap:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    indicator_name: str
    indicator_weight: float
    priority: int
    status: str = "evidence_missing"
    next_action: str = "locate_additional_public_evidence"


def read_qualitative_candidates(path: str | Path) -> list[QualitativeEvidenceCandidate]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = set(QualitativeEvidenceCandidate.__annotations__)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"定性证据候选缺少字段: {','.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, 2):
            try:
                status = row["review_status"].strip()
                if status != "pending":
                    raise ValueError("review_status必须为pending")
                rows.append(QualitativeEvidenceCandidate(
                    row["company_code"].strip().upper(), row["company_name"].strip(),
                    int(row["report_year"]), row["indicator_code"].strip(), row["indicator_name"].strip(),
                    row["source_url"].strip(), row["source_file"].strip(), int(row["source_page"]),
                    row["matched_term"].strip(), row["evidence_text"].strip(),
                    float(row["confidence"]), status,
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"定性证据候选第{line}行格式错误: {error}") from error
    return rows


def plan_qualitative_review(
    candidates: list[QualitativeEvidenceCandidate], coverage_path: str | Path,
    methodology: Methodology, report_year: int,
) -> tuple[list[QualitativeReviewPacket], list[QualitativeEvidenceGap], dict]:
    indicators = {item.code: item for item in methodology.qualitative}
    grouped: dict[tuple[str, str], list[QualitativeEvidenceCandidate]] = defaultdict(list)
    for item in candidates:
        if item.report_year != report_year:
            raise ValueError(f"定性证据报告期不一致: {item.company_code}")
        if item.indicator_code not in indicators:
            raise ValueError(f"未知定性指标: {item.indicator_code}")
        grouped[(item.company_code, item.indicator_code)].append(item)
    with Path(coverage_path).open(encoding="utf-8-sig", newline="") as stream:
        coverage = list(csv.DictReader(stream))
    if not coverage or not {"stock_code", "company_name", "annual_status"}.issubset(coverage[0]):
        raise ValueError("文档覆盖审计字段不完整")
    companies = {
        row["stock_code"].strip().upper(): row["company_name"].strip()
        for row in coverage if row["annual_status"].strip() == "collected"
    }
    unknown = sorted({code for code, _ in grouped}.difference(companies))
    if unknown:
        raise ValueError(f"定性证据公司不在年报覆盖范围: {unknown[0]}")
    packets = []
    for key, items in sorted(grouped.items()):
        indicator = indicators[key[1]]
        unique = {re.sub(r"\s+", " ", item.evidence_text).casefold(): item for item in items}
        combined = " ".join(unique)
        features = {name: bool(pattern.search(combined)) for name, pattern in FEATURE_PATTERNS.items()}
        feature_count = sum(features.values())
        if feature_count >= 3 and features["result"]:
            suggested_score = 80
        elif feature_count >= 2 or features["action"]:
            suggested_score = 50
        else:
            suggested_score = 20
        max_confidence = max(item.confidence for item in items)
        if max_confidence >= .75 and feature_count >= 3:
            quality = "strong_candidate"
        elif max_confidence >= .75 or feature_count >= 2:
            quality = "standard_candidate"
        else:
            quality = "weak_candidate"
        priority = 1 if quality == "weak_candidate" or suggested_score == 80 else 2
        representative = max(
            unique.values(),
            key=lambda item: (sum(bool(pattern.search(item.evidence_text)) for pattern in FEATURE_PATTERNS.values()), item.confidence, len(item.evidence_text), -item.source_page),
        )
        packets.append(QualitativeReviewPacket(
            key[0], items[0].company_name, report_year, key[1], indicator.name, indicator.weight,
            len(items), len(unique), "|".join(str(page) for page in sorted({item.source_page for item in items})),
            max_confidence, features["system"], features["target"], features["action"], features["result"],
            feature_count, suggested_score, quality, priority, representative.source_page,
            representative.evidence_text,
            f"heuristic_features={','.join(name for name, present in features.items() if present) or 'mention_only'};human_signature_required",
        ))
    gaps = []
    for code, name in sorted(companies.items()):
        for indicator in methodology.qualitative:
            if (code, indicator.code) not in grouped:
                gaps.append(QualitativeEvidenceGap(
                    code, name, report_year, indicator.code, indicator.name, indicator.weight,
                    1 if indicator.weight >= 3 else 2,
                ))
    quality_counts = defaultdict(int)
    score_counts = defaultdict(int)
    for item in packets:
        quality_counts[item.evidence_quality] += 1
        score_counts[str(item.suggested_score)] += 1
    summary = {
        "report_year": report_year,
        "company_count": len(companies),
        "qualitative_indicator_count": len(methodology.qualitative),
        "expected_group_count": len(companies) * len(methodology.qualitative),
        "candidate_observation_count": len(candidates),
        "review_packet_count": len(packets),
        "evidence_gap_count": len(gaps),
        "quality_counts": dict(sorted(quality_counts.items())),
        "suggested_score_counts": dict(sorted(score_counts.items())),
        "auto_confirmed_count": 0,
        "scoring_authorized": False,
    }
    return packets, gaps, summary


def write_qualitative_review_plan(
    packet_path: str | Path, gap_path: str | Path, summary_path: str | Path,
    packets: list[QualitativeReviewPacket], gaps: list[QualitativeEvidenceGap], summary: dict,
) -> None:
    for path, rows, fields in (
        (packet_path, packets, tuple(QualitativeReviewPacket.__annotations__)),
        (gap_path, gaps, tuple(QualitativeEvidenceGap.__annotations__)),
    ):
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(asdict(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
