#!/usr/bin/env python3
"""Discover issuer-website domain candidates for companies still missing verified domains.

Channels (research candidates only; never writes domain_verification=verified):
1. local report text — catch bare www./公司网址 patterns the http-only extractor missed
2. East Money F10 company survey (gswz) for A/B shares
3. optional light HTTPS probe to prefer live candidate_url

Output feeds a human review intake; scoring remains unauthorized.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis_esg.domain_hygiene import (  # noqa: E402
    extract_urls,
    host_from_url,
    is_plausible_issuer_domain,
    normalize_host,
)

QUEUE = ROOT / "output/audit/official_website_source_queue_v1_2025.csv"
INDEXES = (
    ROOT / "data/raw/all_markets_document_index.csv",
    ROOT / "output/sync/official_document_index.csv",
)
GAP_LIST = ROOT / "output/audit/official_domain_missing_companies_v1_2025.csv"
OUT_CAND = ROOT / "output/audit/official_domain_gap_candidates_v1_2025.csv"
OUT_INTAKE = ROOT / "data/review/official_domain_decision_intake_gap_v1_2025.csv"
OUT_SUM = ROOT / "output/audit/official_domain_gap_discovery_v1_2025.json"

WEBSITE_LINE_RE = re.compile(
    r"(?:公司网址|公司网站|互联网地址|企业网址|官方网站|网址|网站)\s*[:：]?\s*"
    r"(?:https?://)?(www\.)?"
    r"([A-Za-z0-9][-A-Za-z0-9.]{1,80}\.(?:com\.cn|com\.hk|net\.cn|org\.cn|[a-z]{2,3}\.cn|com|net|org|cn|hk))",
    re.I,
)
BARE_WWW_RE = re.compile(
    r"(?<![A-Za-z0-9./_-])"
    r"(www\.[A-Za-z0-9][-A-Za-z0-9.]{1,80}\.(?:com\.cn|com\.hk|net\.cn|org\.cn|[a-z]{2,3}\.cn|com|net|org|cn|hk))",
    re.I,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _missing_companies() -> list[dict[str, str]]:
    queue = _read_csv(QUEUE)
    verified = {row["company_code"] for row in queue if row.get("domain_verification") == "verified"}
    names: dict[str, str] = {}
    for row in queue:
        code = row.get("company_code") or ""
        if code and code not in verified:
            names[code] = row.get("company_name") or names.get(code, "")
    rows = [{"company_code": code, "company_name": name} for code, name in sorted(names.items())]
    _write_csv(GAP_LIST, rows, ["company_code", "company_name"])
    return rows


def _resolve_text(local_path: str) -> Path | None:
    source = ROOT / local_path
    for candidate in (
        source.with_suffix(".txt"),
        ROOT / str(local_path).replace("data/raw/", "data/text/").replace(".pdf", ".txt"),
        ROOT / str(local_path).replace("data/raw/ci_collection/", "data/text/ci_collection/").replace(".pdf", ".txt"),
    ):
        if candidate.is_file():
            return candidate
    return None


def _hosts_from_text(content: str) -> list[tuple[str, str]]:
    """Return (host, evidence_snippet) pairs."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(host: str, snippet: str) -> None:
        host = normalize_host(host)
        candidates = [host]
        labels = host.split(".")
        # ny.csg.cn -> also try parent csg.cn when subdomain looks like a portal.
        if len(labels) >= 3:
            candidates.append(".".join(labels[1:]))
        for item in candidates:
            if not is_plausible_issuer_domain(item) or item in seen:
                continue
            seen.add(item)
            found.append((item, snippet[:160].replace("\n", " ")))

    for match in WEBSITE_LINE_RE.finditer(content or ""):
        add(match.group(2), match.group(0))
    for match in BARE_WWW_RE.finditer(content or ""):
        add(match.group(1), match.group(1))
    for url in extract_urls(content or ""):
        add(host_from_url(url), url)
    return found


def discover_from_documents(missing: set[str]) -> dict[str, list[dict[str, str]]]:
    by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_files: set[tuple[str, str]] = set()
    for index in INDEXES:
        for row in _read_csv(index):
            code = (row.get("company_code") or "").strip()
            if code not in missing:
                continue
            # Prefer annual/ESG, but for gaps also accept other issuer filings.
            local = row.get("local_path") or ""
            key = (code, local)
            if key in seen_files:
                continue
            seen_files.add(key)
            text_path = _resolve_text(local)
            if text_path is None:
                continue
            content = text_path.read_text(encoding="utf-8", errors="ignore")
            for host, snippet in _hosts_from_text(content):
                channel = (
                    "document_text_website_field"
                    if ("公司网" in snippet or "互联网" in snippet or "网站" in snippet)
                    else "document_text_url"
                )
                by_code[code].append({
                    "company_code": code,
                    "company_name": row.get("company_name") or "",
                    "official_domain": host,
                    "candidate_url": f"https://{host}/",
                    "source_channel": channel,
                    "evidence_file": str(text_path.relative_to(ROOT)),
                    "evidence_snippet": snippet,
                    "evidence_count": "1",
                })
    # Also scan any leftover local text trees for gap companies with no hit yet.
    for code in sorted(missing):
        if code in by_code:
            continue
        for base in (ROOT / "data/text" / code, ROOT / "data/text/hkex_reports" / code, ROOT / "data/text/ci_collection" / code):
            if not base.is_dir():
                continue
            for text_path in base.rglob("*.txt"):
                content = text_path.read_text(encoding="utf-8", errors="ignore")
                for host, snippet in _hosts_from_text(content):
                    by_code[code].append({
                        "company_code": code,
                        "company_name": "",
                        "official_domain": host,
                        "candidate_url": f"https://{host}/",
                        "source_channel": "document_text_tree_scan",
                        "evidence_file": str(text_path.relative_to(ROOT)),
                        "evidence_snippet": snippet,
                        "evidence_count": "1",
                    })
    # collapse evidence counts
    collapsed: dict[str, list[dict[str, str]]] = {}
    for code, items in by_code.items():
        best: dict[str, dict[str, str]] = {}
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            host = item["official_domain"]
            counts[host] += 1
            prior = best.get(host)
            if prior is None or "公司网" in item.get("evidence_snippet", ""):
                best[host] = item
        for host, item in best.items():
            item = dict(item)
            item["evidence_count"] = str(counts[host])
            collapsed.setdefault(code, []).append(item)
    return collapsed


def _eastmoney_code(company_code: str) -> str | None:
    code, _, market = company_code.partition(".")
    market = market.upper()
    if market == "SZ":
        return f"SZ{code.zfill(6)}"
    if market == "SH":
        return f"SH{code.zfill(6)}"
    if market == "BJ":
        return f"BJ{code.zfill(6)}"
    return None


def discover_from_eastmoney(missing_rows: list[dict[str, str]], *, delay: float, limit: int) -> dict[str, list[dict[str, str]]]:
    import gzip

    ctx = ssl.create_default_context()
    out: dict[str, list[dict[str, str]]] = {}
    done = 0
    for row in missing_rows:
        if limit > 0 and done >= limit:
            break
        code = row["company_code"]
        em = _eastmoney_code(code)
        if not em:
            continue
        url = (
            "https://emweb.securities.eastmoney.com/PC_HSF10/"
            f"CompanySurvey/CompanySurveyAjax?code={em}"
        )
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AegisESG-research/0.3)",
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, identity",
                    "Referer": "https://emweb.securities.eastmoney.com/",
                },
            )
            with urllib.request.urlopen(request, timeout=12, context=ctx) as response:
                raw_bytes = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip" or raw_bytes[:2] == b"\x1f\x8b":
                    raw_bytes = gzip.decompress(raw_bytes)
                payload = json.loads(raw_bytes.decode("utf-8", errors="ignore"))
            gswz = ((payload.get("jbzl") or {}).get("gswz") or "").strip()
            if not gswz or gswz in {"-", "--", "无", "N/A", "不适用"}:
                done += 1
                time.sleep(delay)
                continue
            raw = gswz if "://" in gswz else "https://" + gswz.lstrip("/")
            host = host_from_url(raw) or normalize_host(gswz.removeprefix("www."))
            if not is_plausible_issuer_domain(host):
                done += 1
                time.sleep(delay)
                continue
            out[code] = [{
                "company_code": code,
                "company_name": row.get("company_name") or (payload.get("jbzl") or {}).get("agjc") or "",
                "official_domain": host,
                "candidate_url": f"https://{host}/",
                "source_channel": "eastmoney_f10_gswz",
                "evidence_file": url,
                "evidence_snippet": f"gswz={gswz}",
                "evidence_count": "1",
            }]
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
            pass
        done += 1
        time.sleep(delay)
    return out


def _probe_https(host: str, timeout: float = 8.0) -> str:
    ctx = ssl.create_default_context()
    for url in (f"https://www.{host}/", f"https://{host}/"):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AegisESG-research/0.3)"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
                if 200 <= getattr(response, "status", 200) < 400:
                    return url
        except Exception:  # noqa: BLE001
            continue
    return f"https://{host}/"


def choose_best(candidates: list[dict[str, str]]) -> dict[str, str]:
    """Prefer document website-field hits, then higher evidence, then eastmoney."""
    if not candidates:
        raise ValueError("choose_best requires at least one candidate")
    channel_rank = {
        "document_text_website_field": 0,
        "eastmoney_f10_gswz": 1,
        "document_text_url": 2,
        "document_text_tree_scan": 3,
    }

    def score(item: dict[str, str]) -> tuple:
        snippet = item.get("evidence_snippet") or ""
        try:
            evidence = -int(item.get("evidence_count") or 1)
        except ValueError:
            evidence = 0
        return (
            channel_rank.get(item.get("source_channel") or "", 9),
            0 if "公司网" in snippet or "互联网" in snippet else 1,
            evidence,
            item.get("official_domain") or "",
        )

    return min(candidates, key=score)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-eastmoney", action="store_true")
    parser.add_argument("--eastmoney-limit", type=int, default=0, help="0=all A/B gap companies")
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--probe", action="store_true", help="Probe HTTPS homepage for candidate_url")
    parser.add_argument("--probe-limit", type=int, default=80)
    args = parser.parse_args()

    gaps = _missing_companies()
    missing_codes = {row["company_code"] for row in gaps}
    names = {row["company_code"]: row.get("company_name") or "" for row in gaps}

    doc_hits = discover_from_documents(missing_codes)
    em_hits: dict[str, list[dict[str, str]]] = {}
    if not args.skip_eastmoney:
        need_em = [row for row in gaps if row["company_code"] not in doc_hits]
        em_hits = discover_from_eastmoney(need_em, delay=args.delay, limit=args.eastmoney_limit)

    merged: dict[str, list[dict[str, str]]] = defaultdict(list)
    for code, items in doc_hits.items():
        merged[code].extend(items)
    for code, items in em_hits.items():
        merged[code].extend(items)

    selected_rows: list[dict[str, str]] = []
    all_candidate_rows: list[dict[str, str]] = []
    probed = 0
    for code in sorted(merged):
        items = [item for item in merged[code] if item.get("official_domain")]
        if not items:
            continue
        all_candidate_rows.extend(items)
        best = choose_best(items)
        best = dict(best)
        best["company_name"] = best.get("company_name") or names.get(code, "")
        if args.probe and probed < args.probe_limit:
            best["candidate_url"] = _probe_https(best["official_domain"])
            probed += 1
            time.sleep(args.delay)
        selected_rows.append(best)

    fields = [
        "company_code", "company_name", "official_domain", "candidate_url",
        "source_channel", "evidence_file", "evidence_snippet", "evidence_count",
        "verification_status", "next_action",
    ]
    for row in all_candidate_rows:
        row["verification_status"] = "candidate_unverified_gap_fill"
        row["next_action"] = "人工核验后写入官网域名审核批次"
    for row in selected_rows:
        row["verification_status"] = "candidate_unverified_gap_fill"
        row["next_action"] = "人工核验后写入官网域名审核批次"

    _write_csv(OUT_CAND, selected_rows, fields)
    intake_fields = [
        "company_code", "company_name", "official_domain", "candidate_url",
        "source_channel", "evidence_snippet", "verification_decision", "review_note",
    ]
    intake = [{
        "company_code": row["company_code"],
        "company_name": row["company_name"],
        "official_domain": row["official_domain"],
        "candidate_url": row["candidate_url"],
        "source_channel": row["source_channel"],
        "evidence_snippet": row.get("evidence_snippet", ""),
        "verification_decision": "",
        "review_note": "",
    } for row in selected_rows]
    _write_csv(OUT_INTAKE, intake, intake_fields)

    still = sorted(missing_codes - {row["company_code"] for row in selected_rows})
    summary = {
        "policy_version": "official-domain-gap-discovery-v1",
        "run_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "missing_companies": len(missing_codes),
        "document_hit_companies": len(doc_hits),
        "eastmoney_hit_companies": len([c for c, items in em_hits.items() if items]),
        "selected_candidate_companies": len(selected_rows),
        "still_missing_companies": len(still),
        "still_missing_sample": still[:30],
        "candidates_csv": str(OUT_CAND.relative_to(ROOT)),
        "intake_csv": str(OUT_INTAKE.relative_to(ROOT)),
        "domain_verification": "not_verified",
        "download_authorized": False,
        "scoring_authorized": False,
        "notice": "缺口域名仅为研究候选，须人工核验后才能登记 verified；不得自动代签。",
    }
    OUT_SUM.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
