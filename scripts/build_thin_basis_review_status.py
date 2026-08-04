#!/usr/bin/env python3
"""Render a read-only status page for the external thin-population review."""
from __future__ import annotations

import csv
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "output/audit/thin_basis_review_template_v1_2025.csv"
OUTPUT = ROOT / "output/audit/thin_basis_review_status_v1_2025.html"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(row.get('company_code', ''))}</td>"
            f"<td>{html.escape(row.get('company_name', ''))}</td>"
            f"<td>{html.escape(row.get('indicator_name', ''))}</td>"
            f"<td>{html.escape(row.get('located_page', '') or '待定位')}</td>"
            "<td><span class='pill'>待外部审核</span></td>"
            "</tr>"
        )
    page = f"""<!doctype html>
<html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>薄样本复核状态</title>
<style>
body{{margin:0;background:#f7f5ff;color:#25213b;font:15px/1.6 -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}}
main{{max-width:1100px;margin:40px auto;padding:0 24px}} h1{{margin-bottom:4px}} .sub{{color:#706b88}}
.notice{{margin:24px 0;padding:18px 20px;border-radius:18px;background:#fff0f5;border:1px solid #ffc6d9}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:20px 0}} .card{{background:#fff;border-radius:18px;padding:18px;box-shadow:0 8px 24px #43356d12}} .num{{font-size:30px;font-weight:700}}
table{{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border-radius:18px;overflow:hidden}} th,td{{padding:12px;text-align:left;border-bottom:1px solid #eeeaf8}} th{{background:#f0edff}} .pill{{padding:4px 9px;border-radius:999px;background:#fff0bc;color:#755900;font-size:12px}}
</style><main><h1>薄样本证据复核状态</h1><div class='sub'>2025报告期 · 只读工作台 · 不产生正式排名</div>
<div class='notice'><strong>当前状态：外部审核阻塞</strong><br>9条证据均需补全值、单位、分母、统计边界、审核人、时间和理由；完成签署前不得写入正式评分。</div>
<section class='grid'><div class='card'><div class='num'>{len(rows)}</div>待审核证据</div><div class='card'><div class='num'>0</div>已签署记录</div><div class='card'><div class='num'>否</div>正式评分授权</div></section>
<table><thead><tr><th>证券代码</th><th>企业</th><th>指标</th><th>页码</th><th>状态</th></tr></thead><tbody>{''.join(body)}</tbody></table>
</main></html>"""
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"{OUTPUT} rows={len(rows)} scoring_authorized=false")


if __name__ == "__main__":
    main()
