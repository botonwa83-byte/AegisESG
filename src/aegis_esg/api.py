from __future__ import annotations

import json
import html
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .dashboard import load_progress_dashboard, render_conflict_review_template, render_progress_dashboard, render_system_demo, render_system_menu
from .methodology import load_methodology
from .models import Observation, ValueStatus
from .repository import SQLiteRepository
from .scoring import ScoringEngine


ROOT = Path(__file__).resolve().parents[2]
METHODOLOGY_PATH = Path(os.getenv("AEGIS_METHODOLOGY", ROOT / "data/methodologies/energy_esg_2025.json"))
DB_PATH = Path(os.getenv("AEGIS_DB", ROOT / "var/aegis.db"))
PROGRESS_SUMMARY_PATH = Path(os.getenv(
    "AEGIS_PROGRESS_SUMMARY", ROOT / "output/audit/hkex_quantitative_candidate_tasks_summary_2026-07-29.json",
))
PROGRESS_TASKS_PATH = Path(os.getenv(
    "AEGIS_PROGRESS_TASKS", ROOT / "output/audit/hkex_quantitative_candidate_tasks_2026-07-29.csv",
))
REVIEW_SUMMARY_PATH = Path(os.getenv(
    "AEGIS_REVIEW_SUMMARY", ROOT / "data/review/hkex_indicator_candidates_review_2026-07-29.csv",
))
CANDIDATES_PATH = Path(os.getenv(
    "AEGIS_CANDIDATES", ROOT / "data/review/hkex_indicator_candidates_2026-07-29.csv",
))
REVIEW_TIERS_SUMMARY_PATH = Path(os.getenv(
    "AEGIS_REVIEW_TIERS_SUMMARY", ROOT / "output/audit/hkex_candidate_review_tiers_summary_2026-07-29.json",
))
REVIEW_TIERS_PATH = Path(os.getenv(
    "AEGIS_REVIEW_TIERS", ROOT / "output/audit/hkex_candidate_review_tiers_2026-07-29.csv",
))
RESOLUTION_FREEZE_AUDIT_PATH = Path(os.getenv(
    "AEGIS_RESOLUTION_FREEZE_AUDIT",
    ROOT / "output/audit/hkex_resolution_preview_freeze_audit_2026-07-29.json",
))
DEMO_RANKING_PATH = Path(os.getenv("AEGIS_DEMO_RANKING_PATH", ROOT / "output/demo/real_data_demo_2025/ranking.html"))
DEMO_SENSITIVITY_PATH = Path(os.getenv("AEGIS_DEMO_SENSITIVITY_PATH", ROOT / "output/demo/real_data_demo_2025/ranking_sensitivity.json"))
DEMO_METADATA_PATH = Path(os.getenv("AEGIS_DEMO_METADATA_PATH", ROOT / "output/demo/real_data_demo_2025/ranking_metadata.json"))
DEMO_READINESS_PATH = Path(os.getenv("AEGIS_DEMO_READINESS_PATH", ROOT / "output/demo/real_data_demo_2025/external_readiness_2025.json"))
DEMO_IMPACT_REVIEW_PATH = Path(os.getenv("AEGIS_DEMO_IMPACT_REVIEW_PATH", ROOT / "output/audit/all_markets_rank_impact_review_2025.csv"))
methodology = load_methodology(METHODOLOGY_PATH)
app = FastAPI(title="中国能源上市公司ESG评价系统", version="0.1.0")


def _indicator_label(code: str) -> str:
    item = methodology.by_code.get(code)
    return f"{item.name}（{code}）" if item else code


def _status_label(status: str) -> str:
    return {"confirmed": "已确认", "missing": "待补充", "pending": "待审核", "unresolved": "未解决"}.get(status, status)


def _document_index_rows() -> list[dict]:
    """Use the complete all-market index; fall back only for older pilot installs."""
    paths = (ROOT / "data/raw/all_markets_document_index.csv", ROOT / "data/raw/document_index.csv")
    for path in paths:
        if path.is_file():
            import csv
            with path.open(encoding="utf-8-sig", newline="") as stream:
                return list(csv.DictReader(stream))
    return []


class ObservationIn(BaseModel):
    company_code: str
    company_name: str
    report_year: int = Field(ge=2000, le=2100)
    indicator_code: str
    value: Optional[float] = None
    status: ValueStatus = ValueStatus.CONFIRMED
    source_url: str = ""
    source_file: str = ""
    source_page: Optional[int] = None
    evidence_text: str = ""
    confidence: float = Field(default=1, ge=0, le=1)


def repository() -> SQLiteRepository:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    repo = SQLiteRepository(DB_PATH)
    repo.initialize()
    return repo


def progress_data() -> dict:
    try:
        return load_progress_dashboard(
            PROGRESS_SUMMARY_PATH, PROGRESS_TASKS_PATH, REVIEW_SUMMARY_PATH,
            CANDIDATES_PATH, methodology, REVIEW_TIERS_SUMMARY_PATH, REVIEW_TIERS_PATH,
            RESOLUTION_FREEZE_AUDIT_PATH,
        )
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(503, f"进度产物不可用: {error}") from error


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    return HTMLResponse(render_progress_dashboard(progress_data()))


@app.get("/demo", response_class=HTMLResponse, include_in_schema=False)
def system_demo() -> HTMLResponse:
    page = render_system_menu(progress_data())
    # Keep raw JSON endpoints for integrations, but expose only human-readable pages from the executive demo.
    for raw, friendly in {
        "/api/v1/methodology": "/demo/methodology",
        "/api/v1/progress": "/dashboard",
        "/api/v1/review-conflicts": "/dashboard",
        "/api/v1/review-tiers": "/dashboard",
        "/api/v1/resolution-freeze-audit": "/demo/readiness",
    }.items():
        page = page.replace(raw, friendly)
    return HTMLResponse(page)


@app.get("/demo/ranking-center", response_class=HTMLResponse, include_in_schema=False)
def demo_ranking_center(generated: int = Query(0, ge=0, le=1)) -> HTMLResponse:
    """Single entry for preview ranking generation and data completeness warnings."""
    if not DEMO_RANKING_PATH.is_file() or not DEMO_METADATA_PATH.is_file():
        raise HTTPException(404, "研究预排名产物不存在")
    ranking = json.loads(DEMO_RANKING_PATH.with_name("ranking.json").read_text(encoding="utf-8")) if DEMO_RANKING_PATH.with_name("ranking.json").is_file() else []
    metadata = json.loads(DEMO_METADATA_PATH.read_text(encoding="utf-8"))
    try:
        progress = progress_data()
        overview = progress["overview"]
    except HTTPException:
        progress = {}
        overview = {}
    coverage = overview.get("coverage_rate", metadata.get("company_count", "-"))
    missing = overview.get("missing_task_count", "-")
    conflicts = overview.get("conflict_count", "-")
    formal = "可发布" if (progress.get("resolution_freeze_audit") or {}).get("freeze_ready") else "不可发布"
    generated_note = '<p class="success">已读取当前研究输入并生成预排名结果，可进入结果页查看。</p>' if generated else ''
    body = f'''<div class="eyebrow">排名中心</div><h1>一键生成排名</h1><p class="lead">先生成研究预排名，再根据数据完整度决定是否进入人工审核和正式发布。</p>
<div class="steps"><span class="active">① 读取研究数据</span><span>② 生成预排名</span><span>③ 检查缺失</span><span>④ 申请正式审核</span></div>{generated_note}
<section class="action-panel"><h2>研究预排名</h2><p>系统使用当前版本化研究输入、指标方法论和缺失策略生成可复现的预排名。此操作不写入正式观测、不产生签名。</p><form method="post" action="/demo/generate-preview"><button class="primary" type="submit">一键生成 / 刷新研究预排名</button></form><a class="result-link" href="/demo/ranking">查看研究预排名结果 →</a></section>
<h2>数据完整度检查</h2><div class="cards"><div><b>任务覆盖率</b><strong>{coverage}%</strong></div><div><b>待补数据任务</b><strong>{missing}</strong></div><div><b>证据冲突</b><strong>{conflicts}</strong></div><div><b>正式发布状态</b><strong class="warn">{formal}</strong></div></div>
<p class="status"><b>结果解释：</b>数据不完整时，系统仍可生成研究预排名，但会保留缺失项、显示覆盖率并标记不确定性；只有完成审核、签名和冻结门禁后，才允许形成正式排名。</p>
<div class="links"><a href="/demo/complete-chain">查看完整数据链企业</a><a href="/demo/review-workbench">处理高影响缺失与冲突</a><a href="/demo/sensitivity">查看缺失策略敏感性</a><a href="/demo/readiness">查看正式发布门禁</a></div>'''
    return HTMLResponse(_demo_document("排名中心", body))


@app.post("/demo/generate-preview", include_in_schema=False)
def generate_preview() -> RedirectResponse:
    """Demo-safe one-click action: refreshes the view over the versioned research artifact."""
    if not DEMO_RANKING_PATH.is_file():
        raise HTTPException(404, "研究预排名输入不存在")
    return RedirectResponse("/demo/ranking-center?generated=1", status_code=303)


@app.get("/demo/source/{stock_code}/{document_type}", include_in_schema=False)
def demo_source_document(stock_code: str, document_type: str) -> FileResponse:
    """Serve a verified local source document for the demo, never an arbitrary path."""
    if document_type not in {"annual_report", "esg_report"}:
        raise HTTPException(404, "不支持的文档类型")
    index_rows = _document_index_rows()
    if not index_rows:
        raise HTTPException(404, "本地文档索引不存在")
    row = next((item for item in index_rows if item.get("company_code") == stock_code and item.get("document_type") == document_type), None)
    if not row:
        raise HTTPException(404, "未找到该企业的本地文档")
    path = (ROOT / row["local_path"]).resolve()
    raw_root = (ROOT / "data/raw").resolve()
    if raw_root not in path.parents or not path.is_file():
        raise HTTPException(404, "本地文档文件不存在")
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{path.name}"'})


@app.get("/demo/data-readiness", response_class=HTMLResponse, include_in_schema=False)
def demo_data_readiness() -> HTMLResponse:
    """Expose the local document layer before users trust a ranking."""
    rows = _document_index_rows()
    if not rows:
        raise HTTPException(404, "本地文档索引不存在")
    from collections import Counter
    by_type = Counter(row.get("document_type") for row in rows)
    exists = sum(1 for row in rows if (ROOT / row.get("local_path", "")).is_file())
    hash_registered = sum(1 for row in rows if row.get("sha256"))
    companies = len({row.get("company_code") for row in rows})
    annual = by_type.get("annual_report", 0)
    esg = by_type.get("esg_report", 0)
    missing = len(rows) - exists
    body = f'''<div class="eyebrow">数据底座</div><h1>原始文档与证据来源</h1><p class="lead">排名之前先确认数据从哪里来、文件是否在本地、能否回到原始 PDF。</p><div class="steps"><span class="active">① 文档发现</span><span class="active">② 本地下载</span><span class="active">③ Hash索引</span><span>④ 证据抽取</span><span>⑤ 评分排名</span></div><div class="cards"><div><b>索引文档</b><strong>{len(rows)}</strong></div><div><b>覆盖企业</b><strong>{companies}</strong></div><div><b>年报 PDF</b><strong>{annual}</strong></div><div><b>ESG PDF</b><strong>{esg}</strong></div><div><b>本地文件</b><strong>{exists}/{len(rows)}</strong></div><div><b>已登记Hash</b><strong>{hash_registered}/{len(rows)}</strong></div></div><p class="status"><b>{"本地文档层完整" if missing == 0 else f"仍有 {missing} 份文档未落地"}</b>　索引来源：全市场文档索引。外部链接不可访问时，优先使用企业详情中的本地 PDF。</p><h2>来源使用规则</h2><div class="action-panel"><p>每个排名指标必须尽量连接到公司、报告期、PDF文件、页码、证据原文和文件Hash。外部交易所 URL 只作为原始发布地址；本地文件是演示和审计的稳定入口。</p><a class="result-link" href="/demo/complete-chain">进入完整数据链企业排名 →</a><a class="result-link" href="/demo/ranking-center">进入排名中心 →</a></div>'''
    return HTMLResponse(_demo_document("原始文档与证据来源", body))


@app.get("/demo/ranking", response_class=HTMLResponse, include_in_schema=False)
def demo_ranking() -> FileResponse:
    if not DEMO_RANKING_PATH.is_file():
        raise HTTPException(404, "演示排名文件不存在")
    return FileResponse(DEMO_RANKING_PATH, media_type="text/html")


@app.get("/demo/sensitivity", include_in_schema=False)
def demo_sensitivity() -> HTMLResponse:
    if not DEMO_SENSITIVITY_PATH.is_file():
        raise HTTPException(404, "演示敏感性文件不存在")
    data = json.loads(DEMO_SENSITIVITY_PATH.read_text(encoding="utf-8"))
    comparisons = data.get("strategy_comparisons", [])
    rows = "".join(
        f'<tr><td>{html.escape(str(item.get("left", "")))}</td><td>{html.escape(str(item.get("right", "")))}</td>'
        f'<td>{item.get("spearman_rank_correlation", "-")}</td><td>{item.get("top_50_overlap_rate", "-")}</td>'
        f'<td>{item.get("top_200_overlap_rate", "-")}</td></tr>' for item in comparisons
    )
    body = f'<h1>缺失策略敏感性</h1><p>共{data.get("company_count", "-")}家公司；不稳定公司{data.get("unstable_company_count", "-")}家；最大名次跨度{data.get("max_rank_span", "-")}。</p><table><tr><th>策略A</th><th>策略B</th><th>相关性</th><th>Top50重合</th><th>Top200重合</th></tr>{rows}</table>'
    return HTMLResponse(_demo_document("缺失策略敏感性", body))


@app.get("/demo/metadata", include_in_schema=False)
def demo_metadata() -> HTMLResponse:
    if not DEMO_METADATA_PATH.is_file():
        raise HTTPException(404, "演示元数据文件不存在")
    data = json.loads(DEMO_METADATA_PATH.read_text(encoding="utf-8"))
    rows = "".join(f'<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>' for key, value in data.items())
    return HTMLResponse(_demo_document("算法与输入元数据", f'<h1>算法与输入元数据</h1><table>{rows}</table>'))


@app.get("/demo/readiness", include_in_schema=False)
def demo_readiness() -> HTMLResponse:
    if not DEMO_READINESS_PATH.is_file():
        raise HTTPException(404, "演示外部输入状态文件不存在")
    data = json.loads(DEMO_READINESS_PATH.read_text(encoding="utf-8"))
    rows = "".join(f'<tr><td>{html.escape(str(key))}</td><td>{"已就绪" if item.get("ready") else "待外部输入"}</td><td>{html.escape(str(item.get("evidence", "")))}</td><td>{html.escape(str(item.get("required_external_action", "")))}</td></tr>' for key, item in data.get("checks", {}).items())
    body = f'<h1>正式发布门禁与外部输入</h1><p class="status">当前状态：{html.escape(str(data.get("status", "")))}</p><table><tr><th>检查项</th><th>状态</th><th>证据</th><th>下一动作</th></tr>{rows}</table>'
    return HTMLResponse(_demo_document("正式发布门禁", body))


@app.get("/demo/methodology", response_class=HTMLResponse, include_in_schema=False)
def demo_methodology() -> HTMLResponse:
    data = get_methodology()
    rows = "".join(f'<tr><td>{html.escape(str(item.get("code", "")))}</td><td>{html.escape(str(item.get("name", "")))}</td><td>{html.escape(str(item.get("dimension", "")))}</td><td>{item.get("weight", "-")}</td></tr>' for item in data["indicators"])
    return HTMLResponse(_demo_document("评价方法论", f'<h1>评价方法论</h1><p>版本：{html.escape(data["version"])}；共{len(data["indicators"])}项指标；定量权重{data["quantitative_ratio"]}%、定性权重{data["qualitative_ratio"]}%。</p><table><tr><th>编码</th><th>指标</th><th>维度</th><th>权重</th></tr>{rows}</table>'))


@app.get("/demo/review-workbench", response_class=HTMLResponse, include_in_schema=False)
def demo_review_workbench() -> HTMLResponse:
    """Human-review queue presented as actionable decisions, without exposing raw CSV."""
    if not DEMO_IMPACT_REVIEW_PATH.is_file():
        raise HTTPException(404, "审核影响产物不存在")
    import csv
    with DEMO_IMPACT_REVIEW_PATH.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows.sort(key=lambda item: float(item.get("impact_score", 0) or 0), reverse=True)
    body_rows = "".join(
        f'<tr><td>{i}</td><td><a href="/demo/company/{html.escape(row.get("company_code", ""))}">{html.escape(row.get("company_code", ""))}</a><br><small>{html.escape(row.get("company_name", ""))}</small></td>'
        f'<td>{html.escape(_indicator_label(row.get("indicator_code", "")))}</td><td>{html.escape({"manual_signature_required": "必须人工签名", "consistent_multi_review": "多来源抽查", "single_candidate_review": "单候选抽查"}.get(row.get("tier", ""), "自动策略"))}</td>'
        f'<td>{html.escape(row.get("current_rank", "-"))} → {html.escape(row.get("best_rank", "-"))}/{html.escape(row.get("worst_rank", "-"))}</td>'
        f'<td><b>{html.escape(row.get("impact_score", "-"))}</b></td><td>{html.escape(row.get("next_action", ""))}</td>'
        f'<td><button disabled>模拟审核</button></td></tr>' for i, row in enumerate(rows[:40], 1)
    )
    body = f'<div class="eyebrow">02 · 风险处理</div><h1>审核工作台</h1><p class="lead">先处理最可能改变排名的任务，再决定哪些结果可以进入正式流程。</p><div class="steps"><span class="active">① 选择任务</span><span>② 查看证据</span><span>③ 记录决定</span><span>④ 重新计算</span></div><p class="status"><b>{len(rows)}组待处理任务</b>　按排名影响分排序。当前为只读演示，不会产生正式签名。</p><p class="hint">建议从影响分最高的任务开始：查看企业详情，核验报告页码、口径和候选值，再返回记录审核结论。</p><table><tr><th>#</th><th>企业</th><th>指标</th><th>审核层级</th><th>名次区间</th><th>影响分</th><th>下一动作</th><th>操作</th></tr>{body_rows}</table>'
    return HTMLResponse(_demo_document("审核工作台", body))


@app.get("/demo/complete-chain", response_class=HTMLResponse, include_in_schema=False)
def demo_complete_chain() -> HTMLResponse:
    """Rank the real companies with the strongest currently available evidence chain."""
    ranking_path = DEMO_RANKING_PATH.with_name("ranking.json")
    obs_path = ROOT / "output/research/2025/full_auto_observations_v19.csv"
    coverage_path = ROOT / "output/audit/all_markets_document_coverage_embedded_esg_2025.csv"
    if not ranking_path.is_file() or not obs_path.is_file() or not coverage_path.is_file():
        raise HTTPException(404, "完整数据链演示产物不存在")
    import csv
    observations = list(csv.DictReader(obs_path.open(encoding="utf-8-sig", newline="")))
    counts = {}
    for row in observations:
        counts[row["company_code"]] = counts.get(row["company_code"], 0) + 1
    coverage = {row["stock_code"]: row for row in csv.DictReader(coverage_path.open(encoding="utf-8-sig", newline=""))}
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    # A complete-chain demo means a collected annual report, at least 67 scored observations,
    # and a traceable ranking detail record. It is a curated demo cohort, not a release gate.
    cohort = [row for row in ranking if counts.get(row.get("company_code"), 0) >= 67 and coverage.get(row.get("company_code"), {}).get("annual_status") == "collected"]
    cohort.sort(key=lambda row: row.get("total_score", 0), reverse=True)
    rows = "".join(
        f'<tr><td>{i}</td><td><a href="/demo/company/{html.escape(row.get("company_code", ""))}">{html.escape(row.get("company_code", ""))}</a><br><small>{html.escape(row.get("company_name", ""))}</small></td>'
        f'<td>{row.get("total_score", "-")}</td><td>{row.get("quantitative_score", "-")}</td><td>{row.get("qualitative_score", "-")}</td>'
        f'<td>{counts.get(row.get("company_code"), 0)}</td><td>{html.escape(coverage.get(row.get("company_code"), {}).get("document_count", "-"))}</td><td>{row.get("disclosure_rate", "-")}%</td></tr>'
        for i, row in enumerate(cohort, 1)
    )
    body = f'<div class="eyebrow">01 · 研究结果</div><h1>完整数据链企业排名</h1><p class="lead">优先展示资料、证据和计算链较完整的真实企业，帮助客户先理解系统如何得出结论。</p><div class="steps"><span class="active">① 企业排名</span><span>② 指标计算</span><span>③ 证据核验</span><span>④ 发布判断</span></div><p class="status"><b>{len(cohort)}家演示企业</b>　目标年度文档已采集、研究观测不少于67项、排名明细可下钻。此处是研究预排名，不是正式发布榜单。</p><p class="hint">点击企业名称，查看完整链路：排名 → E/S/G得分 → 中文指标 → 标准化与加权 → 缺失项 → 审核边界。</p><table><tr><th>演示名次</th><th>企业</th><th>总分</th><th>定量分</th><th>定性分</th><th>观测数</th><th>文档数</th><th>披露率</th></tr>{rows}</table>'
    return HTMLResponse(_demo_document("完整数据链企业排名", body))


@app.get("/demo/company/{stock_code}", response_class=HTMLResponse, include_in_schema=False)
def demo_company(stock_code: str) -> HTMLResponse:
    """Show one real company as an evidence-to-decision drill-down."""
    if not DEMO_RANKING_PATH.with_name("ranking.json").is_file():
        raise HTTPException(404, "演示排名数据不存在")
    rankings_data = json.loads(DEMO_RANKING_PATH.with_name("ranking.json").read_text(encoding="utf-8"))
    item = next((row for row in rankings_data if row.get("company_code") == stock_code), None)
    if item is None:
        raise HTTPException(404, "演示排名中未找到企业")
    details = item.get("details", [])
    # Join score details back to the actual research observation and document index.
    # A score without this join is deliberately shown as provenance-missing.
    provenance = {}
    observation_path = ROOT / "output/research/2025/full_auto_observations_v19.csv"
    import csv
    if observation_path.is_file():
        with observation_path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("company_code") == stock_code:
                    provenance[row.get("indicator_code")] = row
    documents = {(row.get("company_code"), row.get("local_path")): row for row in _document_index_rows()}
    def provenance_html(indicator_code: str) -> str:
        source = provenance.get(indicator_code)
        if not source:
            return '<span class="badge missing">来源缺失</span>'
        page = html.escape(str(source.get("source_page") or "未标页"))
        source_file = html.escape(str(source.get("source_file") or "来源文件未记录"))
        source_url = html.escape(str(source.get("source_url") or "#"))
        evidence = html.escape(str(source.get("evidence_text") or "未提供证据文本"))
        doc = documents.get((stock_code, source.get("source_file")))
        digest = html.escape(str(doc.get("sha256"))) if doc and doc.get("sha256") else "未登记Hash"
        document_type = "esg_report" if "esg_report.pdf" in str(source.get("source_file")) else "annual_report"
        local_link = f"/demo/source/{html.escape(stock_code)}/{document_type}"
        return f'<details><summary>第{page}页 · 查看原始证据</summary><div class="evidence" style="margin-top:8px;padding:10px;background:#f7fafd;border-left:3px solid #9ebad2;color:#53657b"><b>本地已下载：</b><a href="{local_link}" target="_blank">打开本地PDF</a><br><b>文档：</b>{source_file}<br><b>外部原始URL：</b><a href="{source_url}" target="_blank">尝试打开交易所链接</a><br><b>文件Hash：</b><code>{digest}</code><br><b>原文：</b>{evidence}</div></details>'

    detail_rows = "".join(
        f'<tr><td><b>{html.escape(_indicator_label(str(d.get("indicator_code", ""))))}</b></td><td><span class="badge {html.escape(str(d.get("status", "")))}">{html.escape(_status_label(str(d.get("status", ""))))}</span></td>'
        f'<td>{html.escape("缺失" if d.get("raw_value") is None else str(d.get("raw_value")))}</td><td>{d.get("normalized_score", "-")}</td><td>{d.get("weighted_score", "-")}</td><td>{d.get("population_count", "-")}</td>'
        f'<td>{provenance_html(str(d.get("indicator_code", "")))}</td></tr>' for d in details
    )
    missing = sum(1 for d in details if d.get("status") == "missing")
    body = f'<div class="eyebrow">03 · 企业决策详情</div><h1>{html.escape(item.get("company_name", ""))} <small>{html.escape(stock_code)}</small></h1><p class="lead">把一个排名结论拆开，查看它由哪些指标、证据和不确定性共同构成。</p><div class="cards"><div><b>研究预排名</b><strong>#{item.get("rank", "-")}</strong></div><div><b>综合得分</b><strong>{item.get("total_score", "-")}</strong></div><div><b>披露率</b><strong>{item.get("disclosure_rate", "-")}%</strong></div><div><b>待补指标</b><strong>{missing}</strong></div></div><p class="status"><b>当前结论：可用于研究分析</b><br>正式发布仍需完成证据审核、签名和冻结门禁。</p><h2>一、维度得分</h2><table><tr><th>环境 E</th><th>社会 S</th><th>治理 G</th><th>定量评价</th><th>定性评价</th></tr><tr><td>{item.get("dimension_scores", {}).get("E", "-")}</td><td>{item.get("dimension_scores", {}).get("S", "-")}</td><td>{item.get("dimension_scores", {}).get("G", "-")}</td><td>{item.get("quantitative_score", "-")}</td><td>{item.get("qualitative_score", "-")}</td></tr></table><h2>二、指标计算与原始证据</h2><p class="hint">点击“查看原始证据”可打开 PDF、查看页码和抽取原文。来源缺失会明确标记，不会被当作已追溯。</p><table><tr><th>中文指标名称</th><th>数据状态</th><th>原始值</th><th>标准分</th><th>加权贡献</th><th>可比样本数</th><th>原始来源</th></tr>{detail_rows}</table>'
    return HTMLResponse(_demo_document("企业决策详情", body))


def _demo_document(title: str, body: str) -> str:
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>aegisESP · {html.escape(title)}</title><style>:root{{--bg:#f5f7fb;--panel:#fff;--ink:#172b4d;--muted:#68778d;--blue:#1769aa;--line:#dfe7f0;--green:#16805b;--amber:#a86200}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1180px;margin:auto;padding:0 22px 70px}}.topbar{{display:flex;align-items:center;justify-content:space-between;padding:18px 0;border-bottom:1px solid var(--line);margin-bottom:30px}}.brand{{font-weight:750;letter-spacing:.2px}}.nav a{{display:inline-block;margin-left:16px;color:var(--muted);text-decoration:none;font-size:13px}}.nav a:hover{{color:var(--blue)}}h1{{font-size:32px;line-height:1.25;margin:4px 0 8px}}h2{{font-size:20px;margin:28px 0 10px}}small{{color:var(--muted)}}.eyebrow{{color:var(--blue);font-size:12px;font-weight:750;letter-spacing:1px;text-transform:uppercase}}.lead{{font-size:17px;color:#4e6077;margin:0 0 20px}}.hint{{color:var(--muted);background:#f7fafd;border-left:3px solid #9ebad2;padding:10px 14px}}.steps{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}}.steps span{{padding:7px 12px;border-radius:20px;background:#eaf0f6;color:#748398;font-size:13px}}.steps .active{{background:#e0f2eb;color:var(--green);font-weight:700}}table{{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;box-shadow:0 4px 15px #172b4d08}}th,td{{padding:12px 13px;border-bottom:1px solid #e9eef4;text-align:left;vertical-align:top}}th{{background:#f3f7fb;color:#5b6c82;font-size:13px;font-weight:650}}tr:last-child td{{border-bottom:0}}a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}.status{{padding:14px 16px;background:#fff8e8;border:1px solid #f0d49b;border-radius:10px;color:#765000}}.success{{padding:12px 15px;background:#e2f3eb;border:1px solid #acd9c6;border-radius:9px;color:var(--green)}}.action-panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;box-shadow:0 4px 15px #172b4d08}}.primary{{background:var(--blue);border-color:var(--blue);color:#fff;padding:10px 17px;font-size:15px;font-weight:700;cursor:pointer}}.result-link{{display:inline-block;margin-left:15px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}.cards>div{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:15px;box-shadow:0 4px 15px #172b4d08}}.cards b{{display:block;color:var(--muted);font-size:13px;font-weight:500}}.cards strong{{display:block;font-size:25px;color:var(--blue);margin-top:3px}}.cards strong.warn{{color:var(--amber)}}.badge{{display:inline-block;padding:3px 8px;border-radius:12px;font-size:12px;background:#eaf0f6;color:#63748a}}.badge.confirmed{{background:#e2f3eb;color:var(--green)}}.badge.missing,.badge.pending{{background:#fff1d9;color:var(--amber)}}button{{border:1px solid var(--line);border-radius:6px;background:#f5f7fa;color:#8b98a8;padding:5px 9px}}</style></head><body><main><div class="topbar"><div class="brand">aegisESP · ESG科学决策系统</div><div class="nav"><a href="/demo">系统总览</a><a href="/demo/ranking-center">排名中心</a><a href="/demo/data-readiness">数据底座</a><a href="/demo/complete-chain">企业排名</a><a href="/demo/review-workbench">审核工作台</a><a href="/demo/readiness">发布门禁</a></div></div>{body}</main></body></html>'''


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "methodology_version": methodology.version}


@app.get("/api/v1/methodology")
def get_methodology() -> dict:
    return {
        "version": methodology.version,
        "name": methodology.name,
        "quantitative_ratio": methodology.quantitative_ratio,
        "qualitative_ratio": methodology.qualitative_ratio,
        "indicators": [vars(item) for item in methodology.indicators],
    }


@app.get("/api/v1/progress")
def progress() -> dict:
    return progress_data()


@app.get("/api/v1/review-conflicts")
def review_conflicts() -> list[dict]:
    return progress_data()["conflicts"]


@app.get("/api/v1/review-tiers")
def review_tiers() -> dict:
    return progress_data()["review_tiers"]


@app.get("/api/v1/resolution-freeze-audit")
def resolution_freeze_audit() -> dict:
    return progress_data()["resolution_freeze_audit"]


@app.get("/api/v1/review-template")
def review_template() -> Response:
    return Response(
        render_conflict_review_template(progress_data()), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=indicator_conflict_review.csv"},
    )


@app.post("/api/v1/observations")
def create_observations(items: list[ObservationIn]) -> dict:
    unknown = sorted({x.indicator_code for x in items} - methodology.by_code.keys())
    if unknown:
        raise HTTPException(422, f"未知指标编码: {unknown}")
    observations = [Observation(**item.model_dump()) for item in items]
    repo = repository()
    repo.upsert_observations(observations)
    return {"accepted": len(observations)}


@app.get("/api/v1/rankings")
def rankings(report_year: int = Query(..., ge=2000, le=2100), limit: int = Query(200, ge=1, le=1000)) -> list[dict]:
    observations = repository().confirmed_observations(report_year)
    if not observations:
        raise HTTPException(404, "该报告期没有可评分数据")
    return [item.to_dict(include_details=False) for item in ScoringEngine(methodology).evaluate(observations)[:limit]]


@app.get("/api/v1/companies/{stock_code}/score")
def company_score(stock_code: str, report_year: int) -> dict:
    results = ScoringEngine(methodology).evaluate(repository().confirmed_observations(report_year))
    for item in results:
        if item.company_code == stock_code:
            return item.to_dict(include_details=True)
    raise HTTPException(404, "未找到公司评分")
