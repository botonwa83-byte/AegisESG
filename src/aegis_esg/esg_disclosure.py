from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .extraction import read_page_text_export
from .methodology import Methodology
from .planning import read_document_records


@dataclass(frozen=True)
class AnnualESGEvidence:
    stock_code: str
    company_name: str
    source_url: str
    source_file: str
    source_page: int
    matched_term: str
    evidence_text: str
    review_status: str = "pending"


@dataclass(frozen=True)
class QualitativeEvidenceCandidate:
    company_code: str
    company_name: str
    report_year: int
    indicator_code: str
    indicator_name: str
    source_url: str
    source_file: str
    source_page: int
    matched_term: str
    evidence_text: str
    confidence: float
    review_status: str = "pending"


QUALITATIVE_ALIASES = {
    "X_E_ENV_SYSTEM": ("environmental management system", "环境管理体系"),
    "X_E_EMERGENCY": ("environmental emergency", "环境应急"),
    "X_E_TRAINING": ("environmental training", "环保培训"),
    "X_E_COMPLIANCE": ("environmental compliance", "环境合规"),
    "X_E_IMPACT": ("environmental impact", "环境影响"),
    "X_E_ENERGY_MANAGEMENT": ("energy management", "能源管理"),
    "X_E_WATER": ("water resources", "water resource", "水资源"),
    "X_E_OTHER_RESOURCE": ("resource conservation", "资源节约"),
    "X_E_WASTEWATER": ("wastewater", "sewage", "废水"),
    "X_E_WASTE_GAS": ("air emissions", "exhaust gas", "废气"),
    "X_E_SOLID_WASTE": ("solid waste", "固体废物"),
    "X_E_HAZ_WASTE": ("hazardous waste", "危险废物"),
    "X_E_CLIMATE_RISK": ("climate risk", "气候风险"),
    "X_E_CLIMATE_ACTION": ("climate change", "气候变化"),
    "X_E_BIODIVERSITY": ("biodiversity", "生物多样性"),
    "X_E_GREEN_TRANSITION": ("green transition", "绿色转型"),
    "X_E_CLEAN_PRODUCTION": ("clean production", "清洁生产"),
    "X_E_GREEN_SUPPLY_CHAIN": ("green supply chain", "绿色供应链"),
    "X_E_GREEN_OFFICE": ("green office", "绿色办公"),
    "X_E_GREEN_FINANCE": ("green finance", "green financing", "绿色融资"),
    "X_S_PUBLIC_WELFARE": ("community investment", "public welfare", "社会公益"),
    "X_S_RD_INNOVATION": ("research and development", "研发创新"),
    "X_S_JUST_TRANSITION": ("just transition", "公正转型"),
    "X_S_EMPLOYEE_RIGHTS": ("employee rights", "labour rights", "员工权益"),
    "X_S_OCCUPATIONAL_HEALTH": ("occupational health", "职业健康"),
    "X_S_CAREER": ("career development", "employee development", "职业发展"),
    "X_S_DIVERSITY": ("diversity and inclusion", "equal opportunity", "多元化"),
    "X_S_FEEDBACK": ("employee communication", "employee feedback", "员工沟通"),
    "X_S_CUSTOMER_SERVICE": ("customer service", "客户服务"),
    "X_S_PRODUCT_QUALITY": ("product quality", "产品质量"),
    "X_S_SUPPLY_CHAIN": ("supply chain management", "供应链管理"),
    "X_G_GOVERNANCE_MECHANISM": ("governance mechanism", "治理机制"),
    "X_G_CORPORATE_STRUCTURE": ("corporate structure", "公司架构"),
    "X_G_MANAGEMENT": ("management mechanism", "管理层机制"),
    "X_G_ESG_MANAGEMENT": ("sustainability governance", "ESG management", "可持续发展管理"),
    "X_G_DISCLOSURE": ("information disclosure", "信息披露"),
    "X_G_PERFORMANCE": ("business performance", "operating performance", "经营表现"),
    "X_G_SAFETY": ("production safety", "work safety", "安全生产"),
    "X_G_AUDIT": ("external auditor", "independent auditor", "会计审计"),
    "X_G_INTERNAL_CONTROL": ("internal control", "risk management", "内部控制"),
    "X_G_ANTI_BRIBERY": ("anti-corruption", "anti-bribery", "反贪污", "反商业贿赂"),
    "X_G_TAX": ("tax compliance", "纳税"),
    "X_G_INTEGRITY": ("business ethics", "integrity and compliance", "诚信合规"),
}


ESG_PATTERNS = (
    re.compile(r"environmental,? social and governance", re.I),
    re.compile(r"\bESG (?:report|section|disclosure|information)\b", re.I),
    re.compile(r"\bsustainability report\b", re.I),
    re.compile(r"環境、?社會及管治|环境、?社会及管治"),
)


def _normalize_page_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()


def scan_annual_esg_disclosure(
    coverage_path: str | Path, document_index: str | Path, text_root: str | Path,
    max_per_company: int = 5,
) -> tuple[list[AnnualESGEvidence], dict]:
    if max_per_company < 1:
        raise ValueError("年报ESG证据上限必须大于0")
    with Path(coverage_path).open(encoding="utf-8-sig", newline="") as stream:
        coverage = list(csv.DictReader(stream))
    required = {"stock_code", "company_name", "next_action"}
    if not coverage or not required.issubset(coverage[0]):
        raise ValueError("文档覆盖审计字段不完整")
    targets = {
        row["stock_code"].strip().upper(): row["company_name"].strip()
        for row in coverage if row["next_action"].strip() == "scan_annual_for_esg"
    }
    annuals = {
        item.company_code: item for item in read_document_records(document_index)
        if item.document_type == "annual_report" and item.company_code in targets
    }
    text_root = Path(text_root)
    evidence = []
    missing_text = []
    for code in sorted(targets):
        record = annuals.get(code)
        if record is None:
            continue
        try:
            relative = Path(record.local_path).relative_to("data/raw")
        except ValueError as error:
            raise ValueError(f"年报路径不在data/raw下: {record.local_path}") from error
        text_path = (text_root / relative).with_suffix(".txt")
        if not text_path.exists():
            missing_text.append(str(text_path))
            continue
        found = 0
        for page in read_page_text_export(text_path):
            normalized = _normalize_page_text(page.text)
            match = next((pattern.search(normalized) for pattern in ESG_PATTERNS if pattern.search(normalized)), None)
            if match is None:
                continue
            start, end = max(0, match.start() - 180), min(len(normalized), match.end() + 360)
            evidence.append(AnnualESGEvidence(
                code, targets[code], record.source_url, record.local_path, page.page,
                match.group(0), normalized[start:end],
            ))
            found += 1
            if found >= max_per_company:
                break
    covered = {item.stock_code for item in evidence}
    summary = {
        "target_company_count": len(targets),
        "annual_document_count": len(annuals),
        "candidate_count": len(evidence),
        "candidate_company_count": len(covered),
        "codes_without_candidates": sorted(set(targets).difference(covered)),
        "missing_text_count": len(missing_text),
        "missing_text_files": missing_text,
        "applicable": False,
    }
    return evidence, summary


def write_annual_esg_evidence(
    output_path: str | Path, summary_path: str | Path,
    rows: list[AnnualESGEvidence], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(AnnualESGEvidence.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_annual_qualitative_evidence(
    coverage_path: str | Path, document_index: str | Path, text_root: str | Path,
    methodology: Methodology, report_year: int, max_per_indicator: int = 3,
) -> tuple[list[QualitativeEvidenceCandidate], dict]:
    """Locate auditable qualitative evidence without assigning a score."""
    if max_per_indicator < 1:
        raise ValueError("定性证据上限必须大于0")
    with Path(coverage_path).open(encoding="utf-8-sig", newline="") as stream:
        coverage = list(csv.DictReader(stream))
    required = {"stock_code", "company_name", "annual_status"}
    if not coverage or not required.issubset(coverage[0]):
        raise ValueError("文档覆盖审计字段不完整")
    targets = {
        row["stock_code"].strip().upper(): row["company_name"].strip()
        for row in coverage if row["annual_status"].strip() == "collected"
    }
    annuals = {
        item.company_code: item for item in read_document_records(document_index)
        if item.document_type == "annual_report" and item.report_year == report_year
        and item.company_code in targets
    }
    rules = []
    for indicator in methodology.qualitative:
        aliases = QUALITATIVE_ALIASES.get(indicator.code)
        if not aliases:
            raise ValueError(f"定性指标缺少证据关键词: {indicator.code}")
        rules.append((indicator, tuple(re.compile(re.escape(term), re.I) for term in aliases)))
    output = []
    missing_text = []
    matched_groups: set[tuple[str, str]] = set()
    text_root = Path(text_root)
    for code in sorted(targets):
        record = annuals.get(code)
        if record is None:
            continue
        try:
            relative = Path(record.local_path).relative_to("data/raw")
        except ValueError as error:
            raise ValueError(f"年报路径不在data/raw下: {record.local_path}") from error
        text_path = (text_root / relative).with_suffix(".txt")
        if not text_path.exists():
            missing_text.append(str(text_path))
            continue
        counts: dict[str, int] = {}
        for page in read_page_text_export(text_path):
            normalized = _normalize_page_text(page.text)
            for indicator, patterns in rules:
                if counts.get(indicator.code, 0) >= max_per_indicator:
                    continue
                match = None
                for pattern in patterns:
                    match = pattern.search(normalized)
                    if match is not None:
                        break
                if match is None:
                    continue
                start, end = max(0, match.start() - 180), min(len(normalized), match.end() + 360)
                output.append(QualitativeEvidenceCandidate(
                    code, targets[code], report_year, indicator.code, indicator.name,
                    record.source_url, record.local_path, page.page, match.group(0),
                    normalized[start:end], 0.75 if match.group(0).casefold() == indicator.name.casefold() else 0.65,
                ))
                counts[indicator.code] = counts.get(indicator.code, 0) + 1
                matched_groups.add((code, indicator.code))
    output.sort(key=lambda item: (item.company_code, item.indicator_code, item.source_page))
    expected_groups = len(annuals) * len(methodology.qualitative)
    summary = {
        "report_year": report_year,
        "target_company_count": len(targets),
        "annual_document_count": len(annuals),
        "qualitative_indicator_count": len(methodology.qualitative),
        "candidate_count": len(output),
        "candidate_group_count": len(matched_groups),
        "candidate_company_count": len({item.company_code for item in output}),
        "expected_group_count": expected_groups,
        "missing_group_count": expected_groups - len(matched_groups),
        "missing_text_count": len(missing_text),
        "missing_text_files": missing_text,
        "scoring_authorized": False,
    }
    return output, summary


def write_qualitative_evidence_candidates(
    output_path: str | Path, summary_path: str | Path,
    rows: list[QualitativeEvidenceCandidate], summary: dict,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(QualitativeEvidenceCandidate.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(item) for item in rows)
    summary_output = Path(summary_path)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
