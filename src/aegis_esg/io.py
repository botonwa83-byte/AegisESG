from __future__ import annotations

import csv
import json
from pathlib import Path

from .methodology import Methodology
from .models import CompanyResult, Observation, ValueStatus


OBSERVATION_COLUMNS = (
    "company_code", "company_name", "report_year", "indicator_code", "value",
    "status", "source_url", "source_file", "source_page", "evidence_text", "confidence",
)


def read_observations(path: str | Path, methodology: Methodology) -> list[Observation]:
    result: list[Observation] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            code = (row.get("indicator_code") or "").strip()
            if code not in methodology.by_code:
                raise ValueError(f"第{line}行包含未知指标编码: {code}")
            raw_value = (row.get("value") or "").strip()
            status = ValueStatus((row.get("status") or "confirmed").strip())
            if status == ValueStatus.CONFIRMED and not raw_value:
                raise ValueError(f"第{line}行状态为confirmed但没有value")
            result.append(Observation(
                company_code=(row.get("company_code") or "").strip(),
                company_name=(row.get("company_name") or "").strip(),
                report_year=int(row["report_year"]),
                indicator_code=code,
                value=float(raw_value) if raw_value else None,
                status=status,
                source_url=(row.get("source_url") or "").strip(),
                source_file=(row.get("source_file") or "").strip(),
                source_page=int(row["source_page"]) if (row.get("source_page") or "").strip() else None,
                evidence_text=(row.get("evidence_text") or "").strip(),
                confidence=float(row.get("confidence") or 1),
            ))
    return result


def _ranking_slice(results: list[CompanyResult], limit: int | None) -> list[CompanyResult]:
    """``limit is None`` or ``limit <= 0`` means export the full scored universe."""
    if limit is None or limit <= 0:
        return list(results)
    return list(results[:limit])


def write_ranking_csv(
    path: str | Path,
    results: list[CompanyResult],
    methodology: Methodology,
    limit: int | None = None,
) -> None:
    key_indicators = [i for i in methodology.quantitative if i.key_indicator]
    headers = ["序号", "证券代码", "公司简称", "数值类别", "披露率%", "定量分", "定性分"]
    headers.extend(i.name for i in key_indicators)
    headers.append("可持续发展(ESG)分值")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for result in _ranking_slice(results, limit):
            detail = {d.indicator_code: d for d in result.details}
            raw_row = [
                result.rank, result.company_code, result.company_name, "指标数值",
                result.disclosure_rate, result.quantitative_score, result.qualitative_score,
            ]
            score_row = [
                result.rank, result.company_code, result.company_name, "指标分值",
                "", "", "",
            ]
            for indicator in key_indicators:
                item = detail[indicator.code]
                raw_row.append("" if item.raw_value is None else _number(item.raw_value))
                score_row.append("" if item.raw_value is None else _number(item.weighted_score))
            raw_row.append(_number(result.total_score))
            score_row.append("")
            writer.writerow(raw_row)
            writer.writerow(score_row)


def write_ranking_json(path: str | Path, results: list[CompanyResult], limit: int | None = None) -> None:
    data = [item.to_dict() for item in _ranking_slice(results, limit)]
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_ranking_html(
    path: str | Path,
    results: list[CompanyResult],
    methodology: Methodology,
    title: str,
    limit: int | None = None,
) -> None:
    key_indicators = [i for i in methodology.quantitative if i.key_indicator]
    exported = _ranking_slice(results, limit)
    rows = []
    for result in exported:
        detail = {d.indicator_code: d for d in result.details}
        cells = "".join(
            f"<td><div>{_number(detail[i.code].raw_value) if detail[i.code].raw_value is not None else '-'}</div>"
            f"<small>{_number(detail[i.code].weighted_score) if detail[i.code].raw_value is not None else '-'}</small></td>"
            for i in key_indicators
        )
        rows.append(
            f"<tr><td>{result.rank}</td><td>{_escape(result.company_code)}</td>"
            f"<td>{_escape(result.company_name)}</td>"
            f"<td>{result.disclosure_rate:.1f}%</td>"
            f"<td>{result.quantitative_score:.2f}</td><td>{result.qualitative_score:.2f}</td>"
            f"{cells}<td class='score'>{result.total_score:.2f}</td></tr>"
        )
    headers = "".join(f"<th>{_escape(i.name)}<br><small>数值/分值</small></th>" for i in key_indicators)
    note = (
        f"<p class='note'>本表共 <b>{len(exported)}</b> 家（引擎已评分 {len(results)} 家）。"
        f"表中仅展示 <b>{len(key_indicators)}</b> 项定量关键指标；空值“-”表示交易所披露中未见该项，"
        f"按研究规则<strong>计 0 分</strong>（缺失策略 <code>legacy_zero_v1</code>）。"
        f"关键指标以相关证券交易所披露为准，研究模式不另做原始值人工确认。"
        f"总分 = 定量分×{methodology.quantitative_ratio:.0%} + 定性分×{methodology.qualitative_ratio:.0%}。"
        f"完整 80 项明细见 ranking.json 的 details。目标主体 632 家，当前研究池不足部分需补主体名录。</p>"
    )
    html = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<title>{_escape(title)}</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;margin:24px;color:#173d45}}
h1{{text-align:center;color:#174c72}} .note{{max-width:1200px;margin:0 auto 16px;line-height:1.6;color:#355}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th{{background:#207f8b;color:white;position:sticky;top:0}} th,td{{border:1px solid #aac9c7;padding:5px;text-align:center}}
tr:nth-child(even){{background:#eef8f6}} td small{{color:#557d7c}} .score{{color:#d22;font-weight:700;font-size:14px}}
@media print{{body{{margin:8mm}} th{{position:static}} @page{{size:A3 landscape}}}}
</style></head><body><h1>{_escape(title)}</h1>{note}<table><thead><tr>
<th>序号</th><th>证券代码</th><th>公司简称</th><th>披露率</th><th>定量分</th><th>定性分</th>{headers}<th>可持续发展<br>(ESG)分值</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    Path(path).write_text(html, encoding="utf-8")


def write_observation_template(path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerow(OBSERVATION_COLUMNS)


def write_observations(path: str | Path, observations: list[Observation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OBSERVATION_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in observations:
            writer.writerow({
                "company_code": item.company_code,
                "company_name": item.company_name,
                "report_year": item.report_year,
                "indicator_code": item.indicator_code,
                "value": "" if item.value is None else _observation_number(item.value),
                "status": item.status.value,
                "source_url": item.source_url,
                "source_file": item.source_file,
                "source_page": "" if item.source_page is None else item.source_page,
                "evidence_text": item.evidence_text,
                "confidence": item.confidence,
            })



def merge_confirmed_observations(
    paths: list[str | Path], methodology: Methodology,
) -> tuple[list[Observation], dict]:
    if not paths:
        raise ValueError("至少需要一个确认观测输入")
    merged: dict[tuple[str, int, str], Observation] = {}
    per_file = []
    for path in paths:
        observations = read_observations(path, methodology)
        not_confirmed = [item for item in observations if item.status != ValueStatus.CONFIRMED]
        if not_confirmed:
            raise ValueError(f"{path}存在非confirmed观测，禁止并入正式评分输入")
        per_file.append({"path": str(path), "observation_count": len(observations)})
        for item in observations:
            key = (item.company_code, item.report_year, item.indicator_code)
            existing = merged.get(key)
            if existing is None:
                merged[key] = item
                continue
            if existing.value != item.value:
                raise ValueError(
                    f"确认观测冲突: {item.company_code}/{item.report_year}/{item.indicator_code} "
                    f"{existing.value} != {item.value}，禁止静默选值"
                )
    rows = [merged[key] for key in sorted(merged)]
    summary = {
        "input_files": per_file,
        "merged_observation_count": len(rows),
        "company_count": len({item.company_code for item in rows}),
        "duplicate_conflicts": 0,
        "publishable": False,
    }
    return rows, summary


def _number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _observation_number(value: float) -> str:
    """Preserve small auditable measurements; presentation rounding belongs to rankings."""
    return format(value, ".12g")


def _escape(value: str) -> str:
    import html
    return html.escape(value, quote=True)
