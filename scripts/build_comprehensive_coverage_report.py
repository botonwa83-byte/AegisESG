#!/usr/bin/env python3
"""整合所有数据源的索引，生成完整的数据覆盖率报告"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 各个数据源的索引文件
OFFICIAL_INDEX = ROOT / "output/sync/official_document_index.csv"
CNINFO_GAP_DIR = ROOT / "data/raw/cninfo_esg_gap_collection"
MANIFEST = ROOT / "output/audit/scheduled_collection_manifest_v1_2025.csv"
OUTPUT = ROOT / "output/audit/comprehensive_coverage_report_v1_2025.json"


def _identity(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        (row.get("company_code") or "").strip(),
        str(row.get("report_year") or "").strip(),
        (row.get("document_type") or "").strip(),
    )


def _valid_year(value: str) -> bool:
    try:
        year = int(str(value).strip())
    except ValueError:
        return False
    return 1990 <= year <= 2100


def main() -> None:
    # 读取manifest
    with MANIFEST.open(encoding="utf-8-sig", newline="") as stream:
        manifest = list(csv.DictReader(stream))

    manifest_ids = {_identity(row) for row in manifest if _identity(row)[0] and _identity(row)[2]}
    valid_manifest_ids = {key for key in manifest_ids if _valid_year(key[1])}

    # 读取官方索引
    official_ids = set()
    if OFFICIAL_INDEX.is_file():
        with OFFICIAL_INDEX.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                key = _identity(row)
                if key[0] and key[2] and _valid_year(key[1]):
                    official_ids.add(key)

    # 扫描cninfo gap collection
    cninfo_gap_ids = set()
    cninfo_gap_files = []
    if CNINFO_GAP_DIR.is_dir():
        for pdf in CNINFO_GAP_DIR.rglob("*.pdf"):
            parts = pdf.parts
            if len(parts) >= 4 and parts[-1].endswith(".pdf"):
                company_code = parts[-3]
                report_year = parts[-2]
                doc_type = parts[-1].replace(".pdf", "")
                key = (company_code, report_year, doc_type)
                if _valid_year(report_year):
                    cninfo_gap_ids.add(key)
                    cninfo_gap_files.append({
                        "company_code": company_code,
                        "report_year": report_year,
                        "document_type": doc_type,
                        "path": str(pdf.relative_to(ROOT)),
                        "size_mb": round(pdf.stat().st_size / (1024**2), 1)
                    })

    # 合并所有数据源
    all_collected_ids = official_ids | cninfo_gap_ids

    # 计算缺口
    missing_ids = valid_manifest_ids - all_collected_ids

    # 统计新增的cninfo数据
    cninfo_exclusive = cninfo_gap_ids - official_ids

    result = {
        "policy_version": "comprehensive-coverage-v1",
        "manifest_identities": len(valid_manifest_ids),
        "official_collection_identities": len(official_ids),
        "cninfo_gap_identities": len(cninfo_gap_ids),
        "cninfo_exclusive_identities": len(cninfo_exclusive),
        "total_collected_identities": len(all_collected_ids),
        "missing_identities": len(missing_ids),
        "identity_coverage_rate": round(len(all_collected_ids) / len(valid_manifest_ids), 4) if valid_manifest_ids else 0.0,
        "data_sources": {
            "official_exchanges": len(official_ids),
            "cninfo_gap_supplement": len(cninfo_gap_ids)
        },
        "cninfo_gap_files": cninfo_gap_files,
        "missing_by_document_type": dict(Counter(kind for _, _, kind in missing_ids)),
        "missing_companies": sorted([
            {"company_code": code, "report_year": year, "document_type": doc_type}
            for code, year, doc_type in missing_ids
        ], key=lambda x: (x["document_type"], x["company_code"])),
        "coverage_improvement": {
            "before_cninfo": round(len(official_ids) / len(valid_manifest_ids), 4) if valid_manifest_ids else 0.0,
            "after_cninfo": round(len(all_collected_ids) / len(valid_manifest_ids), 4) if valid_manifest_ids else 0.0,
            "improvement": round((len(all_collected_ids) - len(official_ids)) / len(valid_manifest_ids), 4) if valid_manifest_ids else 0.0
        },
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "整合了官方交易所和cninfo补充数据源的完整覆盖率"
    }

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
