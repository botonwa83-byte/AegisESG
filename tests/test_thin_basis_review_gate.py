import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts/apply_thin_basis_review.py"
SPEC = importlib.util.spec_from_file_location("thin_review_gate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


FIELDS = {
    "basis_decision": "确认",
    "selected_value": "1.2",
    "selected_unit": "吨/万元",
    "selected_denominator": "营业收入",
    "scope_decision": "合并口径",
    "reviewer": "reviewer-a",
    "reviewed_at": "2026-08-04T12:00:00+08:00",
    "review_note": "依据原文表格核验",
}


def test_empty_review_is_blocked():
    result = MODULE.evaluate([{"company_code": "00001.SZ", "indicator_code": "Q_E_TEST"}])
    assert result["status"] == "blocked_external_review"
    assert result["candidate_observations_written"] is False


def test_complete_review_requires_second_authorization():
    row = {"company_code": "00001.SZ", "indicator_code": "Q_E_TEST", **FIELDS}
    result = MODULE.evaluate([row])
    assert result["status"] == "ready_for_secondary_authorization"
    assert result["scoring_authorized"] is False
    assert result["candidate_observations_written"] is False


def test_invalid_decision_does_not_authorize():
    row = {"company_code": "00001.SZ", "indicator_code": "Q_E_TEST", **FIELDS, "basis_decision": "maybe"}
    result = MODULE.evaluate([row])
    assert result["confirmed_rows"] == 0
    assert result["status"] == "reject_template"
    assert result["invalid_decisions"][0]["decision"] == "maybe"
    assert result["scoring_authorized"] is False
