#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_population_gap_diagnostics_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_population_review_packet_v1_2025.html"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows.sort(key=lambda row: (row["indicator_code"], row["company_code"]))
    body = "".join(f'<tr><td>{html.escape(row["indicator_name"])}<br><small>{html.escape(row["company_code"])} {html.escape(row["company_name"])}</small></td><td>{html.escape(row["diagnostic_category"])}</td><td>{html.escape(row["source_pages"] or "未标页")}</td><td>{html.escape(row["diagnostic_excerpt"][:600] or "未发现可用原文")}</td><td>人工判断是否存在同口径值；不得降门或强行换算</td></tr>' for row in rows)
    OUTPUT.write_text(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>薄样本指标复核包</title><style>body{{font:14px/1.6 -apple-system,BlinkMacSystemFont,"Microsoft YaHei",sans-serif;background:#f7f9fc;color:#24324a;margin:0}}main{{max-width:1450px;margin:auto;padding:30px 22px}}h1{{margin:0}}.note{{background:#fff4d8;border:1px solid #efd28d;border-radius:9px;padding:12px;margin:15px 0}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f1}}th,td{{padding:10px;border-bottom:1px solid #edf0f5;text-align:left;vertical-align:top}}th{{background:#eef3fa}}small{{color:#78869a}}</style><main><h1>薄样本指标人工口径复核包</h1><p>2025研究预排名 · 75项诊断任务 · 清洁能源强度、SO2强度、替代水率</p><div class="note"><b>复核边界：</b>本包只用于判断公开文档是否存在同口径数据。不得降低最低人口20的门槛，不得把SOx当SO2，不得把生产量强行当营收分母，也不得把缺失自动记为零。</div><table><tr><th>指标与企业</th><th>诊断类别</th><th>页码</th><th>原文片段</th><th>复核动作</th></tr>{body}</table></main></html>''', encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
