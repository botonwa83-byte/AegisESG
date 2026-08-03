from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .collector import collect_batch, collect_from_manifest, supersede_documents, write_document_index
from .completion import audit_project_completion, write_completion_report
from .continuity_evidence import extract_continuity_evidence_candidates, finalize_continuity_reviews, prepare_continuity_review_packets, render_continuity_review_guide, select_continuity_review_batch, write_continuity_evidence_candidates, write_continuity_review_batch, write_continuity_review_guide, write_continuity_review_packets, write_finalized_continuity_reviews
from .extraction import ReviewSummary, extract_batch_text_exports, extract_indicator_candidates, extract_pdf_text, read_page_text_export, summarize_review_candidates
from .esg_disclosure import (
    collect_annual_qualitative_evidence, collect_esg_qualitative_evidence,
    scan_annual_esg_disclosure, write_annual_esg_evidence,
    write_qualitative_candidates, write_qualitative_evidence_candidates,
)
from .evidence_graph import build_evidence_constraint_graph, write_evidence_constraint_graph
from .financial import derive_financial_observations, read_financial_facts
from .historical import import_historical_workbook, write_historical_import
from .indicator_plan import plan_candidate_coverage, plan_indicator_tasks, write_candidate_coverage, write_indicator_plan
from .issuer_continuity import apply_issuer_continuity_decisions, audit_hkex_issuer_continuity, plan_continuity_evidence_tasks, write_applied_continuity_decisions, write_continuity_evidence_tasks, write_issuer_continuity_audit
from .dual_review import (
    apply_arbitration_decisions, apply_dual_review_decisions, read_arbitration_cases,
    read_arbitration_decisions, read_dual_review_decisions, read_qualitative_review_audits,
    select_dual_review_cases, write_arbitration_results, write_dual_review_results,
    write_dual_review_template,
)
from .io import merge_confirmed_observations, read_observations, write_observation_template, write_observations, write_ranking_csv, write_ranking_html, write_ranking_json
from .methodology import load_methodology
from .qualitative_review import (
    apply_qualitative_review_decisions, merge_qualitative_candidate_files,
    plan_qualitative_review, read_qualitative_candidates,
    read_qualitative_review_decisions, read_qualitative_review_packets,
    reprioritize_evidence_gaps, write_qualitative_review_plan, write_qualitative_review_results,
    write_qualitative_review_template, write_reprioritized_gaps,
)
from .review_batch import (
    apply_review_batch, create_review_batch, read_batch_ledger, read_batch_rows,
    read_review_progress, update_ledger_entry, write_batch_ledger, write_review_progress,
)
from .review_priority import prioritize_review_by_impact, write_impact_review_plan
from .migration import augment_candidate_universe, bind_snapshot_provenance, plan_historical_migration, write_augmented_universe, write_candidate_universe, write_migration_plan, write_provenance_binding
from .planning import audit_document_coverage, collection_summary, merge_document_indexes, plan_collection, read_document_records, write_collection_plan, write_collection_summary, write_document_coverage
from .quality import evaluate_quality
from .ranking_analysis import analyze_missing_sensitivity, validate_ranking_mode, write_sensitivity_report
from .repository import SQLiteRepository
from .resolution import audit_resolution_preview, plan_review_tiers, read_resolution_decisions, read_review_tiers, resolve_pending_candidates, select_manual_review_candidates, write_review_tiers
from .review import apply_conflict_review_instructions, apply_review_instructions, read_review_instructions, write_review_audit, write_review_template
from .reference import extract_reference_securities, write_reference_securities
from .registry import reconcile_registry, write_registry_reconciliation
from .scoring import MissingStrategy, ScoringEngine
from .sources.sse import discover_reports
from .sources.szse import discover_batch as discover_szse_batch, discover_reports as discover_szse_reports
from .sources.listings import collect_listing_pages, fetch_json
from .sources.hkex import import_hkex_securities
from .sources.hkex_profile import collect_hkex_issuer_profiles, prepare_hkex_evidence_drafts, write_hkex_evidence_drafts, write_hkex_issuer_profiles
from .sources.hkex_disclosure import discover_hkex_continuity_batch, read_hkex_disclosures, select_continuity_downloads, write_hkex_disclosures
from .sources.bse import BSE_LIST_PAGE, collect_bse_listings, make_bse_fetcher, parse_bse_code_mapping, discover_bse_annual_report
from .universe import audit_universe, read_universe, write_universe_audit
from .universe_builder import audit_snapshot, build_energy_universe, normalize_exchange_export, read_exchange_snapshot, write_decision_audit, write_exchange_snapshot, write_snapshot_quality, write_universe
from .universe_review import apply_universe_evidence, merge_universe_evidence_batches, plan_universe_evidence, write_applied_universe_evidence, write_universe_evidence_ledger, write_universe_evidence_plan


DEFAULT_METHODOLOGY = Path("data/methodologies/energy_esg_2025.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="中国能源上市公司ESG评价工具")
    parser.add_argument("--methodology", default=str(DEFAULT_METHODOLOGY))
    sub = parser.add_subparsers(dest="command", required=True)
    template = sub.add_parser("template", help="生成观测数据CSV模板")
    template.add_argument("output")
    completion = sub.add_parser("audit-completion", help="汇总六道项目完成与正式发布门禁")
    completion.add_argument("--documents", required=True, help="文档覆盖摘要JSON")
    completion.add_argument("--quantitative", required=True, help="定量候选任务摘要JSON")
    completion.add_argument("--qualitative", required=True, help="定性复核计划摘要JSON")
    completion.add_argument("--resolution", required=True, help="定量冻结审计摘要JSON")
    completion.add_argument("--expected-companies", type=int, default=632)
    completion.add_argument("--output", required=True)
    evidence_graph = sub.add_parser("build-evidence-graph", help="构建多源证据约束图及质量摘要")
    evidence_graph.add_argument("input")
    evidence_graph.add_argument("--output", required=True)
    evidence_graph.add_argument("--summary", required=True)
    score = sub.add_parser("score", help="从CSV自动计算并导出排名")
    score.add_argument("input")
    score.add_argument("--output-dir", default="output")
    score.add_argument("--title", default="中国能源上市公司可持续发展（ESG）评价前200名单")
    score.add_argument("--universe", help="正式发布时使用的公司池CSV")
    score.add_argument("--expected-companies", type=int, help="正式发布目标公司主体数")
    score.add_argument("--mode", choices=("preview", "research", "release"), default="preview")
    score.add_argument("--missing-strategy", choices=tuple(item.value for item in MissingStrategy))
    score.add_argument("--release", action="store_true", help="兼容旧调用，等同于--mode release")
    universe_audit = sub.add_parser("universe-audit", help="审计公司池及已完成数据覆盖")
    universe_audit.add_argument("universe")
    universe_audit.add_argument("--observations")
    universe_audit.add_argument("--expected-companies", type=int, default=632)
    universe_audit.add_argument("--output", required=True)
    build_universe = sub.add_parser("build-universe", help="从交易所标准快照生成能源公司池和审计表")
    build_universe.add_argument("snapshots", nargs="+")
    build_universe.add_argument("--output", required=True)
    build_universe.add_argument("--audit", required=True)
    normalize_snapshot = sub.add_parser("normalize-snapshot", help="将交易所CSV/TSV/XLSX导出转换为标准快照")
    normalize_snapshot.add_argument("input")
    normalize_snapshot.add_argument("--exchange", required=True, choices=("SSE", "SZSE", "BSE", "HKEX"))
    normalize_snapshot.add_argument("--source-url", required=True)
    normalize_snapshot.add_argument("--as-of-date", required=True)
    normalize_snapshot.add_argument("--output", required=True)
    normalize_snapshot.add_argument("--quality", required=True)
    discover_listings = sub.add_parser("discover-listings", help="从官方分页JSON接口采集上市证券快照")
    discover_listings.add_argument("--exchange", required=True, choices=("SSE", "SZSE", "BSE", "HKEX"))
    discover_listings.add_argument("--endpoint-template", required=True, help="包含{page}占位符的官方接口URL")
    discover_listings.add_argument("--referer", required=True)
    discover_listings.add_argument("--as-of-date", required=True)
    discover_listings.add_argument("--output", required=True)
    discover_listings.add_argument("--quality", required=True)
    merge_snapshots = sub.add_parser("merge-snapshots", help="合并多个已标准化交易所快照")
    merge_snapshots.add_argument("snapshots", nargs="+")
    merge_snapshots.add_argument("--output", required=True)
    merge_snapshots.add_argument("--quality", required=True)
    import_listing = sub.add_parser("import-listing-json", help="从已保存的单页官方JSON生成标准快照")
    import_listing.add_argument("input")
    import_listing.add_argument("--exchange", required=True, choices=("SSE", "SZSE", "BSE", "HKEX"))
    import_listing.add_argument("--source-url", required=True)
    import_listing.add_argument("--as-of-date", required=True)
    import_listing.add_argument("--output", required=True)
    import_listing.add_argument("--quality", required=True)
    import_hkex = sub.add_parser("import-hkex-list", help="导入港交所Full List并筛选主板/GEM普通股")
    import_hkex.add_argument("input")
    import_hkex.add_argument("--source-url", required=True)
    import_hkex.add_argument("--as-of-date", default="", help="可选：要求文件内更新日期与此日期一致")
    import_hkex.add_argument("--output", required=True)
    import_hkex.add_argument("--quality", required=True)
    hkex_profiles = sub.add_parser("discover-hkex-profiles", help="采集港交所中文名称、公司简介和行业候选证据")
    hkex_profiles.add_argument("universe")
    hkex_profiles.add_argument("--output", required=True)
    hkex_profiles.add_argument("--raw-output", required=True)
    hkex_profiles.add_argument("--limit", type=int, default=0, help="仅处理前N家，0表示全部港股")
    hkex_drafts = sub.add_parser("prepare-hkex-evidence-review", help="按版本化精确映射生成未签名港股行业审核草案")
    hkex_drafts.add_argument("profiles")
    hkex_drafts.add_argument("--universe", required=True)
    hkex_drafts.add_argument("--mapping", default="data/methodologies/hkex_energy_industry_mapping_2026.json")
    hkex_drafts.add_argument("--evidence-date", required=True)
    hkex_drafts.add_argument("--output", required=True)
    hkex_drafts.add_argument("--summary", required=True)
    issuer_continuity = sub.add_parser("audit-hkex-issuer-continuity", help="对账历史与当前港股发行人身份及A/H线索")
    issuer_continuity.add_argument("historical_registry")
    issuer_continuity.add_argument("--profiles", required=True)
    issuer_continuity.add_argument("--drafts", required=True)
    issuer_continuity.add_argument("--code-map", action="append")
    issuer_continuity.add_argument("--output", required=True)
    issuer_continuity.add_argument("--summary", required=True)
    continuity_tasks = sub.add_parser("plan-hkex-continuity-evidence", help="生成港股发行人连续性官方证据采集任务")
    continuity_tasks.add_argument("continuity_audit")
    continuity_tasks.add_argument("--output", required=True)
    continuity_tasks.add_argument("--summary", required=True)
    hkex_documents = sub.add_parser("discover-hkex-continuity-documents", help="从HKEXnews发现发行人连续性官方文件")
    hkex_documents.add_argument("tasks")
    hkex_documents.add_argument("--from-date", required=True)
    hkex_documents.add_argument("--to-date", required=True)
    hkex_documents.add_argument("--limit", type=int, default=0)
    hkex_documents.add_argument("--delay", type=float, default=.5)
    hkex_documents.add_argument("--resume", action="store_true")
    hkex_documents.add_argument("--failures")
    hkex_documents.add_argument("--output", required=True)
    hkex_documents.add_argument("--raw-output", required=True)
    hkex_downloads = sub.add_parser("prepare-hkex-continuity-downloads", help="从发现结果选择无覆盖冲突的连续性文件下载清单")
    hkex_downloads.add_argument("discoveries")
    hkex_downloads.add_argument("--output", required=True)
    hkex_downloads.add_argument("--summary", required=True)
    hkex_downloads.add_argument("--report-year", type=int)
    hkex_downloads.add_argument("--annual-only", action="store_true")
    continuity_extract = sub.add_parser("extract-hkex-continuity-evidence", help="从带页码文本提取发行人沿革、主营业务和A/H身份候选")
    continuity_extract.add_argument("document_index")
    continuity_extract.add_argument("--text-root", default="data/text")
    continuity_extract.add_argument("--max-per-category", type=int, default=5)
    continuity_extract.add_argument("--output", required=True)
    continuity_extract.add_argument("--summary", required=True)
    continuity_packets = sub.add_parser("prepare-hkex-continuity-review", help="生成未签名发行人连续性人工复核包")
    continuity_packets.add_argument("tasks")
    continuity_packets.add_argument("candidates")
    continuity_packets.add_argument("--output", required=True)
    continuity_packets.add_argument("--summary", required=True)
    continuity_guide = sub.add_parser("render-hkex-continuity-review", help="将候选证据渲染为人类可读的未签名审阅手册")
    continuity_guide.add_argument("packets")
    continuity_guide.add_argument("candidates")
    continuity_guide.add_argument("--output", required=True)
    continuity_guide.add_argument("--summary", required=True)
    continuity_batch = sub.add_parser("select-hkex-continuity-review-batch", help="按最高优先级切分可独立签名的连续性复核批次")
    continuity_batch.add_argument("packets")
    continuity_batch.add_argument("candidates")
    continuity_batch.add_argument("--max-priority", type=int, required=True)
    continuity_batch.add_argument("--output-packets", required=True)
    continuity_batch.add_argument("--output-candidates", required=True)
    continuity_batch.add_argument("--summary", required=True)
    finalize_continuity = sub.add_parser("finalize-hkex-continuity-review", help="严格校验已签名复核包并生成可应用决定")
    finalize_continuity.add_argument("packets")
    finalize_continuity.add_argument("candidates")
    finalize_continuity.add_argument("--output", required=True)
    finalize_continuity.add_argument("--audit", required=True)
    finalize_continuity.add_argument("--summary", required=True)
    apply_continuity = sub.add_parser("apply-hkex-continuity-decisions", help="应用签名发行人连续性及A/H主体决定")
    apply_continuity.add_argument("universe")
    apply_continuity.add_argument("decisions")
    apply_continuity.add_argument("--continuity-audit", required=True)
    apply_continuity.add_argument("--output", required=True)
    apply_continuity.add_argument("--audit", required=True)
    apply_continuity.add_argument("--summary", required=True)
    discover_bse = sub.add_parser("discover-bse-listings", help="采集北交所全部正常上市公司快照")
    discover_bse.add_argument("--as-of-date", default="", help="可选：要求接口报告日期与此日期一致")
    discover_bse.add_argument("--output", required=True)
    discover_bse.add_argument("--quality", required=True)
    discover_bse.add_argument("--raw-output", required=True, help="保存逐页官方原始响应JSON")
    import_bse_map = sub.add_parser("import-bse-code-map", help="从北交所官方HTML导入新旧代码对照表")
    import_bse_map.add_argument("input")
    import_bse_map.add_argument("--output", required=True)
    reference_codes = sub.add_parser("extract-reference-codes", help="从参考榜单OCR提取证券代码并与快照核对")
    reference_codes.add_argument("ocr")
    reference_codes.add_argument("--snapshot", required=True)
    reference_codes.add_argument("--pages", default="67-72")
    reference_codes.add_argument("--output", required=True)
    reference_codes.add_argument("--code-map", action="append", help="旧代码到当前代码映射CSV，可重复指定")
    registry = sub.add_parser("reconcile-registry", help="将外部企业名录与交易所快照对账")
    registry.add_argument("input")
    registry.add_argument("--snapshot", required=True)
    registry.add_argument("--source-name", required=True)
    registry.add_argument("--source-url", default="")
    registry.add_argument("--as-of-date", required=True)
    registry.add_argument("--output", required=True)
    historical = sub.add_parser("import-historical-workbook", help="导入往年两行制ESG评价工作簿")
    historical.add_argument("input")
    historical.add_argument("--snapshot", required=True)
    historical.add_argument("--evaluation-year", required=True, type=int)
    historical.add_argument("--report-year", required=True, type=int)
    historical.add_argument("--companies", required=True)
    historical.add_argument("--observations", required=True)
    historical.add_argument("--audit", required=True)
    migrate = sub.add_parser("plan-universe-migration", help="将历史公司表迁移为本年度候选样本计划")
    migrate.add_argument("historical_registry")
    migrate.add_argument("--snapshot", required=True)
    migrate.add_argument("--output", required=True)
    migrate.add_argument("--audit", required=True)
    migrate.add_argument("--candidate-universe", help="同步输出可供采集计划使用的标准候选公司池")
    migrate.add_argument("--code-map", action="append", help="旧代码到当前代码映射CSV，可重复指定")
    augment = sub.add_parser("augment-universe", help="以可审计证据表向候选池追加当前快照证券")
    augment.add_argument("base")
    augment.add_argument("additions")
    augment.add_argument("--snapshot", required=True)
    augment.add_argument("--output", required=True)
    bind_provenance = sub.add_parser("bind-universe-provenance", help="按证券代码精确绑定候选池与官方快照来源")
    bind_provenance.add_argument("universe")
    bind_provenance.add_argument("--snapshot", required=True)
    bind_provenance.add_argument("--output", required=True)
    bind_provenance.add_argument("--audit", required=True)
    bind_provenance.add_argument("--summary", required=True)
    evidence_plan = sub.add_parser("plan-universe-evidence", help="生成行业纳入及主体映射证据复核队列")
    evidence_plan.add_argument("universe")
    evidence_plan.add_argument("--snapshot", required=True)
    evidence_plan.add_argument("--output", required=True)
    evidence_plan.add_argument("--summary", required=True)
    evidence_plan.add_argument("--exchange", action="append", choices=("SSE", "SZSE", "BSE", "HKEX"), help="仅生成指定交易所任务，可重复")
    merge_evidence = sub.add_parser("merge-universe-evidence", help="合并带版本链的证据审核批次")
    merge_evidence.add_argument("batches", nargs="+")
    merge_evidence.add_argument("--active-output", required=True)
    merge_evidence.add_argument("--ledger-output", required=True)
    merge_evidence.add_argument("--summary", required=True)
    apply_evidence = sub.add_parser("apply-universe-evidence", help="应用带审核签名的行业及A/H主体决定")
    apply_evidence.add_argument("universe")
    apply_evidence.add_argument("decisions")
    apply_evidence.add_argument("--output", required=True)
    apply_evidence.add_argument("--audit", required=True)
    apply_evidence.add_argument("--summary", required=True)
    plan = sub.add_parser("plan-collection", help="按公司池和现有文档索引生成批量采集缺口计划")
    plan.add_argument("universe")
    plan.add_argument("--document-index", default="data/raw/document_index.csv")
    plan.add_argument("--report-year", required=True, type=int)
    plan.add_argument("--output", required=True)
    plan.add_argument("--summary", required=True)
    indicator_plan = sub.add_parser("plan-indicators", help="生成公司×完整ESG指标任务矩阵")
    indicator_plan.add_argument("universe")
    indicator_plan.add_argument("observations")
    indicator_plan.add_argument("--report-year", required=True, type=int)
    indicator_plan.add_argument("--output", required=True)
    indicator_plan.add_argument("--summary", required=True)
    candidate_plan = sub.add_parser("plan-candidate-coverage", help="生成公司×37项定量指标候选覆盖矩阵")
    candidate_plan.add_argument("companies")
    candidate_plan.add_argument("candidates")
    candidate_plan.add_argument("--output", required=True)
    candidate_plan.add_argument("--summary", required=True)
    database = sub.add_parser("init-db", help="初始化本地审计数据库")
    database.add_argument("path", default="var/aegis.db", nargs="?")
    discover = sub.add_parser("discover-sse", help="从上交所官方接口发现年报和ESG报告")
    discover.add_argument("universe")
    discover.add_argument("--report-year", type=int, required=True)
    discover.add_argument("--output", required=True)
    discover.add_argument("--failures")
    discover.add_argument("--summary")
    discover.add_argument("--delay", type=float, default=.5)
    discover.add_argument("--resume", action="store_true")
    discover.add_argument("--workers", type=int, default=6)
    discover_szse = sub.add_parser("discover-szse", help="从深交所官方接口发现年报和ESG报告")
    discover_szse.add_argument("universe")
    discover_szse.add_argument("--report-year", type=int, required=True)
    discover_szse.add_argument("--output", required=True)
    discover_szse.add_argument("--failures")
    discover_szse.add_argument("--summary")
    discover_szse.add_argument("--delay", type=float, default=.5)
    discover_szse.add_argument("--resume", action="store_true")
    discover_szse.add_argument("--workers", type=int, default=6)
    discover_bse = sub.add_parser("discover-bse", help="从北交所官方年度报告分类发现正式年报")
    discover_bse.add_argument("universe")
    discover_bse.add_argument("--report-year", type=int, required=True)
    discover_bse.add_argument("--output", required=True)
    discover_bse.add_argument("--failures", required=True)
    collect = sub.add_parser("collect", help="下载审核后的公开报告清单并生成Hash索引")
    collect.add_argument("manifest")
    collect.add_argument("--output-root", default="data/raw")
    collect.add_argument("--index", default="data/raw/document_index.csv")
    collect.add_argument("--delay", type=float, default=1.0)
    collect.add_argument("--failures")
    collect.add_argument("--resume", action="store_true", help="复用有效本地PDF并逐项写入检查点")
    collect.add_argument("--workers", type=int, default=1)
    collect.add_argument("--reuse-index", action="append", default=[], help="额外的可信文档索引，用于恢复断点")
    collect.add_argument("--preserve-index", action="store_true", help="仅处理增量清单并保留主索引中的其他文档")
    supersede = sub.add_parser("supersede-documents", help="归档误登记文档并从索引移除，写入取代账本")
    supersede.add_argument("document_index")
    supersede.add_argument("--requests", required=True, help="取代请求CSV：公司、年度、类型、原因")
    supersede.add_argument("--archive-root", required=True)
    supersede.add_argument("--ledger", required=True)
    supersede.add_argument("--summary", required=True)
    merge_indexes = sub.add_parser("merge-document-indexes", help="严格合并多个文档索引并拒绝URL或路径冲突")
    merge_indexes.add_argument("indexes", nargs="+")
    merge_indexes.add_argument("--output", required=True)
    merge_indexes.add_argument("--summary", required=True)
    merge_indexes.add_argument("--allow-metadata-corrections", action="store_true")
    coverage = sub.add_parser("audit-document-coverage", help="审计公司清单的年报和ESG文件覆盖")
    coverage.add_argument("companies")
    coverage.add_argument("document_index")
    coverage.add_argument("--report-year", type=int, help="仅审计指定报告年度")
    coverage.add_argument("--output", required=True)
    coverage.add_argument("--summary", required=True)
    esg_scan = sub.add_parser("scan-annual-esg-disclosure", help="从无独立ESG报告公司的年报提取待复核披露候选")
    esg_scan.add_argument("coverage")
    esg_scan.add_argument("document_index")
    esg_scan.add_argument("--text-root", default="data/text")
    esg_scan.add_argument("--max-per-company", type=int, default=5)
    esg_scan.add_argument("--output", required=True)
    esg_scan.add_argument("--summary", required=True)
    qualitative = sub.add_parser("collect-annual-qualitative-evidence", help="从年报定位43项定性指标的待复核证据")
    qualitative.add_argument("coverage")
    qualitative.add_argument("document_index")
    qualitative.add_argument("--methodology", default="data/methodologies/energy_esg_2025.json")
    qualitative.add_argument("--report-year", type=int, required=True)
    qualitative.add_argument("--text-root", default="data/text")
    qualitative.add_argument("--max-per-indicator", type=int, default=3)
    qualitative.add_argument("--output", required=True)
    qualitative.add_argument("--summary", required=True)
    qualitative_esg = sub.add_parser("collect-esg-qualitative-evidence", help="从独立ESG报告定位43项定性指标的待复核证据")
    qualitative_esg.add_argument("coverage")
    qualitative_esg.add_argument("document_index")
    qualitative_esg.add_argument("--methodology", default="data/methodologies/energy_esg_2025.json")
    qualitative_esg.add_argument("--report-year", type=int, required=True)
    qualitative_esg.add_argument("--text-root", default="data/text")
    qualitative_esg.add_argument("--max-per-indicator", type=int, default=3)
    qualitative_esg.add_argument("--output", required=True)
    qualitative_esg.add_argument("--summary", required=True)
    merge_qual = sub.add_parser("merge-qualitative-candidates", help="合并多份定性证据候选，精确去重且冲突拒绝")
    merge_qual.add_argument("inputs", nargs="+")
    merge_qual.add_argument("--output", required=True)
    merge_qual.add_argument("--summary", required=True)
    qualitative_plan = sub.add_parser("plan-qualitative-review", help="去重定性证据并生成保守档位建议和缺口队列")
    qualitative_plan.add_argument("candidates")
    qualitative_plan.add_argument("coverage")
    qualitative_plan.add_argument("--methodology", default="data/methodologies/energy_esg_2025.json")
    qualitative_plan.add_argument("--report-year", type=int, required=True)
    qualitative_plan.add_argument("--packets", required=True)
    qualitative_plan.add_argument("--gaps", required=True)
    qualitative_plan.add_argument("--summary", required=True)
    qualitative_template = sub.add_parser("qualitative-review-template", help="按优先级生成空白定性签名复核批次")
    qualitative_template.add_argument("packets")
    qualitative_template.add_argument("--priority", type=int, choices=(1, 2))
    qualitative_template.add_argument("--limit", type=int)
    qualitative_template.add_argument("--output", required=True)
    apply_qualitative = sub.add_parser("apply-qualitative-review", help="严格应用定性复核签名并输出确认、剩余和审计")
    apply_qualitative.add_argument("packets")
    apply_qualitative.add_argument("decisions")
    apply_qualitative.add_argument("--confirmed", required=True)
    apply_qualitative.add_argument("--unresolved", required=True)
    apply_qualitative.add_argument("--audit", required=True)
    review_batch = sub.add_parser("qualitative-review-batch", help="创建定性复核批次并登记批次清单")
    review_batch.add_argument("packets")
    review_batch.add_argument("--ledger", required=True)
    review_batch.add_argument("--label", default="")
    review_batch.add_argument("--priority", type=int, choices=(1, 2))
    review_batch.add_argument("--limit", type=int)
    review_batch.add_argument("--output", required=True)
    apply_batch = sub.add_parser("apply-qualitative-batch", help="按批次清单门禁应用定性批次签名并更新完成率")
    apply_batch.add_argument("packets")
    apply_batch.add_argument("batch_file")
    apply_batch.add_argument("--ledger", required=True)
    apply_batch.add_argument("--progress", required=True)
    apply_batch.add_argument("--confirmed", required=True)
    apply_batch.add_argument("--unresolved", required=True)
    apply_batch.add_argument("--audit", required=True)
    dual_select = sub.add_parser("select-dual-review", help="筛出需双人复核的定性决定并生成空白二审模板")
    dual_select.add_argument("packets")
    dual_select.add_argument("audits")
    dual_select.add_argument("--output", required=True)
    dual_apply = sub.add_parser("apply-dual-review", help="应用二审签名，一致闭合、分歧进入仲裁队列")
    dual_apply.add_argument("packets")
    dual_apply.add_argument("audits")
    dual_apply.add_argument("decisions")
    dual_apply.add_argument("--confirmed", required=True)
    dual_apply.add_argument("--outcomes", required=True)
    dual_apply.add_argument("--arbitration", required=True)
    dual_apply.add_argument("--open", required=True)
    arbitration_apply = sub.add_parser("apply-qualitative-arbitration", help="应用仲裁签名并输出最终确认观测")
    arbitration_apply.add_argument("arbitration_file")
    arbitration_apply.add_argument("--confirmed", required=True)
    arbitration_apply.add_argument("--unresolved", required=True)
    arbitration_apply.add_argument("--audit", required=True)
    gap_rank = sub.add_parser("reprioritize-qualitative-gaps", help="按指标权重和ESG报告状态重排定性证据缺口")
    gap_rank.add_argument("gaps")
    gap_rank.add_argument("coverage")
    gap_rank.add_argument("--output", required=True)
    gap_rank.add_argument("--summary", required=True)
    merge_confirmed = sub.add_parser("merge-confirmed-observations", help="安全合并多份confirmed观测，冲突拒绝")
    merge_confirmed.add_argument("inputs", nargs="+")
    merge_confirmed.add_argument("--methodology", default="data/methodologies/energy_esg_2025.json")
    merge_confirmed.add_argument("--output", required=True)
    merge_confirmed.add_argument("--summary", required=True)
    derive = sub.add_parser("derive-financial", help="从标准财务事实自动派生治理指标")
    derive.add_argument("input")
    derive.add_argument("--output", required=True)
    extract = sub.add_parser("extract-pdf", help="从单份PDF抽取待复核指标候选")
    extract.add_argument("pdf")
    extract.add_argument("--company-code", required=True)
    extract.add_argument("--company-name", required=True)
    extract.add_argument("--report-year", required=True, type=int)
    extract.add_argument("--source-url", default="")
    extract.add_argument("--output", required=True)
    extract_text = sub.add_parser("extract-text", help="从带页码的PDF文本导出中抽取待复核候选")
    extract_text.add_argument("text")
    extract_text.add_argument("--source-file", required=True)
    extract_text.add_argument("--company-code", required=True)
    extract_text.add_argument("--company-name", required=True)
    extract_text.add_argument("--report-year", required=True, type=int)
    extract_text.add_argument("--source-url", default="")
    extract_text.add_argument("--output", required=True)
    extract_batch = sub.add_parser("extract-batch-text", help="批量抽取带页码文本并统计公司覆盖")
    extract_batch.add_argument("document_index")
    extract_batch.add_argument("text_root")
    extract_batch.add_argument("--output", required=True)
    extract_batch.add_argument("--coverage", required=True)
    extract_batch.add_argument("--review-summary")
    extract_batch.add_argument("--report-year", type=int)
    quality = sub.add_parser("quality", help="检查正式评分数据是否达到发布门槛")
    quality.add_argument("input")
    quality.add_argument("--expected-companies", type=int)
    resolve = sub.add_parser("resolve-pending", help="按审计策略自动确认无歧义候选")
    resolve.add_argument("input")
    resolve.add_argument("--confirmed", required=True)
    resolve.add_argument("--unresolved", required=True)
    resolve.add_argument("--decisions", required=True)
    review_tiers = sub.add_parser("plan-review-tiers", help="只读生成候选自动确认与人工审核分层")
    review_tiers.add_argument("input")
    review_tiers.add_argument("--output", required=True)
    review_tiers.add_argument("--summary", required=True)
    impact_review = sub.add_parser("prioritize-review-impact", help="按排名敏感性和证据风险重排人工审核")
    impact_review.add_argument("tiers")
    impact_review.add_argument("sensitivity")
    impact_review.add_argument("--top-n", type=int, default=200)
    impact_review.add_argument("--output", required=True)
    impact_review.add_argument("--summary", required=True)
    resolution_audit = sub.add_parser("audit-resolution-preview", help="校验自动确认预览批次能否冻结")
    resolution_audit.add_argument("candidates")
    resolution_audit.add_argument("confirmed")
    resolution_audit.add_argument("unresolved")
    resolution_audit.add_argument("decisions")
    resolution_audit.add_argument("--output", required=True)
    manual_queue = sub.add_parser("select-manual-review", help="按审核分层筛出需人工签名的候选")
    manual_queue.add_argument("candidates")
    manual_queue.add_argument("tiers")
    manual_queue.add_argument("--output", required=True)
    review_template = sub.add_parser("review-template", help="为未决候选生成人工复核模板")
    review_template.add_argument("input")
    review_template.add_argument("--output", required=True)
    apply_review = sub.add_parser("apply-review", help="校验并应用已签名人工复核决定")
    apply_review.add_argument("input")
    apply_review.add_argument("decisions")
    apply_review.add_argument("--confirmed", required=True)
    apply_review.add_argument("--unresolved", required=True)
    apply_conflict_review = sub.add_parser("apply-conflict-review", help="严格应用带时区签名的冲突复核决定并输出审计")
    apply_conflict_review.add_argument("input")
    apply_conflict_review.add_argument("decisions")
    apply_conflict_review.add_argument("--confirmed", required=True)
    apply_conflict_review.add_argument("--unresolved", required=True)
    apply_conflict_review.add_argument("--audit", required=True)
    args = parser.parse_args()
    methodology = load_methodology(args.methodology)
    if args.command == "template":
        write_observation_template(args.output)
        return
    if args.command == "universe-audit":
        completed = []
        if args.observations:
            completed = {item.company_code for item in read_observations(args.observations, methodology)}
        report = audit_universe(read_universe(args.universe), args.expected_companies, completed)
        write_universe_audit(args.output, report)
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return
    if args.command == "build-universe":
        securities = []
        for snapshot in args.snapshots:
            securities.extend(read_exchange_snapshot(snapshot))
        decisions = build_energy_universe(securities)
        write_universe(args.output, decisions)
        write_decision_audit(args.audit, decisions)
        included = sum(item.included for item in decisions)
        print(f"processed {len(decisions)} securities; included {included}; excluded {len(decisions) - included}")
        return
    if args.command == "normalize-snapshot":
        securities = normalize_exchange_export(args.input, args.exchange, args.source_url, args.as_of_date)
        quality = audit_snapshot(securities)
        write_exchange_snapshot(args.output, securities)
        write_snapshot_quality(args.quality, quality)
        print(json.dumps(quality.as_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if quality.valid else 2)
    if args.command == "discover-listings":
        if "{page}" not in args.endpoint_template:
            raise SystemExit("--endpoint-template 必须包含 {page} 占位符")
        securities = collect_listing_pages(
            args.exchange, args.referer, args.as_of_date,
            lambda page: fetch_json(args.endpoint_template.format(page=page), args.referer),
        )
        quality = audit_snapshot(securities)
        write_exchange_snapshot(args.output, securities)
        write_snapshot_quality(args.quality, quality)
        print(json.dumps(quality.as_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if quality.valid else 2)
    if args.command == "merge-snapshots":
        securities = []
        for snapshot in args.snapshots:
            securities.extend(read_exchange_snapshot(snapshot))
        quality = audit_snapshot(securities)
        write_exchange_snapshot(args.output, securities)
        write_snapshot_quality(args.quality, quality)
        print(json.dumps(quality.as_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if quality.valid else 2)
    if args.command == "import-listing-json":
        payload = Path(args.input).read_bytes()
        securities = collect_listing_pages(
            args.exchange, args.source_url, args.as_of_date, lambda page: payload,
        )
        quality = audit_snapshot(securities)
        write_exchange_snapshot(args.output, securities)
        write_snapshot_quality(args.quality, quality)
        print(json.dumps(quality.as_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(0 if quality.valid else 2)
    if args.command == "import-hkex-list":
        securities, as_of_date = import_hkex_securities(
            args.input, args.source_url, args.as_of_date,
        )
        quality = audit_snapshot(securities)
        write_exchange_snapshot(args.output, securities)
        write_snapshot_quality(args.quality, quality)
        print(json.dumps({"file_as_of_date": as_of_date, **quality.as_dict()}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if quality.valid else 2)
    if args.command == "discover-hkex-profiles":
        codes = [
            item.stock_code for item in read_universe(args.universe)
            if item.included and item.exchange == "HKEX"
        ]
        if args.limit > 0:
            codes = codes[:args.limit]
        profiles, payloads = collect_hkex_issuer_profiles(codes)
        write_hkex_issuer_profiles(args.output, args.raw_output, profiles, payloads)
        candidate_count = sum(item.evidence_status == "candidate" for item in profiles)
        print(json.dumps({
            "requested_count": len(codes), "profile_count": len(profiles),
            "candidate_evidence_count": candidate_count,
            "incomplete_count": len(profiles) - candidate_count,
        }, ensure_ascii=False, indent=2))
        return
    if args.command == "prepare-hkex-evidence-review":
        drafts, summary = prepare_hkex_evidence_drafts(
            args.profiles, read_universe(args.universe), args.mapping, args.evidence_date,
        )
        write_hkex_evidence_drafts(args.output, args.summary, drafts, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "audit-hkex-issuer-continuity":
        rows, summary = audit_hkex_issuer_continuity(
            args.historical_registry, args.profiles, args.drafts, args.code_map or (),
        )
        write_issuer_continuity_audit(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "plan-hkex-continuity-evidence":
        tasks, summary = plan_continuity_evidence_tasks(args.continuity_audit)
        write_continuity_evidence_tasks(args.output, args.summary, tasks, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "discover-hkex-continuity-documents":
        with Path(args.tasks).open(encoding="utf-8-sig", newline="") as stream:
            task_rows = list(csv.DictReader(stream))
        if args.limit > 0:
            task_rows = task_rows[:args.limit]
        failure_path = args.failures or str(Path(args.output).with_name(Path(args.output).stem + "_failures.csv"))
        _, failures, summary = discover_hkex_continuity_batch(
            [task["stock_code"] for task in task_rows], args.from_date, args.to_date,
            args.output, args.raw_output, failure_path, args.delay, args.resume,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(0 if not failures else 2)
    if args.command == "prepare-hkex-continuity-downloads":
        rows, summary = select_continuity_downloads(
            read_hkex_disclosures(args.discoveries), args.report_year, args.annual_only,
        )
        write_hkex_disclosures(args.output, rows)
        summary_output = Path(args.summary)
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "extract-hkex-continuity-evidence":
        rows, summary = extract_continuity_evidence_candidates(
            args.document_index, args.text_root, args.max_per_category,
        )
        write_continuity_evidence_candidates(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "prepare-hkex-continuity-review":
        rows, summary = prepare_continuity_review_packets(args.tasks, args.candidates)
        write_continuity_review_packets(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "render-hkex-continuity-review":
        guide, summary = render_continuity_review_guide(args.packets, args.candidates)
        write_continuity_review_guide(args.output, args.summary, guide, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "select-hkex-continuity-review-batch":
        packets, candidates, summary = select_continuity_review_batch(
            args.packets, args.candidates, args.max_priority,
        )
        write_continuity_review_batch(
            args.output_packets, args.output_candidates, args.summary,
            packets, candidates, summary,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "finalize-hkex-continuity-review":
        decisions, audits, summary = finalize_continuity_reviews(args.packets, args.candidates)
        write_finalized_continuity_reviews(
            args.output, args.audit, args.summary, decisions, audits, summary,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "apply-hkex-continuity-decisions":
        rows, decisions, summary = apply_issuer_continuity_decisions(
            read_universe(args.universe), args.continuity_audit, args.decisions,
        )
        write_applied_continuity_decisions(
            args.output, args.audit, args.summary, rows, decisions, summary,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "discover-bse-listings":
        securities, as_of_date, raw_pages = collect_bse_listings(
            make_bse_fetcher(), BSE_LIST_PAGE, args.as_of_date,
        )
        quality = audit_snapshot(securities)
        write_exchange_snapshot(args.output, securities)
        write_snapshot_quality(args.quality, quality)
        raw_output = Path(args.raw_output)
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_text(json.dumps({
            "source_url": BSE_LIST_PAGE, "as_of_date": as_of_date,
            "pages": [payload.decode("utf-8-sig") for payload in raw_pages],
        }, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"file_as_of_date": as_of_date, **quality.as_dict()}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if quality.valid else 2)
    if args.command == "import-bse-code-map":
        mappings = parse_bse_code_mapping(Path(args.input).read_bytes())
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=tuple(mappings[0].__annotations__))
            writer.writeheader()
            writer.writerows(vars(item) for item in mappings)
        print(json.dumps({"mapping_count": len(mappings)}, ensure_ascii=False, indent=2))
        return
    if args.command == "extract-reference-codes":
        aliases = _read_code_maps(args.code_map or [])
        rows = extract_reference_securities(args.ocr, read_universe(args.snapshot), args.pages, aliases)
        write_reference_securities(args.output, rows)
        matched = sum(item.matched_snapshot for item in rows)
        counts = {exchange: sum(item.exchange == exchange for item in rows) for exchange in ("SSE", "SZSE", "BSE", "HKEX")}
        print(json.dumps({"security_count": len(rows), "snapshot_matched": matched, "exchanges": counts}, ensure_ascii=False, indent=2))
        return
    if args.command == "reconcile-registry":
        rows = reconcile_registry(
            args.input, read_universe(args.snapshot), args.source_name,
            args.source_url, args.as_of_date,
        )
        write_registry_reconciliation(args.output, rows)
        counts = {status: sum(item.match_status == status for item in rows) for status in ("matched", "review", "ambiguous", "unmatched")}
        print(json.dumps({"row_count": len(rows), **counts}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if not counts["review"] and not counts["ambiguous"] and not counts["unmatched"] else 2)
    if args.command == "import-historical-workbook":
        companies, observations, audit = import_historical_workbook(
            args.input, read_universe(args.snapshot), args.evaluation_year, args.report_year,
        )
        write_historical_import(
            args.companies, args.observations, args.audit, companies, observations, audit,
        )
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return
    if args.command == "plan-universe-migration":
        rows, audit = plan_historical_migration(
            args.historical_registry, read_universe(args.snapshot),
            _read_code_maps(args.code_map or []),
        )
        write_migration_plan(args.output, args.audit, rows, audit)
        if args.candidate_universe:
            write_candidate_universe(args.candidate_universe, rows)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return
    if args.command == "augment-universe":
        rows = augment_candidate_universe(
            read_universe(args.base), args.additions, args.snapshot,
        )
        write_augmented_universe(args.output, rows)
        print(json.dumps({"company_count": sum(item.included for item in rows)}, ensure_ascii=False, indent=2))
        return
    if args.command == "bind-universe-provenance":
        rows, bindings, summary = bind_snapshot_provenance(
            read_universe(args.universe), args.snapshot,
        )
        write_provenance_binding(args.output, args.audit, args.summary, rows, bindings, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(0 if summary["complete"] else 2)
    if args.command == "plan-universe-evidence":
        tasks, summary = plan_universe_evidence(
            read_universe(args.universe), args.snapshot, args.exchange or (),
        )
        write_universe_evidence_plan(args.output, args.summary, tasks, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "merge-universe-evidence":
        active_rows, ledger, summary = merge_universe_evidence_batches(args.batches)
        write_universe_evidence_ledger(
            args.active_output, args.ledger_output, args.summary, active_rows, ledger, summary,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "apply-universe-evidence":
        rows, audit_rows, summary = apply_universe_evidence(
            read_universe(args.universe), args.decisions,
        )
        write_applied_universe_evidence(args.output, args.audit, args.summary, rows, audit_rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "plan-collection":
        tasks = plan_collection(
            read_universe(args.universe), read_document_records(args.document_index), args.report_year,
        )
        summary = collection_summary(tasks)
        write_collection_plan(args.output, tasks)
        write_collection_summary(args.summary, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "plan-indicators":
        tasks, summary = plan_indicator_tasks(
            read_universe(args.universe), read_observations(args.observations, methodology),
            methodology, args.report_year,
        )
        write_indicator_plan(args.output, args.summary, tasks, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "audit-completion":
        report = audit_project_completion(
            args.documents, args.quantitative, args.qualitative, args.resolution,
            args.expected_companies,
        )
        write_completion_report(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if args.command == "build-evidence-graph":
        methodology = load_methodology(args.methodology)
        graph, summary = build_evidence_constraint_graph(
            read_observations(args.input, methodology), methodology,
        )
        write_evidence_constraint_graph(args.output, args.summary, graph, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "plan-candidate-coverage":
        rows, summary = plan_candidate_coverage(
            args.companies, read_observations(args.candidates, methodology), methodology,
        )
        write_candidate_coverage(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "init-db":
        repo = SQLiteRepository(args.path)
        repo.initialize()
        print(f"initialized {args.path}")
        return
    if args.command == "discover-sse":
        if args.failures or args.summary or args.resume:
            if not args.failures or not args.summary:
                raise ValueError("批量断点模式必须同时提供--failures和--summary")
            companies = [
                (company.stock_code, company.company_name) for company in read_universe(args.universe)
                if company.included and company.exchange == "SSE"
            ]
            _, failures, summary = discover_szse_batch(
                companies, args.report_year, args.output, args.failures, args.summary,
                args.delay, args.resume, discover_reports, args.workers,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            raise SystemExit(0 if not failures else 2)
        rows = []
        for company in read_universe(args.universe):
            if not company.included or company.exchange != "SSE":
                continue
            for item in discover_reports(company.stock_code, args.report_year):
                rows.append({
                    "company_code": item.stock_code, "company_name": item.company_name,
                    "report_year": args.report_year, "document_type": item.document_type,
                    "source_url": item.source_url, "published_date": item.published_date,
                    "title": item.title,
                })
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("company_code", "company_name", "report_year", "document_type", "source_url", "published_date", "title"))
            writer.writeheader(); writer.writerows(rows)
        print(f"discovered {len(rows)} official reports")
        return
    if args.command == "discover-szse":
        if args.failures or args.summary or args.resume:
            if not args.failures or not args.summary:
                raise ValueError("批量断点模式必须同时提供--failures和--summary")
            companies = [
                (company.stock_code, company.company_name) for company in read_universe(args.universe)
                if company.included and company.exchange == "SZSE"
            ]
            _, failures, summary = discover_szse_batch(
                companies, args.report_year, args.output, args.failures, args.summary,
                args.delay, args.resume, workers=args.workers,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            raise SystemExit(0 if not failures else 2)
        rows = []
        for company in read_universe(args.universe):
            if not company.included or company.exchange != "SZSE":
                continue
            for item in discover_szse_reports(company.stock_code, args.report_year):
                rows.append({
                    "company_code": item.stock_code, "company_name": item.company_name,
                    "report_year": args.report_year, "document_type": item.document_type,
                    "source_url": item.source_url, "published_date": item.published_date, "title": item.title,
                })
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
            fields = ("company_code", "company_name", "report_year", "document_type", "source_url", "published_date", "title")
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        print(f"discovered {len(rows)} official SZSE reports")
        return
    if args.command == "discover-bse":
        rows, failures = [], []
        for company in read_universe(args.universe):
            if not company.included or company.exchange != "BSE":
                continue
            try:
                reports = discover_bse_annual_report(company.stock_code, args.report_year)
                if not reports:
                    raise ValueError("official annual report not found")
                rows.extend({
                    "company_code": item.stock_code, "company_name": item.company_name,
                    "report_year": args.report_year, "document_type": item.document_type,
                    "source_url": item.source_url, "published_date": item.published_date,
                    "title": item.title,
                } for item in reports)
            except Exception as error:
                failures.append({"company_code": company.stock_code, "company_name": company.company_name, "error": str(error)})
        fields = ("company_code", "company_name", "report_year", "document_type", "source_url", "published_date", "title")
        output_path = Path(args.output); output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
        failure_path = Path(args.failures); failure_path.parent.mkdir(parents=True, exist_ok=True)
        with failure_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("company_code", "company_name", "error"), lineterminator="\n"); writer.writeheader(); writer.writerows(failures)
        print(f"discovered {len(rows)} official BSE annual reports; failed {len(failures)}")
        raise SystemExit(0 if not failures else 2)
    if args.command == "collect":
        if args.resume:
            failure_path = args.failures or str(Path(args.index).with_name("collection_failures.csv"))
            records, failures = collect_batch(
                args.manifest, args.output_root, args.index, failure_path, args.delay, True,
                args.workers,
                args.reuse_index,
                args.preserve_index,
            )
            print(f"collected {len(records)} documents; failed {len(failures)}")
            raise SystemExit(0 if not failures else 2)
        records = collect_from_manifest(args.manifest, args.output_root, args.delay)
        write_document_index(args.index, records)
        print(f"collected {len(records)} documents")
        return
    if args.command == "supersede-documents":
        records, ledger_rows, summary = supersede_documents(
            args.document_index, args.requests, args.archive_root, args.ledger, args.summary,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "merge-document-indexes":
        records, summary = merge_document_indexes(args.indexes, args.allow_metadata_corrections)
        write_document_index(args.output, records)
        summary_output = Path(args.summary)
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "audit-document-coverage":
        rows, summary = audit_document_coverage(args.companies, args.document_index, args.report_year)
        write_document_coverage(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "scan-annual-esg-disclosure":
        rows, summary = scan_annual_esg_disclosure(
            args.coverage, args.document_index, args.text_root, args.max_per_company,
        )
        write_annual_esg_evidence(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "collect-annual-qualitative-evidence":
        methodology = load_methodology(args.methodology)
        rows, summary = collect_annual_qualitative_evidence(
            args.coverage, args.document_index, args.text_root, methodology,
            args.report_year, args.max_per_indicator,
        )
        write_qualitative_evidence_candidates(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "collect-esg-qualitative-evidence":
        methodology = load_methodology(args.methodology)
        rows, summary = collect_esg_qualitative_evidence(
            args.coverage, args.document_index, args.text_root, methodology,
            args.report_year, args.max_per_indicator,
        )
        write_qualitative_evidence_candidates(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "merge-qualitative-candidates":
        rows, summary = merge_qualitative_candidate_files(args.inputs)
        write_qualitative_candidates(args.output, rows)
        merge_summary_path = Path(args.summary)
        merge_summary_path.parent.mkdir(parents=True, exist_ok=True)
        merge_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "plan-qualitative-review":
        methodology = load_methodology(args.methodology)
        packets, gaps, summary = plan_qualitative_review(
            read_qualitative_candidates(args.candidates), args.coverage,
            methodology, args.report_year,
        )
        write_qualitative_review_plan(args.packets, args.gaps, args.summary, packets, gaps, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "qualitative-review-template":
        count = write_qualitative_review_template(
            args.output, read_qualitative_review_packets(args.packets), args.priority, args.limit,
        )
        print(f"qualitative review template groups {count}")
        return
    if args.command == "apply-qualitative-review":
        confirmed, unresolved, audits = apply_qualitative_review_decisions(
            read_qualitative_review_packets(args.packets),
            read_qualitative_review_decisions(args.decisions),
        )
        write_observations(args.confirmed, confirmed)
        write_qualitative_review_results(args.unresolved, args.audit, unresolved, audits)
        print(json.dumps({
            "confirmed_count": len(confirmed), "unresolved_count": len(unresolved),
            "audit_count": len(audits), "complete": not unresolved,
        }, ensure_ascii=False, indent=2))
        return
    if args.command == "qualitative-review-batch":
        batch = create_review_batch(
            read_qualitative_review_packets(args.packets), args.output, args.ledger,
            args.packets, args.label, args.priority, args.limit,
        )
        print(json.dumps({
            "batch_id": batch.batch_id, "group_count": batch.group_count,
            "keys_sha256": batch.keys_sha256, "status": batch.status,
        }, ensure_ascii=False, indent=2))
        return
    if args.command == "apply-qualitative-batch":
        batch_id, batch_rows = read_batch_rows(args.batch_file)
        ledger = read_batch_ledger(args.ledger)
        progress = read_review_progress(args.progress, batch_id)
        confirmed, unresolved, audits, updated = apply_review_batch(
            read_qualitative_review_packets(args.packets), ledger, batch_id, batch_rows, progress,
        )
        write_observations(args.confirmed, confirmed)
        write_qualitative_review_results(args.unresolved, args.audit, unresolved, audits)
        write_review_progress(args.progress, batch_id, progress + audits)
        write_batch_ledger(args.ledger, update_ledger_entry(ledger, updated))
        print(json.dumps({
            "batch_id": batch_id, "confirmed_count": len(confirmed),
            "unresolved_count": len(unresolved), "decided_count": updated.decided_count,
            "completion_rate": updated.completion_rate, "status": updated.status,
        }, ensure_ascii=False, indent=2))
        return
    if args.command == "select-dual-review":
        cases = select_dual_review_cases(
            read_qualitative_review_packets(args.packets),
            read_qualitative_review_audits(args.audits),
        )
        count = write_dual_review_template(args.output, cases)
        print(json.dumps({"dual_review_case_count": count}, ensure_ascii=False, indent=2))
        return
    if args.command == "apply-dual-review":
        cases = select_dual_review_cases(
            read_qualitative_review_packets(args.packets),
            read_qualitative_review_audits(args.audits),
        )
        confirmed, outcomes, arbitrations, open_cases = apply_dual_review_decisions(
            cases, read_dual_review_decisions(args.decisions),
        )
        write_observations(args.confirmed, confirmed)
        write_dual_review_results(args.outcomes, args.arbitration, args.open, outcomes, arbitrations, open_cases)
        print(json.dumps({
            "confirmed_count": len(confirmed), "closed_count": sum(item.outcome == "closed_agreement" for item in outcomes),
            "arbitration_count": len(arbitrations), "open_count": len(open_cases),
        }, ensure_ascii=False, indent=2))
        return
    if args.command == "apply-qualitative-arbitration":
        confirmed, unresolved, audits = apply_arbitration_decisions(
            read_arbitration_cases(args.arbitration_file),
            read_arbitration_decisions(args.arbitration_file),
        )
        write_observations(args.confirmed, confirmed)
        write_arbitration_results(args.unresolved, args.audit, unresolved, audits)
        print(json.dumps({
            "confirmed_count": len(confirmed), "unresolved_count": len(unresolved),
            "audit_count": len(audits), "complete": not unresolved,
        }, ensure_ascii=False, indent=2))
        return
    if args.command == "reprioritize-qualitative-gaps":
        rows, summary = reprioritize_evidence_gaps(args.gaps, args.coverage)
        write_reprioritized_gaps(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "merge-confirmed-observations":
        methodology = load_methodology(args.methodology)
        rows, summary = merge_confirmed_observations(args.inputs, methodology)
        write_observations(args.output, rows)
        summary_output = Path(args.summary)
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "derive-financial":
        observations = derive_financial_observations(read_financial_facts(args.input))
        write_observations(args.output, observations)
        print(f"derived {len(observations)} observations")
        return
    if args.command == "extract-pdf":
        candidates = extract_indicator_candidates(
            extract_pdf_text(args.pdf), args.company_code, args.company_name,
            args.report_year, args.source_url, args.pdf,
        )
        write_observations(args.output, candidates)
        print(f"extracted {len(candidates)} pending candidates")
        return
    if args.command == "extract-text":
        candidates = extract_indicator_candidates(
            read_page_text_export(args.text), args.company_code, args.company_name,
            args.report_year, args.source_url, args.source_file,
        )
        write_observations(args.output, candidates)
        print(f"extracted {len(candidates)} pending candidates")
        return
    if args.command == "extract-batch-text":
        candidates, coverage = extract_batch_text_exports(args.document_index, args.text_root, args.report_year)
        write_observations(args.output, candidates)
        coverage_path = Path(args.coverage)
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.review_summary:
            summaries = summarize_review_candidates(candidates)
            summary_path = Path(args.review_summary)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(ReviewSummary.__annotations__), lineterminator="\n")
                writer.writeheader()
                writer.writerows(vars(item) for item in summaries)
        print(f"extracted {len(candidates)} pending candidates across {len(coverage)} indicators")
        return
    if args.command == "quality":
        report = evaluate_quality(read_observations(args.input, methodology), methodology, args.expected_companies)
        print(json.dumps({
            "publishable": report.publishable, "company_count": report.company_count,
            "observation_count": report.observation_count, "confirmed_count": report.confirmed_count,
            "issues": [vars(issue) for issue in report.issues],
        }, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report.publishable else 2)
    if args.command == "resolve-pending":
        confirmed, unresolved, decisions = resolve_pending_candidates(read_observations(args.input, methodology))
        write_observations(args.confirmed, confirmed)
        write_observations(args.unresolved, unresolved)
        decision_path = Path(args.decisions)
        decision_path.parent.mkdir(parents=True, exist_ok=True)
        with decision_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=list(type(decisions[0]).__annotations__) if decisions else [],
                lineterminator="\n",
            )
            if decisions:
                writer.writeheader(); writer.writerows(vars(item) for item in decisions)
        print(f"auto-confirmed {len(confirmed)}; unresolved {len(unresolved)}; decisions {len(decisions)}")
        return
    if args.command == "plan-review-tiers":
        rows, summary = plan_review_tiers(read_observations(args.input, methodology))
        write_review_tiers(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "prioritize-review-impact":
        rows, summary = prioritize_review_by_impact(
            read_review_tiers(args.tiers), args.sensitivity,
            load_methodology(args.methodology), args.top_n,
        )
        write_impact_review_plan(args.output, args.summary, rows, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.command == "audit-resolution-preview":
        report = audit_resolution_preview(
            read_observations(args.candidates, methodology),
            read_observations(args.confirmed, methodology),
            read_observations(args.unresolved, methodology),
            read_resolution_decisions(args.decisions),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if args.command == "select-manual-review":
        selected = select_manual_review_candidates(
            read_observations(args.candidates, methodology), read_review_tiers(args.tiers),
        )
        write_observations(args.output, selected)
        print(f"manual review candidates {len(selected)}")
        return
    if args.command == "review-template":
        write_review_template(args.output, read_observations(args.input, methodology))
        print(f"review template written to {args.output}")
        return
    if args.command == "apply-review":
        confirmed, unresolved = apply_review_instructions(
            read_observations(args.input, methodology), read_review_instructions(args.decisions),
        )
        write_observations(args.confirmed, confirmed)
        write_observations(args.unresolved, unresolved)
        print(f"manually confirmed {len(confirmed)}; unresolved {len(unresolved)}")
        return
    if args.command == "apply-conflict-review":
        confirmed, unresolved, audits = apply_conflict_review_instructions(
            read_observations(args.input, methodology), read_review_instructions(args.decisions),
        )
        write_observations(args.confirmed, confirmed)
        write_observations(args.unresolved, unresolved)
        write_review_audit(args.audit, audits)
        print(f"conflict decisions {len(audits)}; confirmed {len(confirmed)}; unresolved {len(unresolved)}")
        return
    observations = read_observations(args.input, methodology)
    mode = "release" if args.release else args.mode
    if args.release and args.mode != "preview":
        raise SystemExit("--release不能与显式--mode同时使用")
    try:
        strategy = validate_ranking_mode(mode, observations, args.missing_strategy).value
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if mode == "release":
        if not args.universe or not args.expected_companies:
            raise SystemExit("正式发布必须同时指定 --universe 和 --expected-companies")
        audit = audit_universe(
            read_universe(args.universe), args.expected_companies,
            {item.company_code for item in observations},
        )
        if not audit.publishable:
            raise SystemExit(
                "公司池未达到正式发布门槛："
                f"样本主体 {audit.included_company_count}/{audit.expected_company_count}，"
                f"已有数据 {audit.completed_company_count}/{audit.expected_company_count}，"
                f"缺少交易所 {','.join(audit.missing_exchanges) or '无'}"
            )
    results = ScoringEngine(methodology).evaluate(observations, strategy)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    title = args.title + ("（自动预排名·非正式）" if mode == "research" else "")
    write_ranking_csv(output / "ranking.csv", results, methodology)
    write_ranking_json(output / "ranking.json", results)
    write_ranking_html(output / "ranking.html", results, methodology, title)
    metadata = {
        "ranking_mode": mode,
        "algorithm_version": "auto_prerank_v1" if mode == "research" else "energy_esg_2025",
        "missing_strategy_version": strategy,
        "company_count": len(results),
        "input_path": str(Path(args.input)),
        "input_sha256": _sha256_file(args.input),
        "methodology_path": str(Path(args.methodology)),
        "methodology_sha256": _sha256_file(args.methodology),
        "official_release": mode == "release",
        "notice": "正式审计版" if mode == "release" else "自动研究结果，不得作为正式榜单",
    }
    (output / "ranking_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    if mode == "research":
        write_sensitivity_report(
            output / "ranking_sensitivity.json",
            analyze_missing_sensitivity(observations, methodology),
        )
    print(f"scored {len(results)} companies in {mode} mode; files written to {output}")


def _read_code_maps(paths: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows or not {"old_code", "new_code"}.issubset(rows[0]):
            raise ValueError("代码映射CSV缺少old_code/new_code字段")
        for row in rows:
            old = row["old_code"].strip().upper()
            new = row["new_code"].strip().upper()
            if old in aliases and aliases[old] != new:
                raise ValueError(f"代码映射冲突: {old}")
            aliases[old] = new
    return aliases


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
