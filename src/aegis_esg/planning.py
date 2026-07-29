from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .collector import DocumentRecord
from .universe import UniverseCompany


@dataclass(frozen=True)
class CollectionTask:
    stock_code: str
    company_name: str
    exchange: str
    report_year: int
    annual_status: str
    esg_status: str
    next_action: str
    priority: int


def read_document_records(path: str | Path) -> list[DocumentRecord]:
    source = Path(path)
    if not source.exists():
        return []
    result = []
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            try:
                result.append(DocumentRecord(
                    row["company_code"].strip().upper(), row["company_name"].strip(),
                    int(row["report_year"]), row["document_type"].strip(), row["source_url"].strip(),
                    (row.get("retrieval_url") or row["source_url"]).strip(), row["local_path"].strip(),
                    row["sha256"].strip(), int(row["size"]),
                ))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"文档索引第{line}行格式错误") from error
    return result


def merge_document_indexes(paths: Iterable[str | Path]) -> tuple[list[DocumentRecord], dict]:
    records = []
    by_url: dict[str, DocumentRecord] = {}
    by_path: dict[str, DocumentRecord] = {}
    duplicate_count = 0
    source_count = 0
    for path in paths:
        source_count += 1
        for record in read_document_records(path):
            existing_url = by_url.get(record.source_url)
            existing_path = by_path.get(record.local_path)
            if existing_url is not None:
                if existing_url != record:
                    raise ValueError(f"文档索引URL元数据冲突: {record.source_url}")
                duplicate_count += 1
                continue
            if existing_path is not None:
                raise ValueError(f"文档索引本地路径冲突: {record.local_path}")
            by_url[record.source_url] = record
            by_path[record.local_path] = record
            records.append(record)
    records.sort(key=lambda item: (item.company_code, item.report_year, item.document_type, item.source_url))
    summary = {
        "source_index_count": source_count,
        "document_count": len(records),
        "company_count": len({item.company_code for item in records}),
        "duplicate_count": duplicate_count,
        "complete": True,
    }
    return records, summary


def plan_collection(
    companies: Iterable[UniverseCompany], records: Iterable[DocumentRecord], report_year: int,
) -> list[CollectionTask]:
    available = {(item.company_code, item.report_year, item.document_type) for item in records}
    tasks = []
    for company in companies:
        if not company.included:
            continue
        annual = "collected" if (company.stock_code, report_year, "annual_report") in available else "missing"
        esg = "collected" if (company.stock_code, report_year, "esg_report") in available else "missing"
        if annual == "missing":
            action, priority = "discover_annual_and_esg", 1
        elif esg == "missing":
            action, priority = "discover_esg_or_scan_annual", 2
        else:
            action, priority = "ready_for_extraction", 3
        tasks.append(CollectionTask(
            company.stock_code, company.company_name, company.exchange, report_year,
            annual, esg, action, priority,
        ))
    return sorted(tasks, key=lambda item: (item.priority, item.exchange, item.stock_code))


def collection_summary(tasks: Iterable[CollectionTask]) -> dict:
    rows = list(tasks)
    return {
        "company_count": len(rows),
        "annual_collected": sum(item.annual_status == "collected" for item in rows),
        "esg_collected": sum(item.esg_status == "collected" for item in rows),
        "ready_for_extraction": sum(item.next_action == "ready_for_extraction" for item in rows),
        "actions": dict(sorted(Counter(item.next_action for item in rows).items())),
        "exchanges": dict(sorted(Counter(item.exchange for item in rows).items())),
    }


def write_collection_plan(path: str | Path, tasks: Iterable[CollectionTask]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(CollectionTask.__annotations__)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(vars(item) for item in tasks)


def write_collection_summary(path: str | Path, summary: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
