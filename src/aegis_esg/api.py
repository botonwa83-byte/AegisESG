from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .methodology import load_methodology
from .models import Observation, ValueStatus
from .repository import SQLiteRepository
from .scoring import ScoringEngine


ROOT = Path(__file__).resolve().parents[2]
METHODOLOGY_PATH = Path(os.getenv("AEGIS_METHODOLOGY", ROOT / "data/methodologies/energy_esg_2025.json"))
DB_PATH = Path(os.getenv("AEGIS_DB", ROOT / "var/aegis.db"))
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
