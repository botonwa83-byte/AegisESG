from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .universe import UniverseCompany


CODE_PATTERN = re.compile(r"(?<!\d)(\d{5,6})\.(SH|SZ|HK|BJ)")


@dataclass(frozen=True)
class ReferenceSecurity:
    stock_code: str
    company_name: str
    exchange: str
    matched_snapshot: bool
    evidence_file: str
    evidence_pages: str


def extract_reference_securities(
    ocr_path: str | Path, snapshots: Iterable[UniverseCompany], evidence_pages: str,
) -> list[ReferenceSecurity]:
    text = Path(ocr_path).read_text(encoding="utf-8")
    codes = []
    for number, suffix in CODE_PATTERN.findall(text):
        code = f"{number}.{suffix}"
        if code not in codes:
            codes.append(code)
    names = {item.stock_code: item.company_name for item in snapshots}
    return [ReferenceSecurity(
        code, names.get(code, "待核对"), _exchange(code), code in names,
        str(ocr_path), evidence_pages,
    ) for code in codes]


def write_reference_securities(path: str | Path, rows: Iterable[ReferenceSecurity]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(ReferenceSecurity.__annotations__)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(vars(item) for item in rows)


def _exchange(code: str) -> str:
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE", "HK": "HKEX"}[code[-2:]]
