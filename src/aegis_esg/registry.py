from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .universe import UniverseCompany


@dataclass(frozen=True)
class RegistryEntry:
    source_row: int
    supplied_code: str
    supplied_name: str
    matched_code: str
    matched_name: str
    exchange: str
    match_status: str
    match_method: str
    candidate_codes: str
    source_name: str
    source_url: str
    as_of_date: str


def reconcile_registry(
    path: str | Path, snapshots: Iterable[UniverseCompany],
    source_name: str, source_url: str, as_of_date: str,
) -> list[RegistryEntry]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return []
    code_column = _find_column(rows[0], ("stock_code", "证券代码", "股票代码", "代码"))
    name_column = _find_column(rows[0], ("company_name", "公司名称", "公司简称", "证券简称", "企业名称"))
    if not code_column and not name_column:
        raise ValueError("企业名录至少需要证券代码或公司名称字段")
    snapshot_rows = list(snapshots)
    by_code = {item.stock_code: item for item in snapshot_rows}
    by_name: dict[str, list[UniverseCompany]] = {}
    for item in snapshot_rows:
        by_name.setdefault(normalize_company_name(item.company_name), []).append(item)
    result = []
    for source_row, row in enumerate(rows, 2):
        code = (row.get(code_column) or "").strip().upper() if code_column else ""
        name = (row.get(name_column) or "").strip() if name_column else ""
        match, status, method, candidates = _match_entry(code, name, by_code, by_name)
        result.append(RegistryEntry(
            source_row, code, name, match.stock_code if match else "",
            match.company_name if match else "", match.exchange if match else "",
            status, method, ";".join(candidates), source_name, source_url, as_of_date,
        ))
    return result


def write_registry_reconciliation(path: str | Path, rows: Iterable[RegistryEntry]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(RegistryEntry.__annotations__)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(vars(item) for item in rows)


def normalize_company_name(value: str) -> str:
    name = re.sub(r"[\s　（）()·•\-]+", "", value).upper()
    name = re.sub(r"(?:集团)?股份有限公司$|股份有限公司$|有限公司$", "", name)
    name = re.sub(r"(?:集团)$", "", name)
    name = re.sub(r"[ＡA]$", "", name)
    return name


def _match_entry(code, name, by_code, by_name):
    if code and code in by_code:
        match = by_code[code]
        if name and normalize_company_name(name) != normalize_company_name(match.company_name):
            return match, "review", "code_exact_name_conflict", [match.stock_code]
        return match, "matched", "code_exact", [match.stock_code]
    candidates = by_name.get(normalize_company_name(name), []) if name else []
    if len(candidates) == 1:
        return candidates[0], "matched", "name_normalized", [candidates[0].stock_code]
    if len(candidates) > 1:
        return None, "ambiguous", "name_multiple", [item.stock_code for item in candidates]
    return None, "unmatched", "none", []


def _find_column(row: dict, aliases: tuple[str, ...]):
    normalized = {re.sub(r"[\s_\-]+", "", key).lower(): key for key in row}
    for alias in aliases:
        key = re.sub(r"[\s_\-]+", "", alias).lower()
        if key in normalized:
            return normalized[key]
    return None
