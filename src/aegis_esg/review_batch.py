from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .models import Observation
from .qualitative_review import (
    QUALITATIVE_DECISION_COLUMNS,
    QualitativeReviewAudit,
    QualitativeReviewDecision,
    QualitativeReviewPacket,
    apply_qualitative_review_decisions,
    parse_qualitative_decision_rows,
)


@dataclass(frozen=True)
class QualitativeReviewBatch:
    batch_id: str
    label: str
    report_year: int
    priority: int
    group_count: int
    keys_sha256: str
    batch_file: str
    batch_sha256: str
    packets_sha256: str
    status: str = "open"
    decided_count: int = 0
    completion_rate: float = 0.0


BATCH_COLUMNS = ("batch_id",) + QUALITATIVE_DECISION_COLUMNS
BATCH_LEDGER_COLUMNS = tuple(QualitativeReviewBatch.__annotations__)
PROGRESS_COLUMNS = ("batch_id",) + tuple(QualitativeReviewAudit.__annotations__)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _group_key(company_code: str, report_year: int, indicator_code: str) -> str:
    return f"{company_code.strip().upper()}|{report_year}|{indicator_code.strip()}"


def _keys_digest(keys: list[str]) -> str:
    return _sha256_text("\n".join(sorted(keys)))


def read_batch_ledger(path: str | Path) -> list[QualitativeReviewBatch]:
    ledger = Path(path)
    if not ledger.exists():
        return []
    with ledger.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(BATCH_LEDGER_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"复核批次清单缺少字段: {','.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, 2):
            try:
                batch = QualitativeReviewBatch(
                    row["batch_id"].strip(), row["label"].strip(), int(row["report_year"]),
                    int(row["priority"]), int(row["group_count"]), row["keys_sha256"].strip(),
                    row["batch_file"].strip(), row["batch_sha256"].strip(),
                    row["packets_sha256"].strip(), row["status"].strip(),
                    int(row["decided_count"]), float(row["completion_rate"]),
                )
            except (TypeError, ValueError) as error:
                raise ValueError(f"复核批次清单第{line}行格式错误: {error}") from error
            if batch.status not in {"open", "closed"}:
                raise ValueError(f"复核批次清单第{line}行status无效")
            if not batch.batch_id.startswith("QRB-") or len(batch.keys_sha256) != 64:
                raise ValueError(f"复核批次清单第{line}行批次标识无效")
            if not 0 <= batch.decided_count <= batch.group_count:
                raise ValueError(f"复核批次清单第{line}行完成计数越界")
            rows.append(batch)
    identifiers = [item.batch_id for item in rows]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("复核批次清单存在重复batch_id")
    return rows


def write_batch_ledger(path: str | Path, batches: list[QualitativeReviewBatch]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BATCH_LEDGER_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(item) for item in batches)


def create_review_batch(
    packets: list[QualitativeReviewPacket], batch_path: str | Path, ledger_path: str | Path,
    packets_path: str | Path, label: str = "", priority: int | None = None, limit: int | None = None,
) -> QualitativeReviewBatch:
    if priority is not None and priority not in {1, 2}:
        raise ValueError("复核优先级只能是1或2")
    if limit is not None and limit < 1:
        raise ValueError("复核批次上限必须大于0")
    if not packets:
        raise ValueError("定性复核包为空，不能创建批次")
    years = {item.report_year for item in packets}
    if len(years) != 1:
        raise ValueError("定性复核包报告期不一致")
    selected = [item for item in packets if priority is None or item.review_priority == priority]
    selected.sort(key=lambda item: (item.review_priority, -item.indicator_weight, item.company_code, item.indicator_code))
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("按当前优先级筛选后无可分配复核组")
    keys = [_group_key(item.company_code, item.report_year, item.indicator_code) for item in selected]
    if len(set(keys)) != len(keys):
        raise ValueError("批次内存在重复公司指标组")
    digest = _keys_digest(keys)
    ledger = read_batch_ledger(ledger_path)
    open_batches = [item for item in ledger if item.status == "open"]
    if any(item.keys_sha256 == digest for item in open_batches):
        raise ValueError("相同复核组集合已存在未关闭批次，禁止重复分配")
    batch_id = f"QRB-{digest[:16]}"
    if any(item.batch_id == batch_id for item in ledger):
        raise ValueError(f"批次{batch_id}已存在于清单")
    output = Path(batch_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BATCH_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in selected:
            writer.writerow(asdict(item) | {
                "batch_id": batch_id, "action": "", "selected_score": "",
                "reviewer": "", "reviewed_at": "", "note": "",
            })
    batch = QualitativeReviewBatch(
        batch_id, label.strip(), years.pop(), priority or 0, len(selected), digest,
        str(output), _sha256_file(output), _sha256_file(packets_path),
    )
    ledger.append(batch)
    write_batch_ledger(ledger_path, ledger)
    return batch


def read_review_progress(path: str | Path, batch_id: str) -> list[QualitativeReviewAudit]:
    progress = Path(path)
    if not progress.exists():
        return []
    with progress.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(PROGRESS_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"批次进度缺少字段: {','.join(sorted(missing))}")
        rows = []
        for line, row in enumerate(reader, 2):
            if row["batch_id"].strip() != batch_id:
                raise ValueError(f"批次进度第{line}行batch_id不一致")
            try:
                rows.append(QualitativeReviewAudit(
                    row["company_code"].strip().upper(), row["company_name"].strip(),
                    int(row["report_year"]), row["indicator_code"].strip(),
                    int(row["suggested_score"]), row["action"].strip(), row["selected_score"].strip(),
                    int(row["representative_page"]), row["reviewer"].strip(),
                    row["reviewed_at"].strip(), row["note"].strip(),
                ))
            except (TypeError, ValueError) as error:
                raise ValueError(f"批次进度第{line}行格式错误: {error}") from error
    keys = [_group_key(item.company_code, item.report_year, item.indicator_code) for item in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("批次进度存在重复公司指标组")
    return rows


def write_review_progress(path: str | Path, batch_id: str, audits: list[QualitativeReviewAudit]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PROGRESS_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in audits:
            writer.writerow({"batch_id": batch_id} | asdict(item))


def read_batch_rows(path: str | Path) -> tuple[str, list[dict]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(BATCH_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"复核批次缺少字段: {','.join(sorted(missing))}")
        rows = [row for row in reader]
    if not rows:
        raise ValueError("复核批次为空")
    batch_ids = {(row.get("batch_id") or "").strip() for row in rows}
    if len(batch_ids) != 1 or not next(iter(batch_ids)).startswith("QRB-"):
        raise ValueError("复核批次batch_id缺失或不一致")
    keys = [_group_key(row["company_code"], int(row["report_year"]), row["indicator_code"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("复核批次存在重复公司指标组")
    return next(iter(batch_ids)), rows


def apply_review_batch(
    packets: list[QualitativeReviewPacket], ledger: list[QualitativeReviewBatch],
    batch_id: str, batch_rows: list[dict], progress: list[QualitativeReviewAudit],
) -> tuple[list[Observation], list[QualitativeReviewPacket], list[QualitativeReviewAudit], QualitativeReviewBatch]:
    matches = [item for item in ledger if item.batch_id == batch_id]
    if not matches:
        raise ValueError(f"批次{batch_id}不在复核批次清单中")
    batch = matches[0]
    if batch.status == "closed":
        raise ValueError(f"批次{batch_id}已关闭，禁止再次应用")
    row_keys = [_group_key(row["company_code"], int(row["report_year"]), row["indicator_code"]) for row in batch_rows]
    if _keys_digest(row_keys) != batch.keys_sha256:
        raise ValueError("复核批次公司指标组与清单登记哈希不一致，禁止跨批覆盖")
    packet_index = {
        _group_key(item.company_code, item.report_year, item.indicator_code): item for item in packets
    }
    missing = [key for key in row_keys if key not in packet_index]
    if missing:
        raise ValueError(f"复核批次包含未知复核包: {missing[0]}")
    decided_keys = {_group_key(item.company_code, item.report_year, item.indicator_code) for item in progress}
    decisions = parse_qualitative_decision_rows([
        {field: (row.get(field) or "") for field in QualitativeReviewDecision.__annotations__}
        for row in batch_rows
    ])
    new_keys = [_group_key(item.company_code, item.report_year, item.indicator_code) for item in decisions]
    overlap = decided_keys.intersection(new_keys)
    if overlap:
        raise ValueError(f"公司指标组已有签名决定，禁止覆盖: {sorted(overlap)[0]}")
    remaining_packets = [
        packet_index[key] for key in row_keys if key not in decided_keys
    ]
    confirmed, unresolved, audits = apply_qualitative_review_decisions(remaining_packets, decisions)
    accumulated = list(progress) + audits
    decided_count = len(accumulated)
    if decided_count > batch.group_count:
        raise ValueError("批次完成计数越界")
    status = "closed" if decided_count == batch.group_count else "open"
    updated = replace(
        batch, status=status, decided_count=decided_count,
        completion_rate=round(decided_count / batch.group_count, 6),
    )
    return confirmed, unresolved, audits, updated


def update_ledger_entry(ledger: list[QualitativeReviewBatch], updated: QualitativeReviewBatch) -> list[QualitativeReviewBatch]:
    result = [updated if item.batch_id == updated.batch_id else item for item in ledger]
    if not any(item.batch_id == updated.batch_id for item in ledger):
        raise ValueError(f"批次{updated.batch_id}不在复核批次清单中")
    return result
