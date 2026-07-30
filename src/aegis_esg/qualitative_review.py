from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .esg_disclosure import QualitativeEvidenceCandidate
from .methodology import Methodology
from .models import Observation, ValueStatus


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
    representative_source_url: str
    representative_source_file: str
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


@dataclass(frozen=True)
class QualitativeReviewDecision:
    company_code: str
    report_year: int
    indicator_code: str
    action: str
    selected_score: str
    reviewer: str
    reviewed_at: str
    note: str


@dataclass(frozen=True)
class QualitativeReviewAudit:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    suggested_score: int
    action: str
    selected_score: str
    representative_page: int
    reviewer: str
    reviewed_at: str
    note: str


QUALITATIVE_DECISION_COLUMNS = tuple(QualitativeReviewPacket.__annotations__) + (
    "action", "selected_score", "reviewer", "reviewed_at", "note",
)


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
            feature_count, suggested_score, quality, priority, representative.source_url,
            representative.source_file, representative.source_page,
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


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{field}不是布尔值")


def read_qualitative_review_packets(path: str | Path) -> list[QualitativeReviewPacket]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(QualitativeReviewPacket.__annotations__) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"定性复核包缺少字段: {','.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, 2):
            try:
                packet = QualitativeReviewPacket(
                    row["company_code"].strip().upper(), row["company_name"].strip(), int(row["report_year"]),
                    row["indicator_code"].strip(), row["indicator_name"].strip(), float(row["indicator_weight"]),
                    int(row["candidate_count"]), int(row["unique_evidence_count"]), row["source_pages"].strip(),
                    float(row["max_confidence"]), _parse_bool(row["has_system"], "has_system"),
                    _parse_bool(row["has_target"], "has_target"), _parse_bool(row["has_action"], "has_action"),
                    _parse_bool(row["has_result"], "has_result"), int(row["feature_count"]),
                    int(row["suggested_score"]), row["evidence_quality"].strip(), int(row["review_priority"]),
                    row["representative_source_url"].strip(), row["representative_source_file"].strip(),
                    int(row["representative_page"]), row["representative_evidence"].strip(),
                    row["suggestion_reason"].strip(), row["review_status"].strip(),
                    _parse_bool(row["scoring_authorized"], "scoring_authorized"),
                )
                flags = (packet.has_system, packet.has_target, packet.has_action, packet.has_result)
                pages = {int(page) for page in packet.source_pages.split("|") if page}
                if packet.suggested_score not in {20, 50, 80} or packet.feature_count != sum(flags):
                    raise ValueError("建议档位或特征计数无效")
                if packet.representative_page not in pages or not packet.representative_source_url or not packet.representative_source_file:
                    raise ValueError("代表证据来源不完整")
                rows.append(packet)
            except (TypeError, ValueError) as error:
                raise ValueError(f"定性复核包第{line}行格式错误: {error}") from error
    if any(item.review_status != "pending" or item.scoring_authorized for item in rows):
        raise ValueError("定性复核包必须保持pending且禁止评分")
    return rows


def write_qualitative_review_template(
    path: str | Path, packets: list[QualitativeReviewPacket], priority: int | None = None,
    limit: int | None = None,
) -> int:
    if priority is not None and priority not in {1, 2}:
        raise ValueError("复核优先级只能是1或2")
    if limit is not None and limit < 1:
        raise ValueError("复核批次上限必须大于0")
    selected = [item for item in packets if priority is None or item.review_priority == priority]
    selected.sort(key=lambda item: (item.review_priority, -item.indicator_weight, item.company_code, item.indicator_code))
    if limit is not None:
        selected = selected[:limit]
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=QUALITATIVE_DECISION_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in selected:
            writer.writerow(asdict(item) | {
                "action": "", "selected_score": "", "reviewer": "", "reviewed_at": "", "note": "",
            })
    return len(selected)


def read_qualitative_review_decisions(path: str | Path) -> list[QualitativeReviewDecision]:
    decisions = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"company_code", "report_year", "indicator_code", "action", "selected_score", "reviewer", "reviewed_at", "note"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"定性复核决定缺少字段: {','.join(sorted(missing))}")
        for line, row in enumerate(reader, 2):
            action = row["action"].strip().lower()
            if not action:
                continue
            if action not in {"confirm", "reject"}:
                raise ValueError(f"定性复核决定第{line}行action无效")
            score = row["selected_score"].strip()
            reviewer, reviewed_at, note = row["reviewer"].strip(), row["reviewed_at"].strip(), row["note"].strip()
            if not reviewer or not reviewed_at or not note:
                raise ValueError("定性复核决定必须填写reviewer、reviewed_at和note")
            try:
                parsed_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"reviewed_at不是ISO-8601时间: {reviewed_at}") from error
            if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                raise ValueError("reviewed_at必须包含时区")
            if action == "confirm":
                try:
                    numeric = int(score)
                except ValueError as error:
                    raise ValueError("confirm必须填写离散selected_score") from error
                if str(numeric) != score or numeric not in {0, 20, 50, 80, 100}:
                    raise ValueError("selected_score只能是0/20/50/80/100")
                if numeric == 100 and not re.search(r"领先|标杆|leading|benchmark", note, re.I):
                    raise ValueError("100分决定必须在note说明行业领先或标杆证据")
            elif score:
                raise ValueError("reject禁止填写selected_score")
            decisions.append(QualitativeReviewDecision(
                row["company_code"].strip().upper(), int(row["report_year"]), row["indicator_code"].strip(),
                action, score, reviewer, reviewed_at, note,
            ))
    return decisions


def apply_qualitative_review_decisions(
    packets: list[QualitativeReviewPacket], decisions: list[QualitativeReviewDecision],
) -> tuple[list[Observation], list[QualitativeReviewPacket], list[QualitativeReviewAudit]]:
    groups = {(item.company_code, item.report_year, item.indicator_code): item for item in packets}
    if len(groups) != len(packets):
        raise ValueError("定性复核包存在重复公司指标")
    by_key = {(item.company_code, item.report_year, item.indicator_code): item for item in decisions}
    if len(by_key) != len(decisions):
        raise ValueError("定性复核决定存在重复公司指标")
    unknown = set(by_key) - set(groups)
    if unknown:
        raise ValueError(f"定性复核决定找不到复核包: {sorted(unknown)[0]}")
    for decision in decisions:
        if decision.action not in {"confirm", "reject"} or not decision.reviewer or not decision.reviewed_at or not decision.note:
            raise ValueError("定性复核决定签名字段无效")
        try:
            parsed_time = datetime.fromisoformat(decision.reviewed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"reviewed_at不是ISO-8601时间: {decision.reviewed_at}") from error
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ValueError("reviewed_at必须包含时区")
        if decision.action == "confirm":
            if decision.selected_score not in {"0", "20", "50", "80", "100"}:
                raise ValueError("selected_score只能是0/20/50/80/100")
            if decision.selected_score == "100" and not re.search(r"领先|标杆|leading|benchmark", decision.note, re.I):
                raise ValueError("100分决定必须在note说明行业领先或标杆证据")
        elif decision.selected_score:
            raise ValueError("reject禁止填写selected_score")
    confirmed, unresolved, audits = [], [], []
    for key, packet in sorted(groups.items()):
        decision = by_key.get(key)
        if decision is None:
            unresolved.append(packet)
            continue
        selected_score = ""
        if decision.action == "confirm":
            selected_score = decision.selected_score
            confirmed.append(Observation(
                packet.company_code, packet.company_name, packet.report_year, packet.indicator_code,
                float(selected_score), ValueStatus.CONFIRMED, source_url=packet.representative_source_url,
                source_file=packet.representative_source_file,
                source_page=packet.representative_page, evidence_text=(
                    packet.representative_evidence +
                    f" [qualitative-manual-review:{decision.reviewer}/{decision.reviewed_at}/{decision.note}]"
                ), confidence=1.0,
            ))
        audits.append(QualitativeReviewAudit(
            packet.company_code, packet.company_name, packet.report_year, packet.indicator_code,
            packet.suggested_score, decision.action, selected_score, packet.representative_page,
            decision.reviewer, decision.reviewed_at, decision.note,
        ))
    return confirmed, unresolved, audits


def write_qualitative_review_results(
    unresolved_path: str | Path, audit_path: str | Path,
    unresolved: list[QualitativeReviewPacket], audits: list[QualitativeReviewAudit],
) -> None:
    unresolved_output = Path(unresolved_path)
    unresolved_output.parent.mkdir(parents=True, exist_ok=True)
    with unresolved_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(QualitativeReviewPacket.__annotations__), lineterminator="\n")
        writer.writeheader(); writer.writerows(asdict(item) for item in unresolved)
    audit_output = Path(audit_path)
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    with audit_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(QualitativeReviewAudit.__annotations__), lineterminator="\n")
        writer.writeheader(); writer.writerows(asdict(item) for item in audits)
