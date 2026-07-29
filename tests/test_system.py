import csv
import tempfile
import unittest
import gzip
import urllib.parse
from decimal import Decimal
from pathlib import Path

from aegis_esg.io import write_ranking_csv
from aegis_esg.methodology import load_methodology
from aegis_esg.models import Direction, Indicator, IndicatorKind, Observation, ValueStatus
from aegis_esg.scoring import PopulationStats, ScoringEngine
from aegis_esg.repository import SQLiteRepository
from aegis_esg.extraction import PageText, extract_batch_text_exports, extract_indicator_candidates, read_page_text_export, summarize_review_candidates
from aegis_esg.financial import FinancialFact, derive_financial_observations
from aegis_esg.quality import evaluate_quality
from aegis_esg.resolution import resolve_pending_candidates
from aegis_esg.review import ReviewInstruction, apply_review_instructions
from aegis_esg.sources.sse import classify_title, discover_reports, parse_response
from aegis_esg.sources.listings import collect_listing_pages, parse_listing_page
from aegis_esg.sources.hkex import import_hkex_securities
from aegis_esg.sources.hkex_profile import collect_hkex_issuer_profiles, parse_hkex_access_token, parse_hkex_quote_payload
from aegis_esg.sources.bse import collect_bse_listings, parse_bse_code_mapping, parse_bse_page
from aegis_esg.collector import DocumentRecord, _decode_document, _download_candidates, _read_document_index, write_document_index
from aegis_esg.universe import UniverseCompany, audit_universe
from aegis_esg.universe_builder import ExchangeSecurity, audit_snapshot, build_energy_universe, normalize_exchange_export, normalize_stock_code, read_exchange_snapshot, write_universe
from aegis_esg.reference import extract_reference_securities
from aegis_esg.registry import normalize_company_name, reconcile_registry
from aegis_esg.planning import collection_summary, plan_collection
from aegis_esg.historical import import_historical_workbook
from aegis_esg.migration import augment_candidate_universe, bind_snapshot_provenance, plan_historical_migration, write_candidate_universe
from aegis_esg.indicator_plan import plan_indicator_tasks
from aegis_esg.universe_review import apply_universe_evidence, merge_universe_evidence_batches, plan_universe_evidence


ROOT = Path(__file__).resolve().parents[1]


class MethodologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.methodology = load_methodology(ROOT / "data/methodologies/energy_esg_2025.json")

    def test_methodology_matches_report(self):
        self.assertEqual(37, len(self.methodology.quantitative))
        self.assertEqual(43, len(self.methodology.qualitative))
        self.assertAlmostEqual(100, sum(i.weight for i in self.methodology.quantitative))
        self.assertAlmostEqual(100, sum(i.weight for i in self.methodology.qualitative))
        self.assertEqual(10, sum(i.key_indicator for i in self.methodology.quantitative))

    def test_normal_direction(self):
        engine = ScoringEngine(self.methodology)
        stat = PopulationStats(3, 10, 2)
        positive = Indicator("P", "E", "x", "x", IndicatorKind.QUANTITATIVE, 100, Direction.POSITIVE)
        negative = Indicator("N", "E", "x", "x", IndicatorKind.QUANTITATIVE, 100, Direction.NEGATIVE)
        self.assertGreater(engine._score_value(positive, 12, stat), engine._score_value(positive, 8, stat))
        self.assertGreater(engine._score_value(negative, 8, stat), engine._score_value(negative, 12, stat))

    def test_evaluation_dense_rank_and_export_shape(self):
        observations = []
        for code, name, offset in (("A", "甲公司", 0), ("B", "乙公司", 1), ("C", "丙公司", 1)):
            for index, indicator in enumerate(self.methodology.indicators):
                if indicator.kind == IndicatorKind.QUALITATIVE:
                    value = 80 if offset == 0 else 50
                elif indicator.direction == Direction.NEGATIVE:
                    value = 10 + index + offset
                elif indicator.direction == Direction.BIDIRECTIONAL:
                    value = 50 + offset
                else:
                    value = 50 + index - offset
                observations.append(Observation(code, name, 2024, indicator.code, value))
        results = ScoringEngine(self.methodology).evaluate(observations)
        self.assertEqual([1, 2, 2], [r.rank for r in results])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ranking.csv"
            write_ranking_csv(output, results, self.methodology)
            with output.open(encoding="utf-8-sig") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(7, len(rows))
            self.assertEqual(15, len(rows[0]))
            self.assertEqual("数值类别", rows[0][3])
            self.assertEqual("指标数值", rows[1][3])
            self.assertEqual("指标分值", rows[2][3])

    def test_observation_revision_keeps_audit_history(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = SQLiteRepository(Path(directory) / "audit.db")
            repo.initialize()
            first = Observation("A", "甲公司", 2024, "Q_E_GHG_INTENSITY", 10)
            second = Observation("A", "甲公司", 2024, "Q_E_GHG_INTENSITY", 8)
            repo.upsert_observations([first])
            repo.upsert_observations([second])
            latest = repo.confirmed_observations(2024)
            self.assertEqual(1, len(latest))
            self.assertEqual(8, latest[0].value)
            count = repo.connection.execute("SELECT COUNT(*) FROM observation").fetchone()[0]
            self.assertEqual(2, count)

    def test_sse_official_response_classification(self):
        payload = '{"result":[' \
            '{"SECURITY_CODE":"600900","SECURITY_NAME":"长江电力","SSEDATE":"2026-04-30",' \
            '"TITLE":"长江电力2025年年度报告","URL":"/annual.pdf"},' \
            '{"SECURITY_CODE":"600900","SECURITY_NAME":"长江电力","SSEDATE":"2026-04-30",' \
            '"TITLE":"长江电力2025年度环境、社会和公司治理报告","URL":"/esg.pdf"}' \
            ']}'
        parsed = parse_response(payload)
        self.assertEqual("https://www.sse.com.cn/annual.pdf", parsed[0].source_url)
        self.assertEqual("annual_report", classify_title(parsed[0].title, "2025"))
        self.assertEqual("esg_report", classify_title(parsed[1].title, "2025"))

        def fetcher(_request):
            return payload.encode()
        reports = discover_reports("600900.SH", 2025, fetcher=fetcher)
        self.assertEqual({"annual_report", "esg_report"}, {item.document_type for item in reports})

    def test_financial_derivation(self):
        def fact(code, value):
            return FinancialFact("600900.SH", "长江电力", 2025, code, Decimal(value), "https://official/report.pdf")
        facts = [
            fact("net_profit", "120"), fact("equity_begin", "900"), fact("equity_end", "1100"),
            fact("liabilities_end", "600"), fact("assets_end", "1500"),
            fact("cash_dividend_total", "50"), fact("total_shares", "100"),
            fact("environmental_investment", "2"), fact("revenue", "200"),
        ]
        values = {item.indicator_code: item.value for item in derive_financial_observations(facts)}
        self.assertAlmostEqual(12, values["Q_G_ROE"])
        self.assertAlmostEqual(40, values["Q_G_DEBT_ASSET_RATE"])
        self.assertAlmostEqual(.5, values["Q_S_DIVIDEND_PER_SHARE"])
        self.assertAlmostEqual(1, values["Q_S_ENV_INVEST_RATE"])

    def test_text_extraction_is_pending_and_converts_units(self):
        pages = [PageText(12, "2025年水资源使用强度为0.81立方米/万元，研发投入占比2.85%。")]
        items = extract_indicator_candidates(pages, "600900.SH", "长江电力", 2025, "https://official/esg.pdf", "esg.pdf")
        values = {item.indicator_code: item for item in items}
        self.assertEqual(810, values["Q_E_WATER_INTENSITY"].value)
        self.assertEqual("pending", values["Q_E_WATER_INTENSITY"].status.value)
        self.assertAlmostEqual(2.85, values["Q_S_RD_RATE"].value)

    def test_page_text_export_preserves_page_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.txt"
            path.write_text("\n=== PAGE 7 ===\n披露文本\n", encoding="utf-8")
            self.assertEqual([PageText(7, "披露文本\n")], read_page_text_export(path))

    def test_batch_text_extraction_reports_company_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "text/A/2025/esg_report.txt"
            text.parent.mkdir(parents=True)
            text.write_text("\n=== PAGE 2 ===\n资产负债率58.2%\n", encoding="utf-8")
            index = root / "index.csv"
            record = DocumentRecord("A", "甲", 2025, "esg_report", "https://source", "https://retrieval", "data/raw/A/2025/esg_report.pdf", "abc", 12)
            write_document_index(index, [record])
            items, coverage = extract_batch_text_exports(index, root / "text")
            self.assertEqual(1, len(items))
            self.assertEqual(
                {"Q_G_DEBT_ASSET_RATE": {"candidate_count": 1, "company_count": 1}},
                coverage,
            )

    def test_debt_ratio_excludes_guarantee_threshold_and_formula(self):
        pages = [PageText(1, "资产负债率超过70%的被担保对象；资产负债率＝负债/资产×100%；期末资产负债率58.2%。")]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "a.pdf")
        self.assertEqual([58.2], [item.value for item in items if item.indicator_code == "Q_G_DEBT_ASSET_RATE"])

    def test_intensity_excludes_table_footnote_as_value(self):
        pages = [PageText(1, "温室气体排放强度3 吨二氧化碳当量/万元 0.02 0.03")]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "esg.pdf")
        self.assertFalse([item for item in items if item.indicator_code == "Q_E_GHG_INTENSITY"])

    def test_standard_annual_report_direct_metrics(self):
        pages = [PageText(8, "加权平均净资产收益率（%）15.90；每10股派息数（元）（含税）10；研发投入总额占营业收入比例（%）2.85")]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "annual.pdf")
        values = {item.indicator_code: item.value for item in items}
        self.assertEqual(15.9, values["Q_G_ROE"])
        self.assertEqual(1, values["Q_S_DIVIDEND_PER_SHARE"])
        self.assertEqual(2.85, values["Q_S_RD_RATE"])

    def test_revenue_growth_uses_main_accounting_table(self):
        pages = [PageText(6, "近三年主要会计数据和财务指标\n（一）主要会计数据\n营业收入 120.00 100.00 20.00\n利润总额 30.00 20.00")]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "annual_report.pdf")
        self.assertEqual([20], [round(item.value, 6) for item in items if item.indicator_code == "Q_G_REVENUE_GROWTH"])

    def test_revenue_growth_repairs_wrapped_numbers_without_joining_columns(self):
        text = "近三年主要会计数据\n（一）主要会计数据\n营业收入 50,363,061,03\n0.51\n52,516,934,87\n3.70\n-4.10\n利润总额 1.00"
        items = extract_indicator_candidates([PageText(6, text)], "A", "甲", 2025, "url", "annual_report.pdf")
        values = [item.value for item in items if item.indicator_code == "Q_G_REVENUE_GROWTH"]
        self.assertAlmostEqual(-4.100, values[0], places=2)

    def test_balance_sheet_turnover_normalizes_summary_ten_thousand_yuan(self):
        pages = [
            PageText(5, "近三年主要会计数据\n（一）主要会计数据\n单位：万元\n营业收入 12.00 10.00\n利润总额 2.00"),
            PageText(80, "合并资产负债表\n资产总计 200000.00 180000.00\n负债合计 80000.00 70000.00"),
            PageText(81, "合并利润表"),
        ]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "annual_report.pdf")
        values = {item.indicator_code: item.value for item in items}
        self.assertAlmostEqual(120000 / 190000, values["Q_G_ASSET_TURNOVER"])

    def test_consolidated_balance_sheet_derives_governance_metrics(self):
        pages = [
            PageText(5, "近三年主要会计数据\n（一）主要会计数据\n营业收入 120.00 100.00\n利润总额 20.00"),
            PageText(80, "合并资产负债表\n应收账款 10.00 8.00\n存货 5.00 4.00\n流动资产合计 40.00 30.00\n资产总计 200.00 180.00\n负债合计 80.00 70.00\n股东权益合计 120.00 110.00"),
            PageText(81, "合并利润表"),
        ]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "annual_report.pdf")
        values = {item.indicator_code: item.value for item in items}
        self.assertAlmostEqual(40, values["Q_G_DEBT_ASSET_RATE"])
        self.assertAlmostEqual(120 / 190, values["Q_G_ASSET_TURNOVER"])
        self.assertAlmostEqual(120 / 9, values["Q_G_AR_TURNOVER"])
        self.assertAlmostEqual(37.5, values["Q_G_TWO_FUNDS_RATE"])
        self.assertAlmostEqual(100 / 11, values["Q_G_CAPITAL_ACCUMULATION"])

    def test_income_and_cashflow_statements_derive_governance_metrics(self):
        pages = [
            PageText(5, "近三年主要会计数据\n（一）主要会计数据\n营业收入 120.00 100.00\n利润总额 20.00"),
            PageText(80, "合并资产负债表\n流动负债合计 50.00 40.00\n资产总计 200.00 180.00"),
            PageText(81, "合并利润表\n营业总成本 70.00 65.00\n其中：利息费用 5.00 4.00\n营业利润 30.00 20.00\n利润总额 25.00 18.00"),
            PageText(82, "母公司利润表"),
            PageText(83, "合并现金流量表\n经营活动现金流入小计 130.00 110.00\n经营活动产生的\n现金流量净额 20.00 18.00"),
            PageText(84, "母公司现金流量表"),
        ]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "annual_report.pdf")
        values = {item.indicator_code: item.value for item in items}
        self.assertAlmostEqual(25, values["Q_G_OPERATING_MARGIN"])
        self.assertAlmostEqual(50, values["Q_G_OPERATING_PROFIT_GROWTH"])
        self.assertAlmostEqual(130 / 120 * 100, values["Q_G_CASH_REALIZATION"])
        self.assertAlmostEqual(40, values["Q_G_CASH_CURRENT_LIABILITY"])
        self.assertAlmostEqual(30 / 190 * 100, values["Q_G_ROA"])

    def test_operating_profit_growth_rejects_next_line_amount_as_prior_year(self):
        pages = [
            PageText(5, "近三年主要会计数据\n营业收入 120.00 100.00\n利润总额 20.00"),
            PageText(80, "合并资产负债表\n资产总计 200.00 180.00"),
            PageText(81, "合并利润表\n营业利润 3000000.00\n加：营业外收入 1000.00\n利润总额 3001000.00"),
            PageText(82, "母公司利润表"),
        ]
        items = extract_indicator_candidates(pages, "A", "甲", 2025, "url", "annual_report.pdf")
        self.assertFalse([item for item in items if item.indicator_code == "Q_G_OPERATING_PROFIT_GROWTH"])

    def test_review_summary_only_recommends_consistent_values(self):
        items = [
            Observation("A", "甲", 2025, "Q_G_ROE", 10, source_page=1),
            Observation("A", "甲", 2025, "Q_G_ROE", 9, source_page=2),
            Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 40, source_page=3),
            Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 40, source_page=4),
        ]
        summaries = {item.indicator_code: item for item in summarize_review_candidates(items)}
        self.assertEqual("", summaries["Q_G_ROE"].recommended_value)
        self.assertEqual("40", summaries["Q_G_DEBT_ASSET_RATE"].recommended_value)

    def test_pending_resolver_confirms_only_consistent_annual_direct_values(self):
        annual = Observation("A", "甲", 2025, "Q_G_ROE", 10, ValueStatus.PENDING, source_file="annual_report.pdf", confidence=.92)
        duplicate = Observation("A", "甲", 2025, "Q_G_ROE", 10, ValueStatus.PENDING, source_file="annual_report.pdf", confidence=.92)
        environmental = Observation("A", "甲", 2025, "Q_E_GHG_INTENSITY", 2, ValueStatus.PENDING, source_file="esg_report.pdf", confidence=.9)
        confirmed, unresolved, decisions = resolve_pending_candidates([annual, duplicate, environmental])
        self.assertEqual(2, len(confirmed))
        self.assertTrue(all(item.status == ValueStatus.CONFIRMED for item in confirmed))
        self.assertFalse(unresolved)
        self.assertEqual({"auto_confirmed"}, {item.decision for item in decisions})

    def test_pending_resolver_accepts_debt_ratio_rounding_tolerance(self):
        items = [
            Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 54.22, ValueStatus.PENDING, source_file="annual_report.pdf", confidence=.9),
            Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 54.2174, ValueStatus.PENDING, source_file="annual_report.pdf", confidence=.94),
        ]
        confirmed, unresolved, _ = resolve_pending_candidates(items)
        self.assertEqual([54.2174], [item.value for item in confirmed])
        self.assertFalse(unresolved)

    def test_pending_resolver_prefers_statement_derived_year_end_debt_ratio(self):
        items = [
            Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 53.76, ValueStatus.PENDING, source_file="annual_report.pdf", evidence_text="期初", confidence=.9),
            Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 57.86, ValueStatus.PENDING, source_file="annual_report.pdf", evidence_text="期末", confidence=.9),
            Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 57.8641, ValueStatus.PENDING, source_file="annual_report.pdf", evidence_text="合并报表自动派生: 负债/资产", confidence=.94),
        ]
        confirmed, unresolved, _ = resolve_pending_candidates(items)
        self.assertEqual([57.8641], [item.value for item in confirmed])
        self.assertFalse(unresolved)

    def test_pending_resolver_confirms_consistent_official_esg_intensity(self):
        item = Observation("A", "甲", 2025, "Q_E_GHG_INTENSITY", 6.68, ValueStatus.PENDING, source_file="esg_report.pdf", confidence=.82)
        confirmed, unresolved, _ = resolve_pending_candidates([item])
        self.assertEqual([6.68], [value.value for value in confirmed])
        self.assertFalse(unresolved)

    def test_manual_review_requires_selected_candidate(self):
        candidate = Observation("A", "甲", 2025, "Q_G_DEBT_ASSET_RATE", 40, ValueStatus.PENDING, source_file="annual.pdf", source_page=3)
        instruction = ReviewInstruction("A", 2025, "Q_G_DEBT_ASSET_RATE", "confirm", "40", "reviewer", "2026-07-28T12:00:00+08:00", "核对年末值")
        confirmed, unresolved = apply_review_instructions([candidate], [instruction])
        self.assertEqual(1, len(confirmed))
        self.assertFalse(unresolved)
        self.assertIn("manual-review:reviewer", confirmed[0].evidence_text)

    def test_quality_gate_rejects_incomplete_dataset(self):
        item = Observation("A", "甲公司", 2025, "Q_G_ROE", 10)
        report = evaluate_quality([item], self.methodology, expected_companies=2)
        self.assertFalse(report.publishable)
        self.assertIn("UNIVERSE_MISMATCH", {issue.code for issue in report.issues})

    def test_universe_audit_deduplicates_entities_and_blocks_partial_release(self):
        companies = [
            UniverseCompany("600001.SH", "甲", "SSE", "电力", entity_id="ENTITY-A"),
            UniverseCompany("00001.HK", "甲", "HKEX", "电力", False, "A/H去重", "ENTITY-A"),
            UniverseCompany("000002.SZ", "乙", "SZSE", "能源设备", entity_id="ENTITY-B"),
        ]
        report = audit_universe(companies, 632, ["600001.SH"])
        self.assertEqual(3, report.security_count)
        self.assertEqual(2, report.included_company_count)
        self.assertEqual(1, report.completed_company_count)
        self.assertAlmostEqual(1 / 632, report.completed_coverage_rate)
        self.assertEqual(("BSE", "HKEX"), report.missing_exchanges)
        self.assertEqual(2, report.missing_source_count)
        self.assertEqual(2, report.missing_date_count)
        self.assertFalse(report.publishable)

    def test_universe_audit_requires_provenance_and_consistent_decisions(self):
        companies = [
            UniverseCompany(
                "600001.SH", "甲", "SSE", "电力", entity_id="ENTITY-A",
                source_url="https://official/sse", as_of_date="2026-07-29",
            ),
            UniverseCompany(
                "00001.HK", "甲H", "HKEX", "电力", entity_id="ENTITY-A",
                source_url="https://official/hkex", as_of_date="2026-07-29",
            ),
            UniverseCompany("000002.SZ", "乙", "SZSE", "电力", exclusion_reason="不应存在"),
            UniverseCompany("920001.BJ", "丙", "BSE", "电力", False),
        ]
        report = audit_universe(companies, 2, ["600001.SH", "00001.HK"])
        self.assertEqual(1, report.duplicate_included_entity_count)
        self.assertEqual(1, report.included_with_exclusion_reason_count)
        self.assertEqual(1, report.excluded_without_reason_count)
        self.assertFalse(report.publishable)

    def test_universe_audit_allows_complete_evidenced_release(self):
        companies = [
            UniverseCompany(
                "600001.SH", "甲", "SSE", "电力", entity_id="A",
                source_url="https://official/sse", as_of_date="2026-07-29",
            ),
            UniverseCompany(
                "000002.SZ", "乙", "SZSE", "电力", entity_id="B",
                source_url="https://official/szse", as_of_date="2026-07-29",
            ),
            UniverseCompany(
                "920001.BJ", "丙", "BSE", "电力", entity_id="C",
                source_url="https://official/bse", as_of_date="2026-07-29",
            ),
            UniverseCompany(
                "00001.HK", "丁", "HKEX", "电力", entity_id="D",
                source_url="https://official/hkex", as_of_date="2026-07-29",
            ),
        ]
        report = audit_universe(companies, 4, [item.stock_code for item in companies])
        self.assertTrue(report.publishable)

    def test_universe_audit_treats_review_placeholders_as_unclassified(self):
        company = UniverseCompany(
            "600001.SH", "甲", "SSE", "历史能源样本待复核", entity_id="A",
            source_url="https://official", as_of_date="2026-07-29",
        )
        report = audit_universe([company], 1, [company.stock_code], required_exchanges=("SSE",))
        self.assertEqual(1, report.unclassified_count)
        self.assertFalse(report.publishable)
        seed = UniverseCompany(
            "600002.SH", "乙", "SSE", "参考榜单能源种子待行业复核", entity_id="B",
            source_url="https://official", as_of_date="2026-07-29",
        )
        self.assertEqual(1, audit_universe([seed], 1, [], required_exchanges=("SSE",)).unclassified_count)

    def test_universe_builder_filters_st_non_energy_and_ah_duplicates(self):
        rows = [
            ExchangeSecurity("00001.HK", "甲电力", "HKEX", "电力", "ENTITY-A"),
            ExchangeSecurity("600001.SH", "甲电力", "SSE", "电力", "ENTITY-A"),
            ExchangeSecurity("000002.SZ", "*ST乙", "SZSE", "能源设备", "ENTITY-B"),
            ExchangeSecurity("920001.BJ", "丙软件", "BSE", "软件", "ENTITY-C"),
            ExchangeSecurity("920002.BJ", "丁储能", "BSE", "其他", "ENTITY-D", energy_eligible="true"),
        ]
        decisions = build_energy_universe(rows)
        self.assertEqual([False, True, False, False, True], [item.included for item in decisions])
        self.assertIn("保留600001.SH", decisions[0].exclusion_reason)
        self.assertEqual("ST/*ST排除", decisions[2].exclusion_reason)
        self.assertEqual("行业待复核:软件", decisions[3].exclusion_reason)

    def test_exchange_snapshot_round_trip_to_universe(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.csv"
            snapshot.write_text(
                "stock_code,company_name,exchange,industry,entity_id,st_status,listing_status,energy_eligible,source_url,as_of_date\n"
                "600900.SH,长江电力,SSE,电力,ENTITY-A,,上市,true,https://official,2026-07-28\n",
                encoding="utf-8",
            )
            output = Path(directory) / "universe.csv"
            write_universe(output, build_energy_universe(read_exchange_snapshot(snapshot)))
            companies = __import__("aegis_esg.universe", fromlist=["read_universe"]).read_universe(output)
            self.assertEqual("ENTITY-A", companies[0].entity_id)
            self.assertTrue(companies[0].included)

    def test_normalize_chinese_exchange_export_and_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "official.csv"
            source.write_text(
                "证券代码,证券简称,所属行业,上市状态,ST状态\n"
                "9001,测试能源,电力,上市,\n",
                encoding="utf-8",
            )
            rows = normalize_exchange_export(source, "BSE", "https://www.bse.cn/list", "2026-07-28")
            self.assertEqual("009001.BJ", rows[0].stock_code)
            self.assertEqual("电力", rows[0].industry)
            self.assertTrue(audit_snapshot(rows).valid)

    def test_stock_code_normalization_for_four_exchanges(self):
        self.assertEqual("600900.SH", normalize_stock_code("600900.ss", "SSE"))
        self.assertEqual("000001.SZ", normalize_stock_code("1", "SZSE"))
        self.assertEqual("920001.BJ", normalize_stock_code("920001", "BSE"))
        self.assertEqual("02688.HK", normalize_stock_code("2688.HK", "HKEX"))
        with self.assertRaises(ValueError):
            normalize_stock_code("ABC", "SSE")

    def test_snapshot_quality_requires_provenance(self):
        row = ExchangeSecurity("600900.SH", "长江电力", "SSE", "电力", "ENTITY")
        quality = audit_snapshot([row])
        self.assertFalse(quality.valid)
        self.assertEqual(1, quality.missing_source_count)
        self.assertEqual(1, quality.missing_date_count)

    def test_snapshot_quality_rejects_duplicates_and_invalid_provenance(self):
        rows = [
            ExchangeSecurity("600900.SH", "甲", "SSE", "电力", "A", source_url="ftp://bad", as_of_date="2026/07/28"),
            ExchangeSecurity("600900.SH", "甲", "SSE", "电力", "A", source_url="https://official", as_of_date="2026-07-28"),
        ]
        quality = audit_snapshot(rows)
        self.assertEqual(1, quality.duplicate_code_count)
        self.assertEqual(1, quality.invalid_source_count)
        self.assertEqual(1, quality.invalid_date_count)
        self.assertFalse(quality.valid)

    def test_official_listing_pagination_is_complete(self):
        payloads = {
            1: '{"data":[{"zqdm":"920001","zqjc":"甲电力","hymc":"电力"}],"pageNo":1,"pageCount":2,"total":2}',
            2: '{"data":[{"zqdm":"920002","zqjc":"乙设备","hymc":"能源设备"}],"pageNo":2,"pageCount":2,"total":2}',
        }
        rows = collect_listing_pages("BSE", "https://official/list", "2026-07-28", payloads.__getitem__)
        self.assertEqual(["920001.BJ", "920002.BJ"], [item.stock_code for item in rows])
        self.assertEqual("电力", rows[0].industry)

    def test_hkex_full_list_filters_non_company_securities(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ListOfSecurities.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["List of Securities"])
            sheet.append(["Updated as at 29/07/2026"])
            sheet.append(["Stock Code", "Name of Securities", "Category", "Sub-Category"])
            sheet.append(["1", "CKH HOLDINGS", "Equity", "Equity Securities (Main Board)"])
            sheet.append(["8100", "GET NICE", "Equity", "Equity Securities (GEM)"])
            sheet.append(["2800", "TRACKER FUND", "Exchange Traded Products", "Exchange Traded Funds"])
            sheet.append(["10001", "DERIVATIVE", "Derivative Warrants", None])
            workbook.save(source)
            rows, as_of_date = import_hkex_securities(
                source, "https://www.hkex.com.hk/ListOfSecurities.xlsx", "2026-07-29",
            )
            self.assertEqual("2026-07-29", as_of_date)
            self.assertEqual(["00001.HK", "08100.HK"], [item.stock_code for item in rows])
            self.assertTrue(audit_snapshot(rows).valid)

    def test_hkex_full_list_rejects_date_mismatch(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ListOfSecurities.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["List of Securities"])
            sheet.append(["Updated as at 28/07/2026"])
            sheet.append(["Stock Code", "Name of Securities", "Category", "Sub-Category"])
            sheet.append(["1", "CKH HOLDINGS", "Equity", "Equity Securities (Main Board)"])
            workbook.save(source)
            with self.assertRaisesRegex(ValueError, "日期不一致"):
                import_hkex_securities(source, "https://official", "2026-07-29")

    def test_hkex_profile_parser_validates_token_code_and_evidence(self):
        html = (
            "<script>LabCI.getToken = function () {\n"
            "//return \"Base64-AES-Encrypted-Token\";\n"
            "return \"abcdefghijklmnopqrstuvwxyz123456\";\n};</script>"
        )
        self.assertEqual("abcdefghijklmnopqrstuvwxyz123456", parse_hkex_access_token(html))
        encoded_html = "LabCI.getToken = function () { return 'abcdefghijklmnopqrstuv%2B1234'; };"
        self.assertEqual("abcdefghijklmnopqrstuv+1234", parse_hkex_access_token(encoded_html))
        payload = (
            'cb({"data":{"responsecode":"000","quote":{"sym":"2688","nm":"新奧能源控股有限公司",'
            '"nm_s":"新奧能源","summary":"主要从事销售及分销管道燃气。",'
            '"hsic_ind_classification":"公用事業 - 公用事業",'
            '"hsic_sub_sector_classification":"燃氣供應","db_updatetime":"2026年7月29日09:48"}}})'
        )
        profile = parse_hkex_quote_payload(payload, "02688.HK")
        self.assertEqual("新奧能源控股有限公司", profile.chinese_name)
        self.assertEqual("燃氣供應", profile.hsic_sub_sector)
        self.assertEqual("candidate", profile.evidence_status)
        with self.assertRaises(ValueError):
            parse_hkex_quote_payload(payload, "00003.HK")

    def test_hkex_profile_collector_reuses_page_token_and_preserves_raw_payload(self):
        html = "LabCI.getToken = function () { return 'abcdefghijklmnopqrstuvwxyz123456'; };"
        payloads = {
            "2688": 'aegisHKEX({"data":{"responsecode":"000","quote":{"sym":"2688","nm":"新奧能源",'
                    '"summary":"燃气业务","hsic_sub_sector_classification":"燃氣供應"}}})',
            "135": 'aegisHKEX({"data":{"responsecode":"000","quote":{"sym":"135","nm":"昆侖能源",'
                   '"summary":"能源业务","hsic_sub_sector_classification":"油氣生產商"}}})',
        }
        calls = []

        def fetch(url):
            calls.append(url)
            if "getequityquote" not in url:
                return html
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            return payloads[query["sym"][0]]

        profiles, raw = collect_hkex_issuer_profiles(["02688.HK", "00135.HK"], fetch)
        self.assertEqual(["02688.HK", "00135.HK"], [item.stock_code for item in profiles])
        self.assertEqual(3, len(calls))
        self.assertEqual({"02688.HK", "00135.HK"}, set(raw))

    def test_bse_jsonp_zero_based_pagination(self):
        def payload(page, code):
            return 'null([{"content":[{"xxzqdm":"%s","xxzqjc":"测试%s","xxhyzl":"电气机械和器材制造业","xxjsrq":"20260729"}],"number":%s,"totalPages":2,"totalElements":2}])' % (code, page, page)
        pages = {0: payload(0, "920001"), 1: payload(1, "920002")}
        rows, as_of_date, raw = collect_bse_listings(pages.__getitem__, expected_as_of_date="2026-07-29")
        self.assertEqual(["920001.BJ", "920002.BJ"], [item.stock_code for item in rows])
        self.assertEqual("2026-07-29", as_of_date)
        self.assertEqual(2, len(raw))
        self.assertTrue(audit_snapshot(rows).valid)

    def test_bse_rejects_page_mismatch_and_incomplete_result(self):
        wrong = 'null([{"content":[],"number":1,"totalPages":1,"totalElements":0}])'
        with self.assertRaisesRegex(ValueError, "分页响应错位"):
            parse_bse_page(wrong, 0)
        incomplete = 'null([{"content":[],"number":0,"totalPages":1,"totalElements":1}])'
        with self.assertRaisesRegex(ValueError, "分页不完整"):
            collect_bse_listings(lambda _: incomplete)

    def test_bse_official_code_mapping_parses_collisions(self):
        html = '<table><tr><td>1</td><td>许昌智能</td><td>2024/1/26</td><td>831396</td><td>920496</td></tr></table>'
        rows = parse_bse_code_mapping(html)
        self.assertEqual("831396.BJ", rows[0].old_code)
        self.assertEqual("920496.BJ", rows[0].new_code)

    def test_official_listing_rejects_html_and_incomplete_pages(self):
        with self.assertRaises(ValueError):
            parse_listing_page("<html>blocked</html>")
        payloads = {
            1: '{"rows":[{"code":"1","name":"甲"}],"page":1,"pageCount":2,"total":3}',
            2: '{"rows":[{"code":"2","name":"乙"}],"page":2,"pageCount":2,"total":3}',
        }
        with self.assertRaisesRegex(ValueError, "分页不完整"):
            collect_listing_pages("SZSE", "https://official/list", "2026-07-28", payloads.__getitem__)

    def test_szse_metadata_and_html_name_are_parsed(self):
        payload = '[{"metadata":{"pageno":1,"pagecount":1,"recordcount":1},"data":[' \
                  '{"zqdm":"000027","gsjc":"<a><u>深圳能源</u></a>","sshymc":"D 电力、热力、燃气及水生产和供应业"}]}]'
        page = parse_listing_page(payload)
        self.assertEqual(1, page.total_count)
        rows = collect_listing_pages("SZSE", "https://www.szse.cn/market/stock/company/", "2026-07-28", lambda _: payload)
        self.assertEqual("深圳能源", rows[0].company_name)
        self.assertTrue(rows[0].industry.startswith("D "))

    def test_sse_pagehelp_response_is_parsed(self):
        payload = '{"pageHelp":{"pageNo":1,"pageCount":1,"total":1,"data":[' \
                  '{"A_STOCK_CODE":"688001","COMPANY_ABBR":"华兴源创","CSRC_CODE_DESC":"制造业"}]},' \
                  '"result":[{"A_STOCK_CODE":"688001","COMPANY_ABBR":"华兴源创","CSRC_CODE_DESC":"制造业"}]}'
        rows = collect_listing_pages("SSE", "https://www.sse.com.cn/assortment/stock/home/", "2026-07-28", lambda _: payload)
        self.assertEqual("688001.SH", rows[0].stock_code)
        self.assertEqual("华兴源创", rows[0].company_name)

    def test_reference_ocr_codes_are_unique_and_snapshot_matched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ocr.txt"
            path.write_text("600900.SH 00956.HK 600900.SH 835185.BJ", encoding="utf-8")
            snapshot = [UniverseCompany("600900.SH", "长江电力", "SSE", "电力")]
            rows = extract_reference_securities(path, snapshot, "67-72")
            self.assertEqual(["600900.SH", "00956.HK", "835185.BJ"], [item.stock_code for item in rows])
            self.assertEqual("长江电力", rows[0].company_name)
            self.assertTrue(rows[0].matched_snapshot)
            self.assertFalse(rows[1].matched_snapshot)

    def test_reference_old_bse_code_matches_through_official_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ocr.txt"
            path.write_text("835185.BJ", encoding="utf-8")
            snapshots = [UniverseCompany("920185.BJ", "贝特瑞", "BSE", "电池制造")]
            rows = extract_reference_securities(path, snapshots, "67", {"835185.BJ": "920185.BJ"})
            self.assertTrue(rows[0].matched_snapshot)
            self.assertEqual("920185.BJ", rows[0].current_stock_code)

    def test_registry_reconciliation_exact_normalized_and_unmatched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            path.write_text(
                "证券代码,企业名称\n600900.SH,长江电力\n,深圳能源集团股份有限公司\n,不存在能源\n",
                encoding="utf-8",
            )
            snapshots = [
                UniverseCompany("600900.SH", "长江电力", "SSE", "电力"),
                UniverseCompany("000027.SZ", "深圳能源", "SZSE", "电力"),
            ]
            rows = reconcile_registry(path, snapshots, "用户名录", "", "2026-07-28")
            self.assertEqual(["matched", "matched", "unmatched"], [item.match_status for item in rows])
            self.assertEqual("name_normalized", rows[1].match_method)
            self.assertEqual("深圳能源", normalize_company_name("深圳能源集团股份有限公司"))

    def test_registry_code_name_conflict_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            path.write_text("stock_code,company_name\n600900.SH,错误名称\n", encoding="utf-8")
            rows = reconcile_registry(path, [UniverseCompany("600900.SH", "长江电力", "SSE", "电力")], "x", "", "2026-07-28")
            self.assertEqual("review", rows[0].match_status)

    def test_collection_plan_prioritizes_missing_annual_report(self):
        companies = [
            UniverseCompany("A", "甲", "SSE", "电力"),
            UniverseCompany("B", "乙", "SZSE", "电力"),
            UniverseCompany("C", "丙", "HKEX", "电力", included=False),
        ]
        records = [DocumentRecord("B", "乙", 2025, "annual_report", "u1", "u1", "a.pdf", "h", 1)]
        tasks = plan_collection(companies, records, 2025)
        self.assertEqual(["A", "B"], [item.stock_code for item in tasks])
        self.assertEqual("discover_annual_and_esg", tasks[0].next_action)
        self.assertEqual("discover_esg_or_scan_annual", tasks[1].next_action)
        summary = collection_summary(tasks)
        self.assertEqual(1, summary["annual_collected"])
        self.assertEqual(0, summary["ready_for_extraction"])

    def test_import_historical_two_row_workbook(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["历史评价表"])
            sheet.append(["序号", "", "", "联系人", "城市", "证券代码", "公司简称", "公司名称", "数值类别", *[name for _, name in __import__('aegis_esg.historical', fromlist=['INDICATORS']).INDICATORS], "ESG分数"])
            sheet.append([1, "", "", "张三", "北京", "600900.SH", "长江电力", "中国长江电力股份有限公司", "指标数值", *range(1, 11), 88.5])
            sheet.append([1, "", "", "", "", "600900.SH", "长江电力", "中国长江电力股份有限公司", "指标分值", *range(11, 21), ""])
            workbook.save(path)
            companies, observations, audit = import_historical_workbook(
                path, [UniverseCompany("600900.SH", "长江电力", "SSE", "电力")], 2024, 2023,
            )
            self.assertEqual(1, len(companies))
            self.assertEqual(10, len(observations))
            self.assertEqual("matched", companies[0].current_snapshot_status)
            self.assertEqual("1", observations[0].raw_value)
            self.assertEqual(10, audit["observation_count"])

    def test_import_historical_rejects_missing_score_row(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["序号", "", "", "联系人", "城市", "证券代码", "公司简称", "公司名称", "数值类别", "温室气体排放强度", "综合能源消耗强度", "NOx", "SO2", "新鲜水资源消耗强度", "一般固废排放强度", "环保/安全生产投入占比", "研发费用占比", "现金分红", "资产负债率", "ESG分数"])
            sheet.append([1, "", "", "", "", "600900.SH", "长江电力", "长江电力", "指标数值"])
            workbook.save(path)
            with self.assertRaisesRegex(ValueError, "缺少紧随其后的指标分值行"):
                import_historical_workbook(path, [], 2024, 2023)

    def test_historical_migration_separates_candidates_and_review(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            path.write_text(
                "stock_code,company_name,company_abbr,exchange,st_flag,historical_rank,historical_esg_score\n"
                "600900.SH,长江电力,长江电力,SSE,False,1,70\n"
                "600112.SH,天成控股,*ST天成,SSE,True,2,20\n"
                "00001.HK,港股甲,港股甲,HKEX,False,3,10\n"
                "#N/A,未知公司,未知公司,UNKNOWN,False,4,5\n",
                encoding="utf-8",
            )
            rows, audit = plan_historical_migration(
                path, [UniverseCompany("600900.SH", "长江电力", "SSE", "电力")],
            )
            self.assertEqual(
                ["provisional_include", "exclude", "pending_snapshot", "manual_review"],
                [item.decision for item in rows],
            )
            self.assertEqual(1, audit["provisional_company_count"])
            self.assertEqual(2, audit["requires_review_count"])
            universe = Path(directory) / "universe.csv"
            write_candidate_universe(universe, rows)
            imported = __import__('aegis_esg.universe', fromlist=['read_universe']).read_universe(universe)
            self.assertEqual([True, False, False, False], [item.included for item in imported])

    def test_historical_migration_uses_available_hkex_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            path.write_text(
                "stock_code,company_name,company_abbr,exchange,st_flag\n"
                "00001.HK,港股甲,港股甲,HKEX,False\n",
                encoding="utf-8",
            )
            rows, audit = plan_historical_migration(
                path, [UniverseCompany("00001.HK", "CKH HOLDINGS", "HKEX", "待分类")],
            )
            self.assertEqual("provisional_include", rows[0].decision)
            self.assertEqual("CKH HOLDINGS", rows[0].current_name)
            self.assertEqual(["HKEX"], audit["snapshot_exchanges"])

    def test_historical_missing_code_can_use_signed_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            path.write_text(
                "stock_code,company_name,company_abbr,exchange,st_flag\n"
                "#N/A,中国港能智慧能源集团有限公司,中国港能,UNKNOWN,False\n",
                encoding="utf-8",
            )
            rows, _ = plan_historical_migration(
                path, [UniverseCompany("00931.HK", "CHINA HK POWER", "HKEX", "待分类")],
                {"#N/A": "00931.HK"},
            )
            self.assertEqual("provisional_include", rows[0].decision)
            self.assertEqual("00931.HK", rows[0].stock_code)

    def test_augment_universe_requires_snapshot_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.csv"
            snapshot.write_text(
                "stock_code,company_name,exchange,industry,entity_id,source_url,as_of_date\n"
                "600925.SH,苏能股份,SSE,煤炭,600925.SH,https://official,2026-07-29\n",
                encoding="utf-8",
            )
            additions = Path(directory) / "add.csv"
            additions.write_text(
                "stock_code,evidence_url,reason\n600925.SH,evidence.txt,参考前200\n",
                encoding="utf-8",
            )
            rows = augment_candidate_universe([], additions, snapshot)
            self.assertEqual("600925.SH", rows[0].stock_code)
            self.assertTrue(rows[0].included)

    def test_bind_snapshot_provenance_fills_only_missing_fields_by_exact_code(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.csv"
            snapshot.write_text(
                "stock_code,company_name,exchange,industry,entity_id,source_url,as_of_date\n"
                "600900.SH,长江电力,SSE,电力,600900.SH,https://official,2026-07-29\n",
                encoding="utf-8",
            )
            companies = [
                UniverseCompany("600900.SH", "中国长江电力", "SSE", "电力"),
                UniverseCompany(
                    "000001.SZ", "甲", "SZSE", "电力", source_url="https://evidence",
                ),
            ]
            rows, bindings, summary = bind_snapshot_provenance(companies, snapshot)
            self.assertEqual("https://official", rows[0].source_url)
            self.assertEqual("2026-07-29", rows[0].as_of_date)
            self.assertEqual("name_difference", bindings[0].status)
            self.assertEqual("https://evidence", rows[1].source_url)
            self.assertEqual("unmatched", bindings[1].status)
            self.assertTrue(bindings[1].included)
            self.assertEqual(1, summary["source_filled_count"])
            self.assertEqual(1, summary["included_unmatched_count"])
            self.assertFalse(summary["complete"])

    def test_bind_snapshot_provenance_flags_explicit_entity_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.csv"
            snapshot.write_text(
                "stock_code,company_name,exchange,industry,entity_id,source_url,as_of_date\n"
                "00001.HK,甲,HKEX,电力,ENTITY-NEW,https://official,2026-07-29\n",
                encoding="utf-8",
            )
            company = UniverseCompany("00001.HK", "甲", "HKEX", "电力", entity_id="ENTITY-OLD")
            rows, bindings, summary = bind_snapshot_provenance([company], snapshot)
            self.assertEqual("ENTITY-OLD", rows[0].entity_id)
            self.assertEqual("entity_conflict", bindings[0].status)
            self.assertEqual(1, summary["entity_conflict_count"])
            self.assertFalse(summary["complete"])

    def test_universe_evidence_plan_prioritizes_hkex_and_tracks_snapshot_industry(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.csv"
            snapshot.write_text(
                "stock_code,company_name,exchange,industry,entity_id,source_url,as_of_date\n"
                "00001.HK,甲,HKEX,待分类,00001.HK,https://hkex,2026-07-29\n"
                "600001.SH,乙,SSE,制造业,600001.SH,https://sse,2026-07-29\n",
                encoding="utf-8",
            )
            companies = [
                UniverseCompany("600001.SH", "乙", "SSE", "历史能源样本待复核"),
                UniverseCompany("00001.HK", "甲", "HKEX", "待分类"),
            ]
            tasks, summary = plan_universe_evidence(companies, snapshot)
            self.assertEqual("00001.HK", tasks[0].stock_code)
            self.assertEqual("collect_hkex_industry_and_chinese_name_evidence", tasks[0].next_action)
            self.assertEqual("制造业", tasks[1].snapshot_industry)
            self.assertEqual(2, summary["pending_industry_count"])
            self.assertFalse(summary["publishable"])
            hk_tasks, hk_summary = plan_universe_evidence(companies, snapshot, ("HKEX",))
            self.assertEqual(["00001.HK"], [item.stock_code for item in hk_tasks])
            self.assertEqual(["HKEX"], hk_summary["exchange_filter"])

    def test_apply_signed_universe_evidence_classifies_and_deduplicates_ah(self):
        with tempfile.TemporaryDirectory() as directory:
            decisions = Path(directory) / "decisions.csv"
            decisions.write_text(
                "stock_code,decision,sub_industry,entity_id,evidence_url,evidence_date,reviewer,reviewed_at,rationale\n"
                "600001.SH,include,电力,ENTITY-A,https://official/a,2026-07-29,alice,2026-07-29T10:00:00+08:00,发行人年报确认\n"
                "00001.HK,include,电力,ENTITY-A,https://official/h,2026-07-29,bob,2026-07-29T10:01:00+08:00,港交所披露确认\n",
                encoding="utf-8",
            )
            companies = [
                UniverseCompany("00001.HK", "甲H", "HKEX", "待分类", entity_id="00001.HK", source_url="https://hkex", as_of_date="2026-07-29"),
                UniverseCompany("600001.SH", "甲", "SSE", "待分类", entity_id="600001.SH", source_url="https://sse", as_of_date="2026-07-29"),
            ]
            rows, audit_rows, summary = apply_universe_evidence(companies, decisions)
            by_code = {item.stock_code: item for item in rows}
            self.assertTrue(by_code["600001.SH"].included)
            self.assertFalse(by_code["00001.HK"].included)
            self.assertIn("保留600001.SH", by_code["00001.HK"].exclusion_reason)
            self.assertEqual("https://hkex", by_code["00001.HK"].source_url)
            self.assertEqual(1, summary["ah_duplicate_excluded_count"])
            self.assertEqual("ah_duplicate_exclude", next(item for item in audit_rows if item.stock_code == "00001.HK").action)

    def test_apply_universe_evidence_rejects_unsigned_or_placeholder_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            decisions = Path(directory) / "decisions.csv"
            decisions.write_text(
                "stock_code,decision,sub_industry,entity_id,evidence_url,evidence_date,reviewer,reviewed_at,rationale\n"
                "600001.SH,include,仍待复核,600001.SH,https://official,2026-07-29,,2026-07-29T10:00:00,\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                apply_universe_evidence(
                    [UniverseCompany("600001.SH", "甲", "SSE", "待分类")], decisions,
                )

    def test_merge_universe_evidence_batches_tracks_supersede_and_revoke(self):
        header = (
            "decision_id,batch_id,operation,supersedes,stock_code,decision,sub_industry,entity_id,"
            "evidence_url,evidence_date,reviewer,reviewed_at,rationale\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            second = Path(directory) / "second.csv"
            third = Path(directory) / "third.csv"
            first.write_text(
                header + "D1,B1,upsert,,600001.SH,include,电力,A,https://official/1,2026-07-29,alice,2026-07-29T10:00:00+08:00,初审\n",
                encoding="utf-8",
            )
            second.write_text(
                header + "D2,B2,upsert,D1,600001.SH,include,新能源,A,https://official/2,2026-07-30,bob,2026-07-30T10:00:00+08:00,更正行业\n",
                encoding="utf-8",
            )
            third.write_text(
                header + "D3,B3,revoke,D2,600001.SH,,,,https://official/3,2026-07-31,carol,2026-07-31T10:00:00+08:00,撤销待重审\n",
                encoding="utf-8",
            )
            active, ledger, summary = merge_universe_evidence_batches([first, second])
            self.assertEqual("新能源", active[0]["sub_industry"])
            self.assertEqual(["superseded", "active"], [item["ledger_state"] for item in ledger])
            self.assertEqual(1, summary["active_decision_count"])
            active, ledger, summary = merge_universe_evidence_batches([first, second, third])
            self.assertFalse(active)
            self.assertEqual(0, summary["active_decision_count"])
            self.assertEqual("revoked", ledger[1]["ledger_state"])

    def test_merge_universe_evidence_rejects_version_fork(self):
        header = (
            "decision_id,batch_id,operation,supersedes,stock_code,decision,sub_industry,entity_id,"
            "evidence_url,evidence_date,reviewer,reviewed_at,rationale\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.csv"
            fork = Path(directory) / "fork.csv"
            first.write_text(
                header + "D1,B1,upsert,,600001.SH,include,电力,A,https://official/1,2026-07-29,alice,2026-07-29T10:00:00+08:00,初审\n",
                encoding="utf-8",
            )
            fork.write_text(
                header + "D2,B2,upsert,WRONG,600001.SH,include,新能源,A,https://official/2,2026-07-30,bob,2026-07-30T10:00:00+08:00,冲突版本\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                merge_universe_evidence_batches([first, fork])

    def test_indicator_plan_builds_complete_company_indicator_matrix(self):
        companies = [
            UniverseCompany("A", "甲", "SSE", "电力"),
            UniverseCompany("B", "乙", "SZSE", "电力"),
        ]
        first = self.methodology.indicators[0]
        observations = [Observation("A", "甲", 2025, first.code, 1)]
        tasks, summary = plan_indicator_tasks(companies, observations, self.methodology, 2025)
        self.assertEqual(160, len(tasks))
        self.assertEqual(1, summary["confirmed_count"])
        self.assertEqual(1, summary["empty_companies"])
        self.assertFalse(summary["publishable"])
        confirmed = next(item for item in tasks if item.company_code == "A" and item.indicator_code == first.code)
        self.assertEqual("complete", confirmed.next_action)

    def test_download_validation_decompresses_and_rejects_html(self):
        pdf = b"%PDF-1.7\n" + b"x" * 10_000
        self.assertEqual(pdf, _decode_document(gzip.compress(pdf), "gzip", "https://official/a.pdf"))
        with self.assertRaises(ValueError):
            _decode_document(b"<html>blocked</html>", "", "https://official/a.pdf")

    def test_sse_download_has_official_big5_fallback(self):
        url = "https://www.sse.com.cn/disclosure/listedinfo/announcement/a.pdf"
        self.assertEqual(
            [
                url,
                "https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/announcement/a.pdf",
            ],
            _download_candidates(url),
        )
        self.assertEqual(
            ["https://example.test/a.pdf"],
            _download_candidates("https://example.test/a.pdf"),
        )

    def test_document_index_round_trip(self):
        record = DocumentRecord("A", "甲", 2025, "annual_report", "https://source", "https://retrieval", "a.pdf", "abc", 12)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.csv"
            write_document_index(path, [record])
            self.assertEqual(record, _read_document_index(path)[record.source_url])


if __name__ == "__main__":
    unittest.main()
