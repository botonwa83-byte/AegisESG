from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from .extraction import read_page_text_export


@dataclass(frozen=True)
class ContinuityEvidenceCandidate:
    candidate_id: str
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


@dataclass(frozen=True)
class ContinuityReviewPacket:
    task_id: str
    decision_id: str
    stock_code: str
    priority: int
    next_action: str
    historical_name: str
    current_chinese_name: str
    issuer_history_candidate_ids: str
    issuer_history_pages: str
    principal_business_candidate_ids: str
    principal_business_pages: str
    ah_identity_candidate_ids: str
    ah_identity_pages: str
    profile_evidence_url: str
    candidate_count: int
    review_readiness: str
    outcome: str
    related_a_code: str
    entity_id: str
    selected_candidate_ids: str
    evidence_url: str
    evidence_date: str
    reviewer: str
    reviewed_at: str
    rationale: str
    review_status: str


@dataclass(frozen=True)
class SignedContinuityDecision:
    decision_id: str
    stock_code: str
    outcome: str
    related_a_code: str
    entity_id: str
    evidence_url: str
    evidence_date: str
    reviewer: str
    reviewed_at: str
    rationale: str


@dataclass(frozen=True)
class FinalizedContinuityReview:
    decision_id: str
    stock_code: str
    outcome: str
    selected_candidate_ids: str
    selected_categories: str
    selected_candidate_count: int
    evidence_url: str
    reviewer: str
    reviewed_at: str


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
        re.compile(r"\bA [Ss]hares?\b"),
        re.compile(r"\bH [Ss]hares?\b"),
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
    candidate_sequence: Counter[tuple] = Counter()
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
                    sequence_key = (
                        row["company_code"].strip().upper(), category,
                        row["document_type"].strip(), year, page.page,
                    )
                    candidate_sequence[sequence_key] += 1
                    candidate_id = "HKCE-{}-{}-{}-{}-P{}-{}".format(
                        row["company_code"].strip().upper().replace(".", "-"),
                        category.upper(), row["document_type"].strip().upper(), year,
                        page.page, candidate_sequence[sequence_key],
                    )
                    candidates.append(ContinuityEvidenceCandidate(
                        candidate_id, row["company_code"].strip().upper(), row["company_name"].strip(), category,
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
        writer = csv.DictWriter(
            stream, fieldnames=tuple(ContinuityEvidenceCandidate.__annotations__), lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(asdict(item) for item in candidates)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_continuity_review_packets(
    tasks_path: str | Path, candidates_path: str | Path,
) -> tuple[list[ContinuityReviewPacket], dict]:
    tasks = _read_csv(tasks_path)
    candidates = _read_csv(candidates_path)
    required_task = {
        "task_id", "stock_code", "priority", "next_action", "historical_name",
        "current_chinese_name", "profile_evidence_url",
    }
    required_candidate = {"candidate_id", "company_code", "evidence_category", "source_page"}
    if not tasks or not required_task.issubset(tasks[0]):
        raise ValueError("连续性证据任务字段不完整")
    if not candidates or not required_candidate.issubset(candidates[0]):
        raise ValueError("连续性证据候选字段不完整")
    candidate_ids = [row["candidate_id"].strip() for row in candidates]
    if any(not item for item in candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("连续性证据候选ID为空或重复")
    by_code: dict[str, list[dict]] = {}
    for row in candidates:
        by_code.setdefault(row["company_code"].strip().upper(), []).append(row)
    packets = []
    seen_codes = set()
    for line, task in enumerate(tasks, 2):
        code = task["stock_code"].strip().upper()
        if code in seen_codes:
            raise ValueError(f"连续性证据任务第{line}行证券代码重复")
        seen_codes.add(code)
        rows = by_code.get(code)
        if not rows:
            continue
        grouped = {category: [] for category in PATTERNS}
        for row in rows:
            category = row["evidence_category"].strip()
            if category not in grouped:
                raise ValueError(f"连续性证据候选类别无效: {category}")
            grouped[category].append(row)

        def values(category, field):
            items = grouped[category]
            if field == "source_page":
                return "|".join(str(item) for item in sorted({int(row[field]) for row in items}))
            return "|".join(row[field].strip() for row in items)

        categories_present = sum(bool(grouped[category]) for category in PATTERNS)
        packets.append(ContinuityReviewPacket(
            task["task_id"].strip(), "", code, int(task["priority"]), task["next_action"].strip(),
            task["historical_name"].strip(), task["current_chinese_name"].strip(),
            values("issuer_history", "candidate_id"), values("issuer_history", "source_page"),
            values("principal_business", "candidate_id"), values("principal_business", "source_page"),
            values("ah_identity", "candidate_id"), values("ah_identity", "source_page"),
            task["profile_evidence_url"].strip(), len(rows),
            "evidence_candidates_available" if categories_present else "missing_evidence_candidates",
            "", "", "", "", "", "", "", "", "", "unsigned",
        ))
    packets.sort(key=lambda item: (item.priority, item.stock_code))
    summary = {
        "task_count": len(tasks),
        "candidate_count": len(candidates),
        "packet_count": len(packets),
        "unsigned_count": sum(item.review_status == "unsigned" for item in packets),
        "codes_without_candidates": sorted(seen_codes.difference(by_code)),
        "applicable": False,
    }
    return packets, summary


def write_continuity_review_packets(
    output_path: str | Path, summary_path: str | Path,
    packets: list[ContinuityReviewPacket], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=tuple(ContinuityReviewPacket.__annotations__), lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(asdict(item) for item in packets)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def finalize_continuity_reviews(
    packets_path: str | Path, candidates_path: str | Path,
) -> tuple[list[SignedContinuityDecision], list[FinalizedContinuityReview], dict]:
    packets = _read_csv(packets_path)
    candidates = _read_csv(candidates_path)
    required_packet = {
        "decision_id", "stock_code", "outcome", "related_a_code", "entity_id",
        "selected_candidate_ids", "evidence_url", "evidence_date", "reviewer",
        "reviewed_at", "rationale", "review_status",
    }
    required_candidate = {"candidate_id", "company_code", "evidence_category", "source_url"}
    if not packets or not required_packet.issubset(packets[0]):
        raise ValueError("连续性人工复核包字段不完整")
    if not candidates or not required_candidate.issubset(candidates[0]):
        raise ValueError("连续性证据候选字段不完整")
    candidate_by_id = {}
    for row in candidates:
        candidate_id = row["candidate_id"].strip()
        if not candidate_id or candidate_id in candidate_by_id:
            raise ValueError("连续性证据候选ID为空或重复")
        candidate_by_id[candidate_id] = row
    decisions = []
    audits = []
    decision_ids = set()
    stock_codes = set()
    for line, raw in enumerate(packets, 2):
        item = {key: (raw.get(key) or "").strip() for key in required_packet}
        item["stock_code"] = item["stock_code"].upper()
        item["related_a_code"] = item["related_a_code"].upper()
        item["entity_id"] = item["entity_id"].upper()
        item["outcome"] = item["outcome"].lower()
        if item["review_status"].lower() != "signed":
            raise ValueError(f"连续性复核包第{line}行尚未签名")
        if not all(item[key] for key in (
            "decision_id", "stock_code", "outcome", "selected_candidate_ids",
            "evidence_url", "evidence_date", "reviewer", "reviewed_at", "rationale",
        )):
            raise ValueError(f"连续性复核包第{line}行签名字段不完整")
        if item["decision_id"] in decision_ids or item["stock_code"] in stock_codes:
            raise ValueError(f"连续性复核包第{line}行决定ID或证券代码重复")
        if item["outcome"] not in {"same_issuer", "new_issuer", "ah_same_entity"}:
            raise ValueError(f"连续性复核包第{line}行outcome无效")
        try:
            date.fromisoformat(item["evidence_date"])
            reviewed_at = datetime.fromisoformat(item["reviewed_at"])
        except ValueError as error:
            raise ValueError(f"连续性复核包第{line}行日期无效") from error
        if reviewed_at.tzinfo is None:
            raise ValueError(f"连续性复核包第{line}行审核时间必须含时区")
        selected_ids = [value.strip() for value in item["selected_candidate_ids"].split("|") if value.strip()]
        if len(set(selected_ids)) != len(selected_ids):
            raise ValueError(f"连续性复核包第{line}行候选ID重复")
        selected = []
        for candidate_id in selected_ids:
            candidate = candidate_by_id.get(candidate_id)
            if candidate is None or candidate["company_code"].strip().upper() != item["stock_code"]:
                raise ValueError(f"连续性复核包第{line}行候选ID未匹配本证券")
            selected.append(candidate)
        selected_urls = {row["source_url"].strip() for row in selected}
        if item["evidence_url"] not in selected_urls:
            raise ValueError(f"连续性复核包第{line}行证据URL不属于所选候选")
        categories = sorted({row["evidence_category"].strip() for row in selected})
        if item["outcome"] == "ah_same_entity":
            if "ah_identity" not in categories or not item["related_a_code"] or not item["entity_id"]:
                raise ValueError(f"连续性复核包第{line}行A/H结论缺少身份候选或主体字段")
        elif item["related_a_code"] or item["entity_id"]:
            raise ValueError(f"连续性复核包第{line}行非A/H结论不能填写主体映射")
        decision_ids.add(item["decision_id"])
        stock_codes.add(item["stock_code"])
        decisions.append(SignedContinuityDecision(
            item["decision_id"], item["stock_code"], item["outcome"], item["related_a_code"],
            item["entity_id"], item["evidence_url"], item["evidence_date"], item["reviewer"],
            item["reviewed_at"], item["rationale"],
        ))
        audits.append(FinalizedContinuityReview(
            item["decision_id"], item["stock_code"], item["outcome"], "|".join(selected_ids),
            "|".join(categories), len(selected), item["evidence_url"], item["reviewer"], item["reviewed_at"],
        ))
    summary = {
        "packet_count": len(packets),
        "signed_decision_count": len(decisions),
        "selected_candidate_count": sum(item.selected_candidate_count for item in audits),
        "outcome_counts": dict(sorted(Counter(item.outcome for item in decisions).items())),
        "complete": len(decisions) == len(packets),
    }
    return decisions, audits, summary


def write_finalized_continuity_reviews(
    decisions_path: str | Path, audit_path: str | Path, summary_path: str | Path,
    decisions: list[SignedContinuityDecision], audits: list[FinalizedContinuityReview], summary: dict,
) -> None:
    for path, rows, row_type in (
        (decisions_path, decisions, SignedContinuityDecision),
        (audit_path, audits, FinalizedContinuityReview),
    ):
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=tuple(row_type.__annotations__), lineterminator="\n")
            writer.writeheader()
            writer.writerows(asdict(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))
