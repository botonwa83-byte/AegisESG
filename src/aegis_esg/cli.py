from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .collector import collect_batch, collect_from_manifest, write_document_index
from .extraction import extract_batch_text_exports, extract_indicator_candidates, extract_pdf_text, read_page_text_export, summarize_review_candidates
from .financial import derive_financial_observations, read_financial_facts
from .historical import import_historical_workbook, write_historical_import
from .indicator_plan import plan_indicator_tasks, write_indicator_plan
from .issuer_continuity import apply_issuer_continuity_decisions, audit_hkex_issuer_continuity, plan_continuity_evidence_tasks, write_applied_continuity_decisions, write_continuity_evidence_tasks, write_issuer_continuity_audit
from .io import read_observations, write_observation_template, write_observations, write_ranking_csv, write_ranking_html, write_ranking_json
from .methodology import load_methodology
from .migration import augment_candidate_universe, bind_snapshot_provenance, plan_historical_migration, write_augmented_universe, write_candidate_universe, write_migration_plan, write_provenance_binding
from .planning import collection_summary, plan_collection, read_document_records, write_collection_plan, write_collection_summary
from .quality import evaluate_quality
from .repository import SQLiteRepository
from .resolution import resolve_pending_candidates
from .review import apply_review_instructions, read_review_instructions, write_review_template
from .reference import extract_reference_securities, write_reference_securities
from .registry import reconcile_registry, write_registry_reconciliation
from .scoring import ScoringEngine
from .sources.sse import discover_reports
from .sources.listings import collect_listing_pages, fetch_json
from .sources.hkex import import_hkex_securities
from .sources.hkex_profile import collect_hkex_issuer_profiles, prepare_hkex_evidence_drafts, write_hkex_evidence_drafts, write_hkex_issuer_profiles
from .sources.bse import BSE_LIST_PAGE, collect_bse_listings, make_bse_fetcher, parse_bse_code_mapping
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
    score = sub.add_parser("score", help="从CSV自动计算并导出排名")
    score.add_argument("input")
    score.add_argument("--output-dir", default="output")
    score.add_argument("--title", default="中国能源上市公司可持续发展（ESG）评价前200名单")
    score.add_argument("--universe", help="正式发布时使用的公司池CSV")
    score.add_argument("--expected-companies", type=int, help="正式发布目标公司主体数")
    score.add_argument("--release", action="store_true", help="启用完整样本发布门槛")
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
    database = sub.add_parser("init-db", help="初始化本地审计数据库")
    database.add_argument("path", default="var/aegis.db", nargs="?")
    discover = sub.add_parser("discover-sse", help="从上交所官方接口发现年报和ESG报告")
    discover.add_argument("universe")
    discover.add_argument("--report-year", type=int, required=True)
    discover.add_argument("--output", required=True)
    collect = sub.add_parser("collect", help="下载审核后的公开报告清单并生成Hash索引")
    collect.add_argument("manifest")
    collect.add_argument("--output-root", default="data/raw")
    collect.add_argument("--index", default="data/raw/document_index.csv")
    collect.add_argument("--delay", type=float, default=1.0)
    collect.add_argument("--failures")
    collect.add_argument("--resume", action="store_true", help="复用有效本地PDF并逐项写入检查点")
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
    quality = sub.add_parser("quality", help="检查正式评分数据是否达到发布门槛")
    quality.add_argument("input")
    quality.add_argument("--expected-companies", type=int)
    resolve = sub.add_parser("resolve-pending", help="按审计策略自动确认无歧义候选")
    resolve.add_argument("input")
    resolve.add_argument("--confirmed", required=True)
    resolve.add_argument("--unresolved", required=True)
    resolve.add_argument("--decisions", required=True)
    review_template = sub.add_parser("review-template", help="为未决候选生成人工复核模板")
    review_template.add_argument("input")
    review_template.add_argument("--output", required=True)
    apply_review = sub.add_parser("apply-review", help="校验并应用已签名人工复核决定")
    apply_review.add_argument("input")
    apply_review.add_argument("decisions")
    apply_review.add_argument("--confirmed", required=True)
    apply_review.add_argument("--unresolved", required=True)
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
    if args.command == "init-db":
        repo = SQLiteRepository(args.path)
        repo.initialize()
        print(f"initialized {args.path}")
        return
    if args.command == "discover-sse":
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
    if args.command == "collect":
        if args.resume:
            failure_path = args.failures or str(Path(args.index).with_name("collection_failures.csv"))
            records, failures = collect_batch(
                args.manifest, args.output_root, args.index, failure_path, args.delay, True,
            )
            print(f"collected {len(records)} documents; failed {len(failures)}")
            raise SystemExit(0 if not failures else 2)
        records = collect_from_manifest(args.manifest, args.output_root, args.delay)
        write_document_index(args.index, records)
        print(f"collected {len(records)} documents")
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
        candidates, coverage = extract_batch_text_exports(args.document_index, args.text_root)
        write_observations(args.output, candidates)
        coverage_path = Path(args.coverage)
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.review_summary:
            summaries = summarize_review_candidates(candidates)
            summary_path = Path(args.review_summary)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(type(summaries[0]).__annotations__) if summaries else [])
                if summaries:
                    writer.writeheader(); writer.writerows(vars(item) for item in summaries)
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
            writer = csv.DictWriter(stream, fieldnames=list(type(decisions[0]).__annotations__) if decisions else [])
            if decisions:
                writer.writeheader(); writer.writerows(vars(item) for item in decisions)
        print(f"auto-confirmed {len(confirmed)}; unresolved {len(unresolved)}; decisions {len(decisions)}")
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
    observations = read_observations(args.input, methodology)
    if args.release:
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
    results = ScoringEngine(methodology).evaluate(observations)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_ranking_csv(output / "ranking.csv", results, methodology)
    write_ranking_json(output / "ranking.json", results)
    write_ranking_html(output / "ranking.html", results, methodology, args.title)
    print(f"scored {len(results)} companies; files written to {output}")


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


if __name__ == "__main__":
    main()
