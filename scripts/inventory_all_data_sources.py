#!/usr/bin/env python3
"""统计所有数据源中的PDF文件"""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/raw"
OUTPUT = ROOT / "output/audit/all_sources_data_inventory_v1_2025.json"


def main() -> None:
    stats = {
        "total_pdfs": 0,
        "total_size_bytes": 0,
        "by_source": {},
        "sources_summary": []
    }

    # 统计每个数据源
    for source_dir in sorted(RAW_DIR.iterdir()):
        if not source_dir.is_dir():
            continue

        pdfs = list(source_dir.rglob("*.pdf"))
        if not pdfs:
            continue

        total_size = sum(pdf.stat().st_size for pdf in pdfs)

        stats["by_source"][source_dir.name] = {
            "pdf_count": len(pdfs),
            "total_size_bytes": total_size,
            "size_mb": round(total_size / (1024**2), 1),
            "size_gb": round(total_size / (1024**3), 2)
        }

        stats["total_pdfs"] += len(pdfs)
        stats["total_size_bytes"] += total_size

    # 分类数据源
    major_sources = []
    company_dirs = []

    for name, data in stats["by_source"].items():
        if data["pdf_count"] >= 10:
            major_sources.append({
                "name": name,
                "pdf_count": data["pdf_count"],
                "size_gb": data["size_gb"]
            })
        else:
            company_dirs.append(name)

    # 排序
    major_sources.sort(key=lambda x: x["pdf_count"], reverse=True)

    stats["sources_summary"] = {
        "major_sources": major_sources,
        "major_sources_count": len(major_sources),
        "company_directories": len(company_dirs),
        "total_sources": len(stats["by_source"])
    }

    stats["total_size_gb"] = round(stats["total_size_bytes"] / (1024**3), 2)

    OUTPUT.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 打印摘要
    print("=" * 60)
    print("所有数据源统计")
    print("=" * 60)
    print(f"总PDF文件数: {stats['total_pdfs']}")
    print(f"总大小: {stats['total_size_gb']} GB")
    print(f"\n主要数据源 (>=10 PDFs):")
    for src in major_sources[:10]:
        print(f"  • {src['name']}: {src['pdf_count']} PDFs, {src['size_gb']} GB")
    print(f"\n公司目录数: {len(company_dirs)}")
    print(f"总数据源数: {stats['sources_summary']['total_sources']}")


if __name__ == "__main__":
    main()
