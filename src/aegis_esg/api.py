from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .dashboard import load_progress_dashboard, render_conflict_review_template, render_progress_dashboard
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
methodology = load_methodology(METHODOLOGY_PATH)
app = FastAPI(title="中国能源上市公司ESG评价系统", version="0.1.0")


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
