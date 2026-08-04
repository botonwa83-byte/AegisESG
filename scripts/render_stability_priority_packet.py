#!/usr/bin/env python3
"""Render the stability remediation queue as a human-readable task packet."""
from __future__ import annotations

import csv
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/research_stability_priority_queue_v1_2025.csv"
OUTPUT = ROOT / "output/audit/research_stability_priority_packet_v1_2025.html"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))[:50]
    body = "".join(
        f"<tr><td>{i}</td><td>{html.escape(row.get('company_code',''))}<br><small>{html.escape(row.get('company_name',''))}</small></td>"
        f"<td>{html.escape(row.get('best_rank','-'))} → {html.escape(row.get('worst_rank','-'))}</td>"
        f"<td><b>{html.escape(row.get('rank_span','-'))}</b></td><td>{html.escape(row.get('disclosure_rate','-'))}</td>"
        f"<td>{html.escape(row.get('stability_priority_score','-'))}</td><td>{html.escape(row.get('next_action',''))}</td></tr>"
        for i, row in enumerate(rows, 1)
    )
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>排名稳定性补证任务包</title>
<style>body{{margin:0;background:#f7f5ff;color:#28243e;font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}main{{max-width:1180px;margin:36px auto;padding:0 22px}}h1{{margin-bottom:4px}}.sub{{color:#716c87}}.notice{{margin:20px 0;padding:16px 18px;background:#fff0f5;border:1px solid #ffc6d9;border-radius:16px}}table{{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 8px 24px #43356d12}}th,td{{padding:11px;border-bottom:1px solid #eeeaf8;text-align:left;vertical-align:top}}th{{background:#f0edff;color:#5c5675}}small{{color:#77718c}}</style><main><h1>排名稳定性优先补证任务包</h1><div class="sub">2025研究预排名 · 前50家高优先级企业 · 只用于数据改进</div><div class="notice"><b>使用规则：</b>优先核验原始PDF、指标口径和缺失策略；任务完成后重新生成研究快照。该队列不授权正式评分，不代表正式排名结论。</div><table><tr><th>#</th><th>企业</th><th>最好→最差名次</th><th>名次跨度</th><th>披露率</th><th>优先级</th><th>下一动作</th></tr>{body}</table></main></html>'''
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"{OUTPUT} rows={len(rows)} formal_publishable=false")


if __name__ == "__main__":
    main()
