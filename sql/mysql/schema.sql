CREATE DATABASE IF NOT EXISTS aegis_esg CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE aegis_esg;

CREATE TABLE company (
  stock_code VARCHAR(16) PRIMARY KEY,
  company_name VARCHAR(128) NOT NULL,
  exchange VARCHAR(16), sub_industry VARCHAR(64), active BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

CREATE TABLE source_document (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  stock_code VARCHAR(16) NOT NULL, report_year SMALLINT NOT NULL,
  document_type VARCHAR(32) NOT NULL, title VARCHAR(500), source_url VARCHAR(1000),
  storage_key VARCHAR(1000), sha256 CHAR(64) NOT NULL, published_at DATETIME,
  collected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_document_hash (sha256),
  CONSTRAINT fk_document_company FOREIGN KEY(stock_code) REFERENCES company(stock_code)
) ENGINE=InnoDB;

CREATE TABLE observation (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  stock_code VARCHAR(16) NOT NULL, company_name VARCHAR(128) NOT NULL,
  report_year SMALLINT NOT NULL, indicator_code VARCHAR(64) NOT NULL,
  value DECIMAL(28,8), status ENUM('confirmed','pending','missing','not_applicable') NOT NULL,
  source_url VARCHAR(1000), source_file VARCHAR(1000), source_page INT,
  evidence_text TEXT, confidence DECIMAL(5,4) NOT NULL DEFAULT 1,
  revision INT NOT NULL DEFAULT 1, reviewed_by VARCHAR(64), reviewed_at DATETIME,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_observation_revision(stock_code,report_year,indicator_code,revision),
  KEY ix_observation_period(report_year,indicator_code,status)
) ENGINE=InnoDB;

CREATE TABLE scoring_run (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  methodology_version VARCHAR(64) NOT NULL, report_year SMALLINT NOT NULL,
  input_hash CHAR(64) NOT NULL, code_version VARCHAR(64),
  status ENUM('running','completed','failed') NOT NULL,
  parameters_json JSON NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME
) ENGINE=InnoDB;

CREATE TABLE company_score (
  run_id BIGINT NOT NULL, stock_code VARCHAR(16) NOT NULL, rank_no INT NOT NULL,
  quantitative_score DECIMAL(8,4) NOT NULL, qualitative_score DECIMAL(8,4) NOT NULL,
  total_score DECIMAL(8,4) NOT NULL, score_e DECIMAL(8,4) NOT NULL,
  score_s DECIMAL(8,4) NOT NULL, score_g DECIMAL(8,4) NOT NULL,
  disclosure_rate DECIMAL(8,4) NOT NULL,
  PRIMARY KEY(run_id,stock_code), KEY ix_score_rank(run_id,rank_no),
  CONSTRAINT fk_score_run FOREIGN KEY(run_id) REFERENCES scoring_run(id)
) ENGINE=InnoDB;

CREATE TABLE indicator_score_detail (
  run_id BIGINT NOT NULL, stock_code VARCHAR(16) NOT NULL, indicator_code VARCHAR(64) NOT NULL,
  raw_value DECIMAL(28,8), normalized_score DECIMAL(10,6) NOT NULL,
  weight_value DECIMAL(10,6) NOT NULL, weighted_score DECIMAL(10,6) NOT NULL,
  population_count INT NOT NULL, population_mean DECIMAL(28,8), population_stddev DECIMAL(28,8),
  PRIMARY KEY(run_id,stock_code,indicator_code),
  CONSTRAINT fk_detail_run FOREIGN KEY(run_id) REFERENCES scoring_run(id)
) ENGINE=InnoDB;
