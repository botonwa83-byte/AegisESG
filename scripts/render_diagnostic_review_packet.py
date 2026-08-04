#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/data_gap_diagnostic_action_queue_v1_2025.csv"
OUTPUT = ROOT / "output/audit/data_gap_diagnostic_review_packet_v1_2025.html"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    counts = Counter(row["diagnostic_action"] for row in rows)
    rows.sort(key=lambda row: (int(row["batch_task_rank"]), row["company_code"]))
    body = "".join(
        f'<tr><td>{html.escape(row["batch_task_rank"])}</td><td><b>{html.escape(row["company_name"])}</b><br><small>{html.escape(row["company_code"])}</small></td>'
        f'<td>{html.escape(row["indicator_name"])}<br><code>{html.escape(row["indicator_code"])}</code></td><td>{html.escape(row["impact_score"])}</td>'
        f'<td>{html.escape(row["diagnostic_category"])}</td><td>{html.escape(row["action_instruction"])}</td><td>{html.escape(row["source_pages"] or "未标页")}</td>'
        f'<td>{html.escape(row["diagnostic_excerpt"][:420] or "未发现可用原文")}</td></tr>' for row in rows
    )
    OUTPUT.write_text(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>高影响数据缺口诊断任务包</title><style>body{{font:14px/1.6 -apple-system,BlinkMacSystemFont,"Microsoft YaHei",sans-serif;background:#f5f7fb;color:#24324a;margin:0}}main{{max-width:1500px;margin:auto;padding:30px 22px}}h1{{margin:0 0 5px}}.note{{background:#fff7df;border:1px solid #efd291;border-radius:9px;padding:12px;margin:15px 0}}.stats{{display:flex;gap:10px;flex-wrap:wrap}}.stat{{background:#fff;border:1px solid #e3e9f2;border-radius:9px;padding:10px 15px}}.stat b{{display:block;font-size:20px;color:#4e79ff}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e9f2}}th,td{{padding:9px;border-bottom:1px solid #edf0f5;text-align:left;vertical-align:top}}th{{background:#eef3fa;white-space:nowrap}}code{{color:#4e79ff}}small{{color:#78869a}}</style><main><h1>高影响数据缺口诊断任务包</h1><p>批次：2025研究预排名 · 250项任务 · 仅用于补证和诊断</p><div class="note"><b>使用规则：</b>先查看页码和原文，再判断是否可闭合指标口径；不得把诊断结果直接写入正式评分。所有任务当前 scoring_authorized=false。</div><div class="stats"><div class="stat">检查原始表格<b>{counts["inspect_source_table"]}</b></div><div class="stat">人工口径核验<b>{counts["manual_basis_review"]}</b></div><div class="stat">保留缺失继续扫描<b>{counts["retain_missing_pending_scan"]}</b></div></div><table><tr><th>批次序号</th><th>企业</th><th>指标</th><th>影响分</th><th>诊断类别</th><th>下一动作</th><th>页码</th><th>原文片段</th></tr>{body}</table></main></html>''', encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
