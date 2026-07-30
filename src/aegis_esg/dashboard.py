from __future__ import annotations

import csv
import html
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

from .methodology import Methodology
from .review import REVIEW_COLUMNS


def load_progress_dashboard(
    summary_path: str | Path,
    tasks_path: str | Path,
    review_path: str | Path,
    candidates_path: str | Path,
    methodology: Methodology,
    review_tiers_summary_path: str | Path | None = None,
    review_tiers_path: str | Path | None = None,
    resolution_freeze_audit_path: str | Path | None = None,
) -> dict:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    tasks = _read_csv(tasks_path)
    reviews = _read_csv(review_path)
    candidates = _read_csv(candidates_path)
    if len(tasks) != summary["task_count"]:
        raise ValueError("候选覆盖任务数与摘要不一致")
    if len(candidates) != summary["candidate_observation_count"]:
        raise ValueError("候选观测数与摘要不一致")

    quantitative = {item.code: item for item in methodology.quantitative}
    company_count = summary["company_count"]
    population = summary["indicator_population"]
    indicators = []
    for item in methodology.quantitative:
        covered = int(population.get(item.code, 0))
        indicators.append({
            "code": item.code,
            "name": item.name,
            "dimension": item.dimension,
            "key_indicator": item.key_indicator,
            "covered_companies": covered,
            "missing_companies": company_count - covered,
            "coverage_rate": round(covered / company_count * 100, 2),
        })
    indicators.sort(key=lambda row: (not row["key_indicator"], row["covered_companies"], row["code"]))

    dimension_tasks: dict[str, Counter] = defaultdict(Counter)
    for task in tasks:
        dimension = task["dimension"]
        dimension_tasks[dimension]["total"] += 1
        dimension_tasks[dimension]["covered" if int(task["candidate_count"]) else "missing"] += 1
    dimensions = []
    for dimension in ("E", "S", "G"):
        counts = dimension_tasks[dimension]
        dimensions.append({
            "dimension": dimension,
            "total": counts["total"],
            "covered": counts["covered"],
            "missing": counts["missing"],
            "coverage_rate": round(counts["covered"] / counts["total"] * 100, 2) if counts["total"] else 0,
        })

    conflict_keys = {
        (row["company_code"], int(row["report_year"]), row["indicator_code"])
        for row in reviews if row["review_reason"] == "conflicting_candidates"
    }
    candidate_groups: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in candidates:
        key = (row["company_code"], int(row["report_year"]), row["indicator_code"])
        if key in conflict_keys:
            candidate_groups[key].append({
                "value": row["value"], "source_page": row["source_page"],
                "source_file": row["source_file"], "source_url": row["source_url"],
                "evidence_text": row["evidence_text"], "confidence": row["confidence"],
            })
    conflicts = []
    review_by_key = {
        (row["company_code"], int(row["report_year"]), row["indicator_code"]): row
        for row in reviews
    }
    for key in sorted(conflict_keys):
        review = review_by_key[key]
        indicator = quantitative[key[2]]
        conflicts.append({
            "company_code": key[0], "company_name": review["company_name"],
            "report_year": key[1], "indicator_code": key[2], "indicator_name": indicator.name,
            "distinct_values": review["distinct_values"], "source_pages": review["source_pages"],
            "candidates": candidate_groups[key],
        })

    key_total = company_count * sum(item.key_indicator for item in methodology.quantitative)
    key_missing = summary["key_indicator_missing_task_count"]
    review_tiers = None
    if review_tiers_summary_path is not None or review_tiers_path is not None:
        if review_tiers_summary_path is None or review_tiers_path is None:
            raise ValueError("审核分层摘要和明细必须同时提供")
        tier_summary = json.loads(Path(review_tiers_summary_path).read_text(encoding="utf-8"))
        tier_rows = _read_csv(review_tiers_path)
        if len(tier_rows) != tier_summary["candidate_group_count"]:
            raise ValueError("审核分层明细数与摘要不一致")
        actual_counts = Counter(row["tier"] for row in tier_rows)
        if any(actual_counts[name] != count for name, count in tier_summary["tier_counts"].items()):
            raise ValueError("审核分层类别计数与摘要不一致")
        review_tiers = {
            "summary": tier_summary,
            "manual_items": [row for row in tier_rows if row["tier"] != "auto_policy_eligible"],
        }
    freeze_audit = None
    if resolution_freeze_audit_path is not None:
        freeze_audit = json.loads(Path(resolution_freeze_audit_path).read_text(encoding="utf-8"))
        if freeze_audit.get("candidate_group_count") != summary["candidate_task_count"]:
            raise ValueError("冻结审计候选组数与覆盖摘要不一致")
        if freeze_audit.get("candidate_observation_count") != len(candidates):
            raise ValueError("冻结审计候选观测数与覆盖摘要不一致")
        if not freeze_audit.get("valid"):
            raise ValueError("冻结审计未通过")
    return {
        "overview": {
            **{key: summary[key] for key in (
                "company_count", "quantitative_indicator_count", "task_count",
                "candidate_task_count", "missing_task_count", "candidate_observation_count",
                "key_indicator_missing_task_count",
            )},
            "coverage_rate": round(summary["candidate_task_count"] / summary["task_count"] * 100, 2),
            "key_indicator_task_count": key_total,
            "key_indicator_covered_task_count": key_total - key_missing,
            "key_indicator_coverage_rate": round((key_total - key_missing) / key_total * 100, 2),
            "conflict_count": len(conflicts),
            "applicable": summary["applicable"],
        },
        "dimensions": dimensions,
        "indicators": indicators,
        "priority_gaps": [row for row in indicators if row["key_indicator"] and row["missing_companies"]][:10],
        "conflicts": conflicts,
        "review_tiers": review_tiers,
        "resolution_freeze_audit": freeze_audit,
    }


def render_progress_dashboard(data: dict) -> str:
    overview = data["overview"]
    tier_summary = (data.get("review_tiers") or {}).get("summary", {})
    tier_counts = tier_summary.get("tier_counts", {})
    freeze_audit = data.get("resolution_freeze_audit") or {}
    cards = (
        ("公司", overview["company_count"]),
        ("候选观测", overview["candidate_observation_count"]),
        ("任务覆盖", f'{overview["candidate_task_count"]}/{overview["task_count"]}'),
        ("总体覆盖率", f'{overview["coverage_rate"]}%'),
        ("关键指标覆盖", f'{overview["key_indicator_covered_task_count"]}/{overview["key_indicator_task_count"]}'),
        ("待复核冲突", overview["conflict_count"]),
        ("v4可自动确认", tier_counts.get("auto_policy_eligible", "-")),
        ("人工审核组", sum(value for key, value in tier_counts.items() if key != "auto_policy_eligible") if tier_counts else "-"),
        ("正式冻结", "就绪" if freeze_audit.get("freeze_ready") else "待人工审核" if freeze_audit else "-"),
    )
    card_html = "".join(f'<div class="card"><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>' for label, value in cards)
    dimension_html = "".join(
        f'<tr><td>{row["dimension"]}</td><td>{row["covered"]}</td><td>{row["missing"]}</td><td>{row["coverage_rate"]}%</td></tr>'
        for row in data["dimensions"]
    )
    indicator_html = "".join(
        f'<tr class="indicator-row" data-search="{html.escape((row["code"] + " " + row["name"] + " " + row["dimension"]).lower())}"><td><code>{html.escape(row["code"])}</code></td><td>{html.escape(row["name"])}</td>'
        f'<td>{"是" if row["key_indicator"] else "否"}</td><td>{row["covered_companies"]}</td>'
        f'<td>{row["missing_companies"]}</td><td>{row["coverage_rate"]}%</td></tr>'
        for row in data["indicators"]
    )
    priority_html = "".join(
        f'<tr><td>{index}</td><td><code>{html.escape(row["code"])}</code></td>'
        f'<td>{html.escape(row["name"])}</td><td>{row["covered_companies"]}</td>'
        f'<td>{row["missing_companies"]}</td><td>扩展抽取规则</td></tr>'
        for index, row in enumerate(data["priority_gaps"], 1)
    )
    conflict_html = "".join(
        f'<article><h3>{html.escape(item["company_code"])} · {html.escape(item["indicator_name"])}</h3>'
        f'<p>候选值：{html.escape(item["distinct_values"])}　页码：{html.escape(item["source_pages"])}</p>'
        + "".join(
            f'<blockquote><b>{html.escape(candidate["value"])}</b>（第{html.escape(candidate["source_page"])}页，'
            f'置信度 {html.escape(candidate["confidence"])})<br>{html.escape(candidate["evidence_text"])}</blockquote>'
            for candidate in item["candidates"]
        ) + '</article>' for item in data["conflicts"]
    ) or "<p>当前没有冲突候选。</p>"
    tier_html = "".join(
        f'<tr><td>{html.escape(item["tier"])}</td><td>{html.escape(item["company_code"])}</td>'
        f'<td><code>{html.escape(item["indicator_code"])}</code></td><td>{html.escape(item["distinct_values"])}</td>'
        f'<td>{html.escape(item["next_action"])}</td></tr>'
        for item in (data.get("review_tiers") or {}).get("manual_items", [])
    ) or '<tr><td colspan="5">未加载审核分层产物。</td></tr>'
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AegisESP 开发进度</title><style>
:root{{--bg:#f3f6f4;--panel:#fff;--ink:#19332a;--muted:#66776f;--accent:#087f5b;--line:#dce5e0}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1200px;margin:auto;padding:32px 20px 64px}}h1{{margin:0}}.sub{{color:var(--muted);margin:4px 0 24px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.card,section{{background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 5px 18px #173d2b0a}}.card{{padding:16px}}.card span{{display:block;color:var(--muted)}}.card strong{{font-size:25px;color:var(--accent)}}
section{{margin-top:18px;padding:20px;overflow:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}th{{color:var(--muted)}}code{{color:#096b50}}article{{border-top:1px solid var(--line);padding:12px 0}}blockquote{{margin:8px 0;padding:10px 14px;background:#f5faf7;border-left:3px solid var(--accent)}}input{{width:min(420px,100%);padding:10px 12px;border:1px solid var(--line);border-radius:8px;font:inherit}}
</style></head><body><main><h1>AegisESP 开发进度</h1><p class="sub">港股定量候选覆盖 · 只读审计看板 · 候选数据不等于正式评分</p>
<div class="cards">{card_html}</div><section><h2>维度覆盖</h2><table><thead><tr><th>维度</th><th>已有候选</th><th>缺失</th><th>覆盖率</th></tr></thead><tbody>{dimension_html}</tbody></table></section>
<section><h2>审核分层</h2><table><thead><tr><th>分层</th><th>公司</th><th>指标</th><th>候选值</th><th>下一步</th></tr></thead><tbody>{tier_html}</tbody></table></section>
<section><h2>下一批关键缺口</h2><table><thead><tr><th>优先级</th><th>编码</th><th>指标</th><th>覆盖公司</th><th>缺失公司</th><th>下一步</th></tr></thead><tbody>{priority_html}</tbody></table></section>
<section><h2>37项定量指标</h2><p><input id="indicator-search" placeholder="搜索指标名称、编码或E/S/G维度"></p><table><thead><tr><th>编码</th><th>指标</th><th>关键</th><th>覆盖公司</th><th>缺失公司</th><th>覆盖率</th></tr></thead><tbody>{indicator_html}</tbody></table></section>
<section><h2>冲突候选</h2><p><a href="/api/v1/review-template">下载待签名复核模板 CSV</a></p>{conflict_html}</section></main><script>
const search=document.getElementById('indicator-search');search.addEventListener('input',()=>{{const q=search.value.trim().toLowerCase();document.querySelectorAll('.indicator-row').forEach(row=>row.hidden=q&&!row.dataset.search.includes(q));}});
</script></body></html>"""


def render_conflict_review_template(data: dict) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in data["conflicts"]:
        writer.writerow({
            "company_code": item["company_code"], "company_name": item["company_name"],
            "report_year": item["report_year"], "indicator_code": item["indicator_code"],
            "candidate_count": len(item["candidates"]), "distinct_values": item["distinct_values"],
            "source_pages": item["source_pages"], "recommended_value": "",
            "review_reason": "conflicting_candidates", "action": "", "selected_value": "",
            "reviewer": "", "reviewed_at": "", "note": "",
        })
    return "\ufeff" + stream.getvalue()


def _read_csv(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))
