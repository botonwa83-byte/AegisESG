#!/usr/bin/env python3
"""Fill remaining CI identity gaps from research locals, issuer websites, and cninfo.

Does not mark domains as verified and never authorizes scoring.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.collector import _decode_document, _download_pdf  # noqa: E402
from aegis_esg.domain_hygiene import is_plausible_issuer_domain, normalize_host  # noqa: E402
from aegis_esg.official_report_discovery import (  # noqa: E402
    extract_same_domain_pdf_candidates,
)
from aegis_esg.sources.cninfo import find_disclosure_pdf  # noqa: E402

GAPS = ROOT / "output/audit/remaining_identity_gaps_v1_2025.csv"
RESEARCH = ROOT / "data/raw/all_markets_document_index.csv"
CI_INDEX = ROOT / "output/sync/official_document_index.csv"
CI_ROOT = ROOT / "data/raw/ci_collection"
TEXT_ROOT = ROOT / "data/text/ci_collection"
SUMMARY = ROOT / "output/audit/identity_gap_alternate_fill_v1_2025.json"
DISCOVERY = ROOT / "output/audit/identity_gap_website_discovery_v1_2025.csv"
INDEX_FIELDS = (
    "company_code", "company_name", "report_year", "document_type",
    "source_url", "retrieval_url", "local_path", "sha256", "size",
)
URL_RE = re.compile(
    r"(?:https?://|www\.)([a-zA-Z0-9][-a-zA-Z0-9.]{1,80}\.(?:com(?:\.cn)?|cn|net|org))",
    re.I,
)
BLOCK = (
    "cninfo", "szse", "sse.com", "hkex", "csrc", "chinaclear", "sseinfo", "p5w",
    "eastmoney", "sina", "qq.com", "baidu", "stcn.com", "gdeei", "sthjt", "gov.cn",
    "jiangsu", "zhejiang", "shanghai",
)
SEED_PATHS = (
    "/", "/investor/", "/investor/reports/", "/responsibility/", "/esg/",
    "/about/social/", "/sustainability/", "/ir/", "/tzzgx/", "/shzr/",
)


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_index(rows: list[dict[str, str]]) -> None:
    rows = sorted(rows, key=lambda r: (r["company_code"], r["report_year"], r["document_type"]))
    with CI_INDEX.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _identity(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        (row.get("company_code") or "").strip(),
        str(row.get("report_year") or "").strip(),
        (row.get("document_type") or "").strip(),
    )


def _fetch(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AegisESG-gap-fill/0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _domains_from_text(text: str) -> list[str]:
    found = []
    for match in URL_RE.finditer(text or ""):
        host = normalize_host(match.group(1))
        if any(token in host for token in BLOCK):
            continue
        if not is_plausible_issuer_domain(host):
            continue
        if host not in found:
            found.append(host)
    return found


def _index_pdf(
    *,
    code: str,
    name: str,
    year: str,
    kind: str,
    source_url: str,
    body: bytes,
    rows_by_id: dict[tuple[str, str, str], dict[str, str]],
    channel: str,
) -> dict[str, str]:
    target = CI_ROOT / code / year / f"{kind}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    local = str(target.relative_to(ROOT))
    row = {
        "company_code": code,
        "company_name": name,
        "report_year": year,
        "document_type": kind,
        "source_url": source_url,
        "retrieval_url": f"{source_url}#{channel}",
        "local_path": local,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size": str(len(body)),
    }
    rows_by_id[(code, year, kind)] = row
    return row


def main() -> None:
    gaps = _read(GAPS)
    research = {
        _identity(row): row
        for row in _read(RESEARCH)
        if _identity(row)[0]
    }
    ci_rows = _read(CI_INDEX)
    rows_by_id = {_identity(row): row for row in ci_rows if _identity(row)[0]}
    actions = []
    discoveries = []

    # Phase A: import from research local PDFs.
    for gap in gaps:
        key = _identity(gap)
        if key in rows_by_id:
            actions.append({"company_code": key[0], "document_type": key[2], "action": "already_indexed"})
            continue
        src = research.get(key)
        if not src:
            continue
        path = Path(src.get("local_path") or "")
        if not path.is_file():
            path = ROOT / path
        if not path.is_file():
            actions.append({"company_code": key[0], "document_type": key[2], "action": "research_path_missing"})
            continue
        body = path.read_bytes()
        try:
            body = _decode_document(body, "", str(path))
        except ValueError as error:
            actions.append({"company_code": key[0], "document_type": key[2], "action": "research_invalid_pdf", "error": str(error)[:160]})
            continue
        source_url = (src.get("source_url") or "").strip() or f"research://{key[0]}/{key[1]}/{key[2]}"
        _index_pdf(
            code=key[0], name=gap.get("company_name") or src.get("company_name") or "",
            year=key[1], kind=key[2], source_url=source_url, body=body,
            rows_by_id=rows_by_id, channel="research_import",
        )
        actions.append({
            "company_code": key[0], "document_type": key[2],
            "action": "imported_from_research", "source_url": source_url, "bytes": len(body),
        })

    # Phase B/C: website discovery + download for still-missing gaps.
    still = [gap for gap in gaps if _identity(gap) not in rows_by_id]
    for gap in still:
        key = _identity(gap)
        code, year, kind = key
        text_path = TEXT_ROOT / code / year / "annual_report.txt"
        if not text_path.is_file():
            text_path = ROOT / "data/text" / code / year / "annual_report.txt"
        domains = _domains_from_text(text_path.read_text(encoding="utf-8", errors="ignore") if text_path.is_file() else "")
        if not domains:
            actions.append({"company_code": code, "document_type": kind, "action": "no_plausible_domain"})
            continue
        downloaded = False
        for domain in domains[:3]:
            for seed in SEED_PATHS:
                page_url = f"https://{domain}{seed}"
                try:
                    html = _fetch(page_url)
                except Exception as error:  # noqa: BLE001
                    discoveries.append({
                        "company_code": code, "company_name": gap.get("company_name", ""),
                        "report_year": year, "document_type": kind, "official_domain": domain,
                        "source_url": "", "page_url": page_url, "status": "fetch_failed",
                        "error": str(error)[:160],
                    })
                    continue
                hits = [
                    hit for hit in extract_same_domain_pdf_candidates(
                        page_url, html, official_domain=domain, report_year=int(year),
                    )
                    if hit["document_type"] == kind
                ]
                for hit in hits:
                    discoveries.append({
                        "company_code": code, "company_name": gap.get("company_name", ""),
                        "report_year": year, "document_type": kind, "official_domain": domain,
                        "source_url": hit["source_url"], "page_url": page_url,
                        "status": "candidate", "error": "",
                    })
                    try:
                        body, retrieval = _download_pdf(hit["source_url"])
                        _index_pdf(
                            code=code, name=gap.get("company_name", ""), year=year, kind=kind,
                            source_url=hit["source_url"], body=body, rows_by_id=rows_by_id,
                            channel=f"issuer_website:{domain}",
                        )
                        actions.append({
                            "company_code": code, "document_type": kind,
                            "action": "downloaded_from_issuer_website",
                            "domain": domain, "source_url": hit["source_url"],
                            "retrieval_url": retrieval, "bytes": len(body),
                        })
                        downloaded = True
                        break
                    except Exception as error:  # noqa: BLE001
                        actions.append({
                            "company_code": code, "document_type": kind,
                            "action": "website_download_failed",
                            "domain": domain, "source_url": hit["source_url"],
                            "error": str(error)[:200],
                        })
                if downloaded:
                    break
            if downloaded:
                break
        if not downloaded and not any(a.get("company_code") == code and a.get("document_type") == kind and a.get("action", "").startswith("downloaded") for a in actions):
            if not any(a.get("company_code") == code and a.get("document_type") == kind for a in actions):
                actions.append({"company_code": code, "document_type": kind, "action": "website_no_pdf_found", "domains": domains[:3]})

    # Phase C: cninfo (exchange-designated disclosure) as alternate download channel.
    still = [gap for gap in gaps if _identity(gap) not in rows_by_id]
    for gap in still:
        key = _identity(gap)
        code, year, kind = key
        try:
            hit = find_disclosure_pdf(code, year, kind)
        except Exception as error:  # noqa: BLE001
            actions.append({
                "company_code": code, "document_type": kind,
                "action": "cninfo_query_failed", "error": str(error)[:200],
            })
            continue
        if not hit:
            actions.append({"company_code": code, "document_type": kind, "action": "cninfo_no_match"})
            continue
        title, source_url = hit
        try:
            body, retrieval = _download_pdf(source_url)
            _index_pdf(
                code=code, name=gap.get("company_name", ""), year=year, kind=kind,
                source_url=source_url, body=body, rows_by_id=rows_by_id,
                channel="cninfo_disclosure",
            )
            actions.append({
                "company_code": code, "document_type": kind,
                "action": "downloaded_from_cninfo",
                "title": title, "source_url": source_url,
                "retrieval_url": retrieval, "bytes": len(body),
            })
        except Exception as error:  # noqa: BLE001
            actions.append({
                "company_code": code, "document_type": kind,
                "action": "cninfo_download_failed",
                "source_url": source_url, "error": str(error)[:200],
            })
        time.sleep(0.3)

    _write_index(list(rows_by_id.values()))
    DISCOVERY.parent.mkdir(parents=True, exist_ok=True)
    with DISCOVERY.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = (
            "company_code", "company_name", "report_year", "document_type",
            "official_domain", "source_url", "page_url", "status", "error",
        )
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(discoveries)

    fill_actions = {
        "imported_from_research",
        "downloaded_from_issuer_website",
        "downloaded_from_cninfo",
    }
    filled = sum(1 for a in actions if a.get("action") in fill_actions)
    still_missing = sum(1 for gap in gaps if _identity(gap) not in rows_by_id)
    summary = {
        "policy_version": "identity-gap-alternate-fill-v2",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "gap_input": len(gaps),
        "filled_count": filled,
        "still_missing": still_missing,
        "actions": actions,
        "discovery_rows": len(discoveries),
        "discovery_csv": str(DISCOVERY.relative_to(ROOT)),
        "domain_verification_claimed": False,
        "scoring_authorized": False,
        "formal_publishable": False,
        "notice": "研究底座导入、年报自披露域名同域下载，或巨潮法定披露备用渠道；不宣称域名已核验，不授权评分。",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
