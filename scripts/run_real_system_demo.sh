#!/bin/sh
set -eu

# 领导演示用全市场只读配置；不执行采集、评分写回或人工审核。
# 无论从哪个目录启动，都先定位项目根目录，避免相对PYTHONPATH在sudo/脚本目录下失效。
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export AEGIS_PROGRESS_SUMMARY="$PROJECT_ROOT/output/audit/all_markets_quantitative_candidate_tasks_summary_v22_2025.json"
export AEGIS_PROGRESS_TASKS="$PROJECT_ROOT/output/audit/all_markets_quantitative_candidate_tasks_v22_2025.csv"
export AEGIS_REVIEW_SUMMARY="$PROJECT_ROOT/output/audit/all_markets_indicator_candidate_review_summary_v22_2025.csv"
export AEGIS_CANDIDATES="$PROJECT_ROOT/data/review/all_markets_indicator_candidates_v22_2025.csv"
export AEGIS_REVIEW_TIERS_SUMMARY="$PROJECT_ROOT/output/audit/all_markets_indicator_review_tiers_summary_v22_2025.json"
export AEGIS_REVIEW_TIERS="$PROJECT_ROOT/output/audit/all_markets_indicator_review_tiers_v22_2025.csv"
export AEGIS_RESOLUTION_FREEZE_AUDIT="$PROJECT_ROOT/output/audit/all_markets_indicator_resolution_audit_v22_2025.json"
export AEGIS_DEMO_RANKING_PATH="$PROJECT_ROOT/output/demo/real_data_demo_2025/ranking.html"
export AEGIS_DEMO_SENSITIVITY_PATH="$PROJECT_ROOT/output/demo/real_data_demo_2025/ranking_sensitivity.json"
export AEGIS_DEMO_METADATA_PATH="$PROJECT_ROOT/output/demo/real_data_demo_2025/ranking_metadata.json"
export AEGIS_DEMO_READINESS_PATH="$PROJECT_ROOT/output/demo/real_data_demo_2025/external_readiness_2025.json"

exec uvicorn aegis_esg.api:app --host 127.0.0.1 --port "${AEGIS_DEMO_PORT:-8000}"
