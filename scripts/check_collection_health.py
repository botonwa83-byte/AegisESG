#!/usr/bin/env python3
"""健康检查脚本：监控数据收集系统状态"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "output/audit/scheduled_collection_coverage_v1_2025.json"
RETRY = ROOT / "output/audit/scheduled_collection_retry_v1_2025_summary.json"
INDEX = ROOT / "output/sync/official_document_index.csv"
FAILURES = ROOT / "output/sync/official_collection_failures.csv"
COLLECTION_DIR = ROOT / "data/raw/ci_collection"


def main() -> None:
    """运行健康检查并输出报告"""
    print("=" * 60)
    print("ESG数据收集系统健康检查")
    print("=" * 60)
    print(f"检查时间: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}")
    print()

    # 检查覆盖率
    if COVERAGE.is_file():
        coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
        print("📊 数据覆盖率")
        print(f"  ✓ 目标公司: {coverage['manifest_valid_identities']}")
        print(f"  ✓ 已收集: {coverage['downloaded_identities']}")
        print(f"  ✓ 缺失: {coverage['missing_identities']}")
        print(f"  ✓ 覆盖率: {coverage['identity_coverage_rate']*100:.1f}%")
        print()
    else:
        print("⚠️  覆盖率报告不存在")
        print()

    # 检查重试队列
    if RETRY.is_file():
        retry = json.loads(RETRY.read_text(encoding="utf-8"))
        print("🔄 重试队列")
        print(f"  • 待重试: {retry['retry_rows']}个")
        if retry["retry_rows"] > 0:
            print(f"  • 失败分类: {retry['by_failure_class']}")
            print(f"  • 文档类型: {retry['by_document_type']}")
        print()
    else:
        print("⚠️  重试摘要不存在")
        print()

    # 检查索引文件
    if INDEX.is_file():
        index_lines = sum(1 for _ in INDEX.open(encoding="utf-8-sig")) - 1
        print("📁 索引文件")
        print(f"  ✓ 已索引记录: {index_lines}")
    else:
        print("⚠️  索引文件不存在")
    print()

    # 检查失败记录
    if FAILURES.is_file():
        failure_lines = sum(1 for _ in FAILURES.open(encoding="utf-8-sig")) - 1
        print("❌ 失败记录")
        print(f"  • 失败数量: {failure_lines}")
        if failure_lines > 0:
            with FAILURES.open(encoding="utf-8-sig") as f:
                next(f)  # skip header
                for line in f:
                    parts = line.strip().split(',', 5)
                    if len(parts) >= 5:
                        print(f"  • {parts[0]} {parts[1]} {parts[3]}")
    else:
        print("ℹ️  无失败记录")
    print()

    # 检查数据目录
    if COLLECTION_DIR.is_dir():
        pdf_count = sum(1 for _ in COLLECTION_DIR.rglob("*.pdf"))
        total_size = sum(f.stat().st_size for f in COLLECTION_DIR.rglob("*.pdf"))
        print("💾 数据存储")
        print(f"  ✓ PDF文件数: {pdf_count}")
        print(f"  ✓ 总大小: {total_size / (1024**3):.1f} GB")
    else:
        print("⚠️  数据目录不存在")
    print()

    # 健康评分
    print("=" * 60)
    if COVERAGE.is_file():
        coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
        rate = coverage['identity_coverage_rate']
        if rate >= 0.99:
            status = "🟢 优秀"
        elif rate >= 0.95:
            status = "🟡 良好"
        elif rate >= 0.80:
            status = "🟠 一般"
        else:
            status = "🔴 需要改进"
        print(f"系统状态: {status} (覆盖率 {rate*100:.1f}%)")
    else:
        print("系统状态: ⚪ 未知（缺少覆盖率数据）")
    print("=" * 60)


if __name__ == "__main__":
    main()
