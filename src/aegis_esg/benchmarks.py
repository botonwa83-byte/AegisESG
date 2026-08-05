"""国资委工业领域优秀值注入与 DL/T 正式治理打分门禁。"""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from .methodology import Methodology, load_methodology
from .models import Direction, Indicator, IndicatorKind


GOVERNANCE_BENCHMARK_TARGET_VERSION = "DLT2971-2025-v1"
BENCHMARK_PACKET_VERSION = "governance-benchmark-packet-v1"
REQUIRED_GOVERNANCE_CODES = (
    "Q_G_ROE", "Q_G_ROA", "Q_G_OPERATING_MARGIN", "Q_G_EBITDA_MARGIN",
    "Q_G_CASH_REALIZATION", "Q_G_COST_REVENUE_RATE", "Q_G_ASSET_TURNOVER",
    "Q_G_AR_TURNOVER", "Q_G_CURRENT_ASSET_TURNOVER", "Q_G_TWO_FUNDS_RATE",
    "Q_G_DEBT_ASSET_RATE", "Q_G_EBITDA_INTEREST", "Q_G_QUICK_RATIO",
    "Q_G_CASH_CURRENT_LIABILITY", "Q_G_REVENUE_GROWTH",
    "Q_G_OPERATING_PROFIT_GROWTH", "Q_G_CAPITAL_ACCUMULATION",
)

# 行标指标 → 《企业绩效评价标准值》常见表头别名（便于人工对照抄录）
SASAC_FIELD_MAP: dict[str, dict[str, str]] = {
    "Q_G_ROE": {
        "sasac_name": "净资产收益率",
        "mapping_note": "主表盈利回报指标；抄录“优秀值”列",
    },
    "Q_G_ROA": {
        "sasac_name": "总资产报酬率",
        "mapping_note": "主表盈利回报指标；抄录“优秀值”列",
    },
    "Q_G_OPERATING_MARGIN": {
        "sasac_name": "销售（营业）利润率",
        "mapping_note": "行标称营业利润率；与国资委销售（营业）利润率口径对齐需方法论确认",
    },
    "Q_G_EBITDA_MARGIN": {
        "sasac_name": "（补充/映射）EBITDA利润率",
        "mapping_note": "国资委主表通常无同名项；需方法论负责人确认是否用近似项或保留空并改指标",
    },
    "Q_G_CASH_REALIZATION": {
        "sasac_name": "盈余现金保障倍数/营业收现相关",
        "mapping_note": "行标为营业收现率；与国资委盈余现金保障倍数不同，禁止擅自替换数值",
    },
    "Q_G_COST_REVENUE_RATE": {
        "sasac_name": "成本费用利润率（需换算）或成本费用占收比",
        "mapping_note": "行标为成本费用/营业收入（负向）；不可直接抄成本费用利润率而不换算",
    },
    "Q_G_ASSET_TURNOVER": {
        "sasac_name": "总资产周转率",
        "mapping_note": "主表资产运营指标；单位为次",
    },
    "Q_G_AR_TURNOVER": {
        "sasac_name": "应收账款周转率",
        "mapping_note": "主表资产运营指标；单位为次",
    },
    "Q_G_CURRENT_ASSET_TURNOVER": {
        "sasac_name": "流动资产周转率",
        "mapping_note": "主表资产运营指标；单位为次",
    },
    "Q_G_TWO_FUNDS_RATE": {
        "sasac_name": "（行标特有）两金占流动资产比例",
        "mapping_note": "国资委主表通常无两金占比；需方法论确认数据来源或保留行业样本中性",
    },
    "Q_G_DEBT_ASSET_RATE": {
        "sasac_name": "资产负债率",
        "mapping_note": "双向指标；抄录优秀值，打分以优秀值为峰向两侧衰减",
    },
    "Q_G_EBITDA_INTEREST": {
        "sasac_name": "已获利息倍数",
        "mapping_note": "行标称EBITDA利息倍数/已获利息倍数；双向指标",
    },
    "Q_G_QUICK_RATIO": {
        "sasac_name": "速动比率",
        "mapping_note": "双向指标；注意国资委表中单位是否已是百分比",
    },
    "Q_G_CASH_CURRENT_LIABILITY": {
        "sasac_name": "现金流动负债比率",
        "mapping_note": "双向指标；抄录优秀值列",
    },
    "Q_G_REVENUE_GROWTH": {
        "sasac_name": "营业增长率 / 销售（营业）增长率",
        "mapping_note": "主表经营增长指标",
    },
    "Q_G_OPERATING_PROFIT_GROWTH": {
        "sasac_name": "营业利润增长率",
        "mapping_note": "若表中仅有利润总额增长率，不得直接替代",
    },
    "Q_G_CAPITAL_ACCUMULATION": {
        "sasac_name": "资本积累率",
        "mapping_note": "主表经营增长指标",
    },
}

BENCHMARK_TABLE_FIELDS = (
    "indicator_code", "name", "level2", "direction", "unit", "weight",
    "sasac_name", "benchmark", "source_year", "source_industry", "source_document",
    "mapping_note", "notes",
)


def governance_indicator_codes(methodology: Methodology) -> tuple[str, ...]:
    return tuple(
        item.code for item in methodology.indicators
        if item.kind == IndicatorKind.QUANTITATIVE and item.dimension == "G"
    )


def audit_governance_benchmarks(methodology: Methodology | str | Path) -> dict[str, Any]:
    loaded = methodology if isinstance(methodology, Methodology) else load_methodology(methodology)
    codes = governance_indicator_codes(loaded)
    missing = [code for code in codes if loaded.by_code[code].benchmark is None]
    filled = [code for code in codes if loaded.by_code[code].benchmark is not None]
    complete = not missing and set(codes) == set(REQUIRED_GOVERNANCE_CODES)
    return {
        "audit_version": "governance-benchmark-audit-v1",
        "standard_ref": "DL/T 2971—2025",
        "methodology_version": loaded.version,
        "governance_indicator_count": len(codes),
        "filled_count": len(filled),
        "missing_count": len(missing),
        "missing_codes": missing,
        "complete": complete,
        "formal_ready": complete,
        "target_methodology_version": GOVERNANCE_BENCHMARK_TARGET_VERSION,
        "blocker": (
            None if complete
            else "需填入国资委企业绩效评价标准值工业领域优秀值后冻结DLT2971-2025-v1"
        ),
    }


def require_governance_benchmarks(methodology: Methodology | str | Path) -> dict[str, Any]:
    audit = audit_governance_benchmarks(methodology)
    if not audit["formal_ready"]:
        missing = "、".join(audit["missing_codes"][:5]) or "全部治理定量指标"
        raise ValueError(
            "DL/T 2971正式治理打分要求17项优秀值全部配置；"
            f"当前缺失{audit['missing_count']}项，例如：{missing}"
        )
    return audit


def read_benchmark_table(path: str | Path) -> dict[str, float]:
    values: dict[str, float] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            code = (row.get("indicator_code") or "").strip()
            raw = (row.get("benchmark") or "").strip()
            if not code:
                raise ValueError(f"第{line}行缺少indicator_code")
            if not raw:
                continue
            try:
                values[code] = float(raw)
            except ValueError as error:
                raise ValueError(f"第{line}行benchmark不是数值: {raw}") from error
    return values


def build_benchmark_intake_rows(methodology: Methodology | str | Path) -> list[dict[str, str]]:
    loaded = methodology if isinstance(methodology, Methodology) else load_methodology(methodology)
    rows: list[dict[str, str]] = []
    for code in REQUIRED_GOVERNANCE_CODES:
        indicator = loaded.by_code[code]
        alias = SASAC_FIELD_MAP[code]
        rows.append({
            "indicator_code": code,
            "name": indicator.name,
            "level2": indicator.level2,
            "direction": indicator.direction.value,
            "unit": indicator.unit,
            "weight": f"{indicator.weight:.2f}",
            "sasac_name": alias["sasac_name"],
            "benchmark": "" if indicator.benchmark is None else str(indicator.benchmark),
            "source_year": "",
            "source_industry": "工业全行业",
            "source_document": "国资委企业绩效评价标准值",
            "mapping_note": alias["mapping_note"],
            "notes": "",
        })
    return rows


def write_benchmark_intake_csv(path: str | Path, rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BENCHMARK_TABLE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_benchmark_intake_html(path: str | Path, rows: list[dict[str, str]], summary: dict[str, Any]) -> None:
    body = "".join(
        "<tr>"
        f"<td><code>{html.escape(row['indicator_code'])}</code></td>"
        f"<td>{html.escape(row['name'])}</td>"
        f"<td>{html.escape(row['sasac_name'])}</td>"
        f"<td>{html.escape(row['direction'])}</td>"
        f"<td>{html.escape(row['unit'])}</td>"
        f"<td>{html.escape(row['weight'])}</td>"
        f"<td>{html.escape(row['benchmark'] or '待填')}</td>"
        f"<td class='note-cell'>{html.escape(row['mapping_note'])}</td>"
        "</tr>"
        for row in rows
    )
    html_doc = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>治理优秀值录入工作包</title>
<style>
body{{font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#f7f9fc;color:#24324a;margin:0}}
main{{max-width:1280px;margin:auto;padding:28px 22px}}
.note{{background:#fff4d8;border:1px solid #efd28d;border-radius:10px;padding:14px;margin:16px 0}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f1}}
th,td{{padding:10px;border-bottom:1px solid #edf0f5;text-align:left;vertical-align:top;white-space:normal;word-break:break-word}}
th{{background:#eef3fa;white-space:nowrap}}
td.note-cell{{min-width:220px;color:#53657b}}
code{{color:#4e79ff;white-space:nowrap}}
</style>
<main>
<h1>DL/T 2971 治理优秀值录入工作包</h1>
<p>标准：{html.escape(str(summary.get("standard_ref", "")))}　目标版本：{html.escape(str(summary.get("target_methodology_version", "")))}</p>
<div class="note"><b>使用规则：</b>只从当年《企业绩效评价标准值》抄录工业领域“优秀值”。有映射风险的指标不得擅自用近似项顶替；
填齐 17 项并经方法论负责人确认后，再执行 <code>apply-governance-benchmarks</code>。禁止把网络 OCR 未核验数值冻结为正式方法论。</div>
<p>已填 {summary.get("filled_count", 0)} / {summary.get("row_count", 0)}；直接映射可抄录 {summary.get("direct_copy_count", 0)} 项；需口径确认 {summary.get("mapping_risk_count", 0)} 项。</p>
<table><thead><tr><th>编码</th><th>行标名称</th><th>国资委表头别名</th><th>方向</th><th>单位</th><th>权重</th><th>优秀值</th><th>映射说明</th></tr></thead>
<tbody>{body}</tbody></table>
</main></html>
"""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_doc, encoding="utf-8")


def prepare_governance_benchmark_packet(
    methodology_path: str | Path,
    *,
    csv_path: str | Path,
    html_path: str | Path,
    summary_path: str | Path,
) -> dict[str, Any]:
    methodology = load_methodology(methodology_path)
    rows = build_benchmark_intake_rows(methodology)
    write_benchmark_intake_csv(csv_path, rows)
    filled = sum(1 for row in rows if str(row.get("benchmark") or "").strip())
    risk_codes = {
        "Q_G_EBITDA_MARGIN", "Q_G_CASH_REALIZATION", "Q_G_COST_REVENUE_RATE", "Q_G_TWO_FUNDS_RATE",
    }
    summary = {
        "packet_version": BENCHMARK_PACKET_VERSION,
        "standard_ref": "DL/T 2971—2025",
        "methodology_version": methodology.version,
        "target_methodology_version": GOVERNANCE_BENCHMARK_TARGET_VERSION,
        "row_count": len(rows),
        "filled_count": filled,
        "missing_count": len(rows) - filled,
        "direct_copy_count": len(rows) - len(risk_codes),
        "mapping_risk_count": len(risk_codes),
        "mapping_risk_codes": sorted(risk_codes),
        "csv_path": str(csv_path),
        "html_path": str(html_path),
        "notice": "本工作包只辅助人工抄录；不授权冻结正式方法论。",
    }
    write_benchmark_intake_html(html_path, rows, summary)
    Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _methodology_from_raw(raw: dict[str, Any]) -> Methodology:
    indicators = tuple(
        Indicator(
            code=item["code"],
            dimension=item["dimension"],
            level2=item["level2"],
            name=item["name"],
            kind=IndicatorKind(item["kind"]),
            weight=float(item["weight"]),
            direction=Direction(item.get("direction", "positive")),
            unit=item.get("unit", ""),
            formula=item.get("formula", ""),
            benchmark=item.get("benchmark"),
            key_indicator=bool(item.get("key_indicator", False)),
        )
        for item in raw["indicators"]
    )
    return Methodology(
        version=raw["version"],
        name=raw["name"],
        quantitative_ratio=float(raw.get("quantitative_ratio", 0.8)),
        qualitative_ratio=float(raw.get("qualitative_ratio", 0.2)),
        missing_policy=raw.get("missing_policy", "zero"),
        indicators=indicators,
    )


def apply_governance_benchmarks(
    methodology_path: str | Path,
    benchmark_table_path: str | Path,
    *,
    output_path: str | Path | None = None,
    require_complete: bool = True,
    target_version: str = GOVERNANCE_BENCHMARK_TARGET_VERSION,
) -> dict[str, Any]:
    """把优秀值写入方法论副本；仅在齐全时可冻结为正式DLT版本。"""
    source = Path(methodology_path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    values = read_benchmark_table(benchmark_table_path)
    unknown = sorted(set(values) - set(REQUIRED_GOVERNANCE_CODES))
    if unknown:
        raise ValueError(f"优秀值表包含未知治理指标: {'、'.join(unknown[:5])}")

    updated = 0
    for item in raw["indicators"]:
        code = item["code"]
        if code not in values:
            continue
        item["benchmark"] = values[code]
        updated += 1

    draft = _methodology_from_raw(raw)
    audit = audit_governance_benchmarks(draft)
    if require_complete and not audit["formal_ready"]:
        raise ValueError(audit["blocker"] or "治理优秀值未齐全")

    notes = list(raw.get("notes") or [])
    note = (
        f"已注入国资委工业领域优秀值（来源表：{Path(benchmark_table_path).name}），"
        "治理定量按DL/T 2971附录A优秀值峰打分。"
    )
    if note not in notes:
        notes.append(note)
    raw["notes"] = notes
    if audit["formal_ready"]:
        raw["version"] = target_version
        raw["name"] = "DL/T 2971—2025能源企业ESG披露指标与评价体系（正式）"
        raw["standard_ref"] = "DL/T 2971—2025"
        raw["governance_scoring"] = "sasac_excellence_benchmark"

    destination = Path(output_path) if output_path else source.with_name("energy_esg_dlt2971_v1.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    load_methodology(destination)
    return {
        **audit,
        "updated_count": updated,
        "source_methodology": str(source),
        "benchmark_table": str(benchmark_table_path),
        "output_methodology": str(destination),
        "written_version": raw["version"],
    }
