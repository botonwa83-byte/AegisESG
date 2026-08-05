#!/usr/bin/env python3
"""Export the read-only system demo to GitHub Pages-compatible static HTML."""
from __future__ import annotations

import re
import csv
import json
from pathlib import Path

from aegis_esg import api

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public-demo"


def save(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def static_page(response) -> str:
    return response.body.decode("utf-8")


def main() -> None:
    if OUT.exists():
        for path in sorted(OUT.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    save(OUT / "index.html", static_page(api.system_demo()))
    save(OUT / "ranking-center/index.html", static_page(api.demo_ranking_center()))
    save(OUT / "data-readiness/index.html", static_page(api.demo_data_readiness()))
    save(OUT / "review-workbench/index.html", static_page(api.demo_review_workbench()))
    save(OUT / "complete-chain/index.html", static_page(api.demo_complete_chain()))
    save(OUT / "readiness/index.html", static_page(api.demo_readiness()))
    save(OUT / "methodology/index.html", static_page(api.demo_methodology()))
    save(OUT / "sensitivity/index.html", static_page(api.demo_sensitivity()))
    save(OUT / "ranking/index.html", api.DEMO_RANKING_PATH.read_text(encoding="utf-8"))
    # Export curated complete-chain drill-downs from the latest ranking cohort.
    obs_candidates = sorted(
        (ROOT / "output/research/2025").glob("full_auto_observations_v*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not obs_candidates:
        raise SystemExit("missing research observations for company drill-down export")
    obs = list(csv.DictReader(obs_candidates[0].open(encoding="utf-8-sig", newline="")))
    counts = {}
    for row in obs:
        counts[row["company_code"]] = counts.get(row["company_code"], 0) + 1
    coverage = {
        row["stock_code"]: row
        for row in csv.DictReader(
            (ROOT / "output/audit/all_markets_document_coverage_embedded_esg_2025.csv").open(
                encoding="utf-8-sig", newline="",
            )
        )
    }
    ranking = json.loads((ROOT / "output/demo/real_data_demo_2025/ranking.json").read_text(encoding="utf-8"))
    # After authority-fill strips false qualitative zeros, dense firms often sit ~55-61.
    codes = [
        row["company_code"]
        for row in ranking
        if counts.get(row.get("company_code"), 0) >= 50
        and coverage.get(row.get("company_code"), {}).get("annual_status") == "collected"
    ][:12]
    for code in codes:
        save(OUT / "company" / code / "index.html", static_page(api.demo_company(code)))
    # Make navigation relative for Pages and remove server-only local PDF endpoints.
    for path in OUT.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        text = text.replace("aegisESP · ESG科学决策系统", "万绿信评 · ESG科学决策系统")
        if path == OUT / "index.html":
            text = text.replace("</main>", '<p style="color:#9cb1c8;font-size:13px;margin-top:28px">品牌参考：北京万家绿色信用评级有限公司（万绿信评） · <a href="https://www.greenrank.com.cn/" target="_blank" style="color:#63c9ff">访问官方站点</a></p></main>')
        prefix = "../" * (len(path.relative_to(OUT).parts) - 1)
        text = text.replace('href="/demo"', f'href="{prefix}"')
        replacements = {
            'href="/demo/ranking-center"': f'href="{prefix}ranking-center/"',
            'href="/demo/data-readiness"': f'href="{prefix}data-readiness/"',
            'href="/demo/complete-chain"': f'href="{prefix}complete-chain/"',
            'href="/demo/review-workbench"': f'href="{prefix}review-workbench/"',
            'href="/demo/readiness"': f'href="{prefix}readiness/"',
            'href="/demo/methodology"': f'href="{prefix}methodology/"',
            'href="/demo/ranking"': f'href="{prefix}ranking/"',
            'href="/demo/sensitivity"': f'href="{prefix}sensitivity/"',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = text.replace('method="post" action="/demo/generate-preview"', f'method="get" action="{prefix}ranking/"')
        text = re.sub(r'href="/demo/company/([^\"]+)"', rf'href="{prefix}company/\1/"', text)
        text = re.sub(r'href="/demo/source/[^\"]+"', 'href="https://www.sse.com.cn/"', text)
        save(path, text)
    save(OUT / "README.md", "# aegisESP 客户演示\n\n这是只读研究预排名演示，不是正式发布榜单。\n")
    print(f"generated {sum(1 for _ in OUT.rglob('*.html'))} html pages at {OUT}")


if __name__ == "__main__":
    main()
