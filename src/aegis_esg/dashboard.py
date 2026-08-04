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


def render_system_demo(data: dict) -> str:
    """Render the product-wide executive demo landing page."""
    overview = data["overview"]
    tiers = (data.get("review_tiers") or {}).get("summary", {}).get("tier_counts", {})
    freeze = data.get("resolution_freeze_audit") or {}
    cards = (("真实公司", overview["company_count"]), ("候选观测", overview["candidate_observation_count"]),
             ("候选组", overview["candidate_task_count"]), ("冲突待审", overview["conflict_count"]),
             ("自动政策组", tiers.get("auto_policy_eligible", "-")),
             ("正式冻结", "未就绪" if not freeze.get("freeze_ready") else "就绪"))
    card_html = "".join(f'<div class="card"><small>{html.escape(str(label))}</small><strong>{html.escape(str(value))}</strong></div>' for label, value in cards)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>aegisESP 系统演示总览</title><style>
:root{{--bg:#f4f7fb;--panel:#fff;--ink:#172b4d;--muted:#61708a;--accent:#1769aa;--line:#dbe4ef}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1240px;margin:auto;padding:38px 22px 70px}}h1{{font-size:34px;margin:0}}h2{{margin:0 0 12px}}.sub{{color:var(--muted);margin:6px 0 22px}}.notice{{background:#fff7e8;border:1px solid #f1d49c;border-radius:12px;padding:14px 18px;color:#704400;margin:18px 0}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0 24px}}.card,section,.step{{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:0 5px 18px #172b4d0a}}.card{{padding:16px}}.card small{{display:block;color:var(--muted)}}.card strong{{display:block;font-size:27px;color:var(--accent)}}section{{padding:22px;margin-top:18px}}.flow{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px}}.step{{padding:14px;min-height:105px}}.step b{{display:block;color:var(--accent);font-size:18px}}.step span{{color:var(--muted);font-size:14px}}.links{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}a{{display:block;color:var(--accent);text-decoration:none;border:1px solid var(--line);border-radius:9px;padding:11px 13px;background:#fbfdff}}a:hover{{border-color:var(--accent)}}.small{{color:var(--muted);font-size:14px}}</style></head><body><main><h1>aegisESP 系统演示总览</h1><p class="sub">真实公开数据 · 自动预排名 · 人工审核 · 正式发布门禁</p><div class="notice"><b>演示边界：</b>当前为612家公司研究/审核阶段，正式六道门禁尚未完成。这里展示完整评价系统如何工作，不是正式榜单。</div><div class="cards">{card_html}</div>
<section><h2>系统生产链</h2><div class="flow"><div class="step"><b>1. 数据源</b><span>交易所、年报、ESG报告、来源Hash</span></div><div class="step"><b>2. 证据抽取</b><span>页码、年份、单位、主体和口径约束</span></div><div class="step"><b>3. 候选决策</b><span>自动确认、冲突识别、缺口队列</span></div><div class="step"><b>4. 自动预排名</b><span>指标评分、敏感性、可信等级</span></div><div class="step"><b>5. 风险审核</b><span>单审、双审、仲裁和签名留痕</span></div><div class="step"><b>6. 正式发布</b><span>固定算法、冻结Hash、双签授权</span></div></div></section>
<section><h2>现场操作入口</h2><div class="links"><a href="/demo/review-workbench">进入审核工作台（真实任务队列）</a><a href="/demo/company/600236.SH">打开企业决策详情（证据→计算→结论）</a><a href="/demo/ranking">真实研究预排名</a><a href="/demo/sensitivity">缺失策略敏感性</a><a href="/demo/metadata">算法与输入Hash</a><a href="/demo/methodology">80项方法论指标</a><a href="/dashboard">覆盖、冲突与审核分层</a><a href="/demo/readiness">正式发布门禁</a></div></section><section><h2>现场决策路径</h2><p><b>先看待办：</b>进入审核工作台选择高影响任务；<b>再看企业：</b>打开企业详情追溯证据、指标计算和缺失项；<b>最后做结论：</b>通过敏感性与冻结门禁判断能否进入正式发布。</p><p class="small">正式算法与自动预排名算法隔离；缺失不静默等于零；演示操作只生成模拟决策，不写入正式签名。</p></section></main></body></html>'''


def render_system_menu(data: dict) -> str:
    overview = data["overview"]
    freeze = data.get("resolution_freeze_audit") or {}
    items = [("01", "排名中心", "一键生成研究预排名，查看覆盖率、缺失数据和发布状态", "/demo/ranking-center"),
             ("02", "企业排名", "查看完整数据链企业和企业决策详情", "/demo/complete-chain"),
             ("03", "数据底座", "确认原始PDF、本地文件和Hash是否完整", "/demo/data-readiness"),
             ("04", "审核工作台", "处理证据冲突、缺失数据和高影响任务", "/demo/review-workbench"),
             ("05", "评价方法论", "查看中文指标、E/S/G维度、权重和规则", "/demo/methodology"),
             ("06", "正式发布门禁", "检查主体、文档、审核、冻结和授权状态", "/demo/readiness")]
    cards = "".join(f'<a class="item" href="{url}"><b>{num}</b><h2>{title}</h2><p>{desc}</p><i>›</i></a>' for num,title,desc,url in items)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>aegisESP · 系统主菜单</title><style>body{{margin:0;background:#f4f7fb;color:#172b4d;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1160px;margin:auto;padding:48px 24px}}.head{{display:flex;justify-content:space-between;margin-bottom:34px}}.brand{{color:#1769aa;font-weight:700}}h1{{font-size:36px;margin:8px 0}}.sub{{color:#68778d;font-size:17px}}.state{{background:#fff8e8;border:1px solid #f0d49b;border-radius:10px;padding:12px 16px;color:#765000;text-align:right}}.state b{{display:block;font-size:19px}}.menu{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}}.item{{position:relative;background:white;border:1px solid #dfe7f0;border-radius:15px;padding:22px;text-decoration:none;color:#172b4d;box-shadow:0 5px 18px #172b4d0b}}.item:hover{{border-color:#8bb3d2;transform:translateY(-2px)}}.item b{{display:inline-block;background:#e4f0f8;color:#1769aa;padding:4px 9px;border-radius:8px}}.item h2{{margin:16px 0 4px;font-size:20px}}.item p{{margin:0;color:#68778d}}.item i{{position:absolute;right:20px;top:21px;color:#1769aa;font-size:25px;font-style:normal}}.metrics{{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}}.metric{{background:white;border:1px solid #dfe7f0;border-radius:9px;padding:9px 15px}}.metric span{{display:block;color:#68778d;font-size:12px}}.metric strong{{font-size:20px;color:#1769aa}}</style></head><body><main><div class="head"><div><div class="brand">aegisESP · ESG科学决策系统</div><h1>系统主菜单</h1><p class="sub">从公开披露文档到 ESG 研究排名与正式发布审核</p></div><div class="state">当前工作域<strong>研究预排名</strong><small>正式发布：{"已就绪" if freeze.get("freeze_ready") else "待审核"}</small></div></div><div class="menu">{cards}</div><div class="metrics"><div class="metric"><span>研究企业</span><strong>{overview.get("company_count", "-")}</strong></div><div class="metric"><span>候选观测</span><strong>{overview.get("candidate_observation_count", "-")}</strong></div><div class="metric"><span>任务覆盖率</span><strong>{overview.get("coverage_rate", "-")}%</strong></div><div class="metric"><span>待审核冲突</span><strong>{overview.get("conflict_count", "-")}</strong></div></div></main></body></html>'''


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
