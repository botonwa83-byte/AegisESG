from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Observation, ValueStatus


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS company (
  stock_code TEXT PRIMARY KEY, company_name TEXT NOT NULL, exchange TEXT,
  sub_industry TEXT, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS source_document (
  id INTEGER PRIMARY KEY AUTOINCREMENT, stock_code TEXT NOT NULL, report_year INTEGER NOT NULL,
  document_type TEXT NOT NULL, title TEXT, source_url TEXT, storage_key TEXT,
  sha256 TEXT NOT NULL, published_at TEXT, collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(sha256), FOREIGN KEY(stock_code) REFERENCES company(stock_code)
);
CREATE TABLE IF NOT EXISTS observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT, stock_code TEXT NOT NULL, company_name TEXT NOT NULL,
  report_year INTEGER NOT NULL, indicator_code TEXT NOT NULL, value REAL,
  status TEXT NOT NULL, source_url TEXT, source_file TEXT, source_page INTEGER,
  evidence_text TEXT, confidence REAL NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1,
  reviewed_by TEXT, reviewed_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(stock_code, report_year, indicator_code, revision)
);
CREATE TABLE IF NOT EXISTS scoring_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT, methodology_version TEXT NOT NULL, report_year INTEGER NOT NULL,
  input_hash TEXT NOT NULL, code_version TEXT, status TEXT NOT NULL,
  parameters_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS company_score (
  run_id INTEGER NOT NULL, stock_code TEXT NOT NULL, rank_no INTEGER NOT NULL,
  quantitative_score REAL NOT NULL, qualitative_score REAL NOT NULL, total_score REAL NOT NULL,
  score_e REAL NOT NULL, score_s REAL NOT NULL, score_g REAL NOT NULL, disclosure_rate REAL NOT NULL,
  PRIMARY KEY(run_id, stock_code), FOREIGN KEY(run_id) REFERENCES scoring_run(id)
);
"""


class SQLiteRepository:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def upsert_observations(self, observations: list[Observation]) -> None:
        for item in observations:
            self.connection.execute(
                "INSERT OR IGNORE INTO company(stock_code,company_name) VALUES (?,?)",
                (item.company_code, item.company_name),
            )
            revision = self.connection.execute(
                """SELECT COALESCE(MAX(revision),0)+1 FROM observation
                   WHERE stock_code=? AND report_year=? AND indicator_code=?""",
                (item.company_code, item.report_year, item.indicator_code),
            ).fetchone()[0]
            self.connection.execute(
                """INSERT INTO observation
                (stock_code,company_name,report_year,indicator_code,value,status,source_url,
                 source_file,source_page,evidence_text,confidence,revision)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item.company_code, item.company_name, item.report_year, item.indicator_code,
                 item.value, item.status.value, item.source_url, item.source_file,
                 item.source_page, item.evidence_text, item.confidence, revision),
            )
        self.connection.commit()

    def confirmed_observations(self, report_year: int) -> list[Observation]:
        rows = self.connection.execute(
            """SELECT o.* FROM observation o JOIN (
              SELECT stock_code,report_year,indicator_code,MAX(revision) revision FROM observation
              WHERE report_year=? GROUP BY stock_code,report_year,indicator_code
            ) latest USING(stock_code,report_year,indicator_code,revision)""",
            (report_year,),
        )
        return [Observation(
            company_code=r["stock_code"], company_name=r["company_name"],
            report_year=r["report_year"], indicator_code=r["indicator_code"], value=r["value"],
            status=ValueStatus(r["status"]), source_url=r["source_url"] or "",
            source_file=r["source_file"] or "", source_page=r["source_page"],
            evidence_text=r["evidence_text"] or "", confidence=r["confidence"],
        ) for r in rows]
