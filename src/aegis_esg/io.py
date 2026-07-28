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


def write_ranking_csv(
    path: str | Path,
    results: list[CompanyResult],
    methodology: Methodology,
    limit: int = 200,
) -> None:
    key_indicators = [i for i in methodology.quantitative if i.key_indicator]
    headers = ["序号", "证券代码", "公司简称", "数值类别"]
    headers.extend(i.name for i in key_indicators)
    headers.append("可持续发展(ESG)分值")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for result in results[:limit]:
            detail = {d.indicator_code: d for d in result.details}
            raw_row = [result.rank, result.company_code, result.company_name, "指标数值"]
            score_row = [result.rank, result.company_code, result.company_name, "指标分值"]
            for indicator in key_indicators:
                item = detail[indicator.code]
                raw_row.append("" if item.raw_value is None else _number(item.raw_value))
                score_row.append("" if item.raw_value is None else _number(item.weighted_score))
            raw_row.append(_number(result.total_score))
            score_row.append("")
            writer.writerow(raw_row)
            writer.writerow(score_row)


def write_ranking_json(path: str | Path, results: list[CompanyResult], limit: int = 200) -> None:
    data = [item.to_dict() for item in results[:limit]]
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_ranking_html(
    path: str | Path,
    results: list[CompanyResult],
    methodology: Methodology,
    title: str,
    limit: int = 200,
) -> None:
    key_indicators = [i for i in methodology.quantitative if i.key_indicator]
    rows = []
    for result in results[:limit]:
        detail = {d.indicator_code: d for d in result.details}
        cells = "".join(
            f"<td><div>{_number(detail[i.code].raw_value) if detail[i.code].raw_value is not None else '-'}</div>"
            f"<small>{_number(detail[i.code].weighted_score) if detail[i.code].raw_value is not None else '-'}</small></td>"
            for i in key_indicators
        )
        rows.append(
            f"<tr><td>{result.rank}</td><td>{_escape(result.company_code)}</td>"
            f"<td>{_escape(result.company_name)}</td>{cells}<td class='score'>{result.total_score:.2f}</td></tr>"
        )
    headers = "".join(f"<th>{_escape(i.name)}<br><small>数值/分值</small></th>" for i in key_indicators)
    html = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<title>{_escape(title)}</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;margin:24px;color:#173d45}}
h1{{text-align:center;color:#174c72}} table{{border-collapse:collapse;width:100%;font-size:12px}}
th{{background:#207f8b;color:white;position:sticky;top:0}} th,td{{border:1px solid #aac9c7;padding:5px;text-align:center}}
tr:nth-child(even){{background:#eef8f6}} td small{{color:#557d7c}} .score{{color:#d22;font-weight:700;font-size:14px}}
@media print{{body{{margin:8mm}} th{{position:static}} @page{{size:A3 landscape}}}}
</style></head><body><h1>{_escape(title)}</h1><table><thead><tr>
<th>序号</th><th>证券代码</th><th>公司简称</th>{headers}<th>可持续发展<br>(ESG)分值</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    Path(path).write_text(html, encoding="utf-8")


def write_observation_template(path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerow(OBSERVATION_COLUMNS)


def write_observations(path: str | Path, observations: list[Observation]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OBSERVATION_COLUMNS)
        writer.writeheader()
        for item in observations:
            writer.writerow({
                "company_code": item.company_code,
                "company_name": item.company_name,
                "report_year": item.report_year,
                "indicator_code": item.indicator_code,
                "value": "" if item.value is None else _number(item.value),
                "status": item.status.value,
                "source_url": item.source_url,
                "source_file": item.source_file,
                "source_page": "" if item.source_page is None else item.source_page,
                "evidence_text": item.evidence_text,
                "confidence": item.confidence,
            })



def _number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _escape(value: str) -> str:
    import html
    return html.escape(value, quote=True)
