from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from aegis_esg.sources.cninfo import find_disclosure_pdf, should_try_cninfo_fallback


@dataclass(frozen=True)
class DocumentRecord:
    company_code: str
    company_name: str
    report_year: int
    document_type: str
    source_url: str
    retrieval_url: str
    local_path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class CollectionFailure:
    company_code: str
    company_name: str
    report_year: int
    document_type: str
    source_url: str
    error: str


def collect_from_manifest(
    manifest_path: str | Path,
    output_root: str | Path,
    delay_seconds: float = 1.0,
) -> list[DocumentRecord]:
    """按经审核的公开URL清单下载文档。

    清单模式避免把特定网站的非公开接口或绕过反爬逻辑写进系统。上游可由
    巨潮资讯、交易所、公司官网或合规数据服务生成，下载过程保留URL和Hash。
    """
    output_root = Path(output_root)
    records: list[DocumentRecord] = []
    with Path(manifest_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows.sort(key=lambda row: (row["document_type"].strip() != "annual_report", row["company_code"].strip()))
    for index, row in enumerate(rows):
        code = row["company_code"].strip()
        year = int(row["report_year"])
        kind = row["document_type"].strip()
        url = row["source_url"].strip()
        suffix = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".pdf"
        target = output_root / code / str(year) / f"{kind}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        body, retrieval_url = _download_pdf(url)
        target.write_bytes(body)
        records.append(DocumentRecord(
            company_code=code,
            company_name=row["company_name"].strip(),
            report_year=year,
            document_type=kind,
            source_url=url,
            retrieval_url=retrieval_url,
            local_path=str(target),
            sha256=hashlib.sha256(body).hexdigest(),
            size=len(body),
        ))
        if index + 1 < len(rows):
            time.sleep(delay_seconds)
    return records


def collect_batch(
    manifest_path: str | Path,
    output_root: str | Path,
    index_path: str | Path,
    failure_path: str | Path,
    delay_seconds: float = 1.0,
    reuse_existing: bool = True,
    workers: int = 1,
    reuse_indexes: list[str] | None = None,
    preserve_index: bool = False,
    max_minutes: float | None = None,
    document_priority: str = "esg",
) -> tuple[list[DocumentRecord], list[CollectionFailure]]:
    """Resumable collector: reuse valid PDFs and checkpoint after every manifest row.

    ``max_minutes`` is a soft wall-clock budget. When set, the collector stops
    launching new work after the budget elapses, cancels pending downloads, and
    returns whatever has already been checkpointed. This keeps a CI hard timeout
    from wasting in-flight bytes; the next run resumes from the flushed index.

    ``document_priority`` is ``esg`` (default) or ``annual``. ESG is launched first
    because scheduled coverage gaps are concentrated in independent ESG reports.
    """
    output_root = Path(output_root)
    primary_index = _read_document_index(index_path)
    previous = dict(primary_index)
    records: list[DocumentRecord] = list(primary_index.values()) if preserve_index else []
    failures: list[CollectionFailure] = []
    trusted_by_path: dict[str, DocumentRecord] = {}
    for reuse_index in reuse_indexes or []:
        for source_url, record in _read_document_index(reuse_index).items():
            previous.setdefault(source_url, record)
            trusted_by_path[record.local_path] = record
    with Path(manifest_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    prefer_esg = (document_priority or "esg").strip().lower() != "annual"
    rows.sort(
        key=lambda row: (
            row["document_type"].strip() != ("esg_report" if prefer_esg else "annual_report"),
            row["company_code"].strip(),
        )
    )
    if reuse_existing:
        rows = [row for row in rows if row["source_url"].strip() not in previous]

    def collect_one(row: dict[str, str]) -> DocumentRecord:
        code = row["company_code"].strip()
        name = row["company_name"].strip()
        year = int(row["report_year"])
        if year < 1990 or year > 2100:
            raise ValueError(f"非法报告年份: {year}")
        kind = row["document_type"].strip()
        url = row["source_url"].strip()
        suffix = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".pdf"
        target = output_root / code / str(year) / f"{kind}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        old = previous.get(url)
        if old is None:
            trusted = trusted_by_path.get(str(target))
            if trusted is not None and (
                trusted.company_code, trusted.report_year, trusted.document_type
            ) == (code, year, kind):
                old = trusted
        can_reuse = reuse_existing and target.exists() and old is not None and Path(old.local_path) == target
        if can_reuse:
            body = _decode_document(target.read_bytes(), "", str(target))
            digest = hashlib.sha256(body).hexdigest()
            if digest != old.sha256 or len(body) != old.size:
                raise ValueError(f"本地PDF与断点索引不一致: {target}")
            retrieval_url = old.retrieval_url
        else:
            body, retrieval_url = _download_with_optional_cninfo(url, code, year, kind)
            # Prefer the successful retrieval host as indexed source when fallback wins.
            if "cninfo.com.cn" in retrieval_url and "cninfo.com.cn" not in url:
                url = retrieval_url.split("#", 1)[0]
            target.write_bytes(body)
        return DocumentRecord(
            company_code=code, company_name=name, report_year=year, document_type=kind,
            source_url=url, retrieval_url=retrieval_url, local_path=str(target),
            sha256=hashlib.sha256(body).hexdigest(), size=len(body),
        )

    if not rows:
        compact = dedupe_document_records(records)
        write_document_index(index_path, compact)
        write_collection_failures(failure_path, failures)
        return compact, failures

    executor = ThreadPoolExecutor(max_workers=max(1, workers))
    pending_rows = list(rows)
    in_flight: dict = {}
    started = _clock()
    budget_seconds = max_minutes * 60.0 if max_minutes else None
    timed_out = False

    def budget_exhausted() -> bool:
        return budget_seconds is not None and _clock() - started >= budget_seconds

    def launch_available() -> None:
        while pending_rows and len(in_flight) < max(1, workers):
            if budget_exhausted():
                return
            row = pending_rows.pop(0)
            in_flight[executor.submit(collect_one, row)] = row

    launch_available()
    while in_flight:
        for future in as_completed(list(in_flight)):
            row = in_flight.pop(future)
            try:
                record = future.result()
                records = _upsert_document_record(records, record)
            except Exception as error:
                failures.append(CollectionFailure(
                    company_code=row["company_code"].strip(), company_name=row["company_name"].strip(),
                    report_year=int(row["report_year"]), document_type=row["document_type"].strip(),
                    source_url=row["source_url"].strip(), error=str(error),
                ))
            records = dedupe_document_records(records)
            write_document_index(index_path, records)
            write_collection_failures(failure_path, failures)
            if budget_exhausted():
                timed_out = True
                pending_rows.clear()
            else:
                launch_available()
            break
    if timed_out:
        for pending in list(in_flight):
            pending.cancel()
    executor.shutdown(wait=False, cancel_futures=True)
    return dedupe_document_records(records), failures


def document_identity(record: DocumentRecord) -> tuple[str, int, str]:
    return (record.company_code, record.report_year, record.document_type)


def _upsert_document_record(records: list[DocumentRecord], record: DocumentRecord) -> list[DocumentRecord]:
    identity = document_identity(record)
    kept = [
        item for item in records
        if item.source_url != record.source_url and document_identity(item) != identity
    ]
    kept.append(record)
    return kept


def dedupe_document_records(records: list[DocumentRecord]) -> list[DocumentRecord]:
    """Keep one record per company/year/type, preferring valid years and existing files."""
    best: dict[tuple[str, int, str], DocumentRecord] = {}
    for record in records:
        if record.report_year < 1990 or record.report_year > 2100:
            continue
        key = document_identity(record)
        current = best.get(key)
        if current is None:
            best[key] = record
            continue
        current_exists = Path(current.local_path).is_file()
        candidate_exists = Path(record.local_path).is_file()
        if candidate_exists and not current_exists:
            best[key] = record
        elif candidate_exists == current_exists and record.size >= current.size:
            best[key] = record
    result = list(best.values())
    result.sort(key=lambda item: (item.company_code, item.report_year, item.document_type, item.source_url))
    return result


def _clock() -> float:
    """Module-local monotonic clock so tests can stub the budget without
    perturbing ``concurrent.futures``' own use of ``time.monotonic``."""
    return time.monotonic()


def _szse_curl_max_time() -> int:
    """SZSE ESG PDFs are often large; allow env override for overnight resumes."""
    raw = os.getenv("AEGIS_SZSE_CURL_MAX_TIME", "1200").strip()
    try:
        value = int(raw)
    except ValueError:
        return 1200
    return value if value > 30 else 1200


def _http_curl_max_time() -> int:
    """Fallback curl budget for SSE/HKEX when urllib hits SSL/reset/timeouts."""
    raw = os.getenv("AEGIS_HTTP_CURL_MAX_TIME", "300").strip()
    try:
        value = int(raw)
    except ValueError:
        return 300
    return value if value > 30 else 300


def _download_with_optional_cninfo(
    url: str,
    company_code: str,
    report_year: int,
    document_type: str,
) -> tuple[bytes, str]:
    """Download primary URL; on SZSE antibot/invalid PDF, try cninfo static PDF."""
    try:
        return _download_pdf(url)
    except Exception as error:
        if not should_try_cninfo_fallback(url, str(error)):
            raise
        hit = find_disclosure_pdf(company_code, report_year, document_type)
        if not hit:
            raise ValueError(f"{error}；巨潮备用未命中") from error
        _title, alt_url = hit
        body, retrieval = _download_pdf(alt_url)
        return body, f"{retrieval}#cninfo_fallback"


def _download_pdf(url: str) -> tuple[bytes, str]:
    errors: list[str] = []
    for candidate in _download_candidates(url):
        if "disc.static.szse.cn" in candidate:
            try:
                return _download_with_curl(
                    candidate,
                    referer="https://www.szse.cn/disclosure/",
                    max_time=_szse_curl_max_time(),
                    prefix="aegis_szse_",
                )
            except Exception as error:
                errors.append(f"{candidate}: {error}")
                continue
        request = urllib.request.Request(
            candidate,
            headers={
                "Referer": _referer_for(candidate),
                "User-Agent": "AegisESG/0.2 public-disclosure-collector",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=_http_urlopen_timeout()) as response:
                body = _decode_document(
                    response.read(), response.headers.get("Content-Encoding", ""), candidate
                )
            return body, candidate
        except Exception as error:
            errors.append(f"{candidate}: {error}")
            # Overnight residual gaps are concentrated on SSE/HKEX transport failures.
            try:
                return _download_with_curl(
                    candidate,
                    referer=_referer_for(candidate),
                    max_time=_http_curl_max_time(),
                    prefix="aegis_http_",
                )
            except Exception as curl_error:
                errors.append(f"{candidate}[curl]: {curl_error}")
    raise ValueError("公开PDF下载失败；" + " | ".join(errors))


def _http_urlopen_timeout() -> int:
    raw = os.getenv("AEGIS_HTTP_URLOPEN_TIMEOUT", "90").strip()
    try:
        value = int(raw)
    except ValueError:
        return 90
    return value if value > 10 else 90


def _referer_for(url: str) -> str:
    if "hkexnews.hk" in url:
        return "https://www1.hkexnews.hk/"
    if "sse.com.cn" in url:
        return "https://www.sse.com.cn/"
    if "szse.cn" in url:
        return "https://www.szse.cn/disclosure/"
    if "cninfo.com.cn" in url:
        return "https://www.cninfo.com.cn/"
    return "https://www.sse.com.cn/"


def _download_with_curl(url: str, *, referer: str, max_time: int, prefix: str) -> tuple[bytes, str]:
    partial = Path(tempfile.gettempdir()) / f"{prefix}{hashlib.sha256(url.encode()).hexdigest()}.part"
    if partial.exists() and partial.read_bytes()[:5] != b"%PDF-":
        partial.unlink()
    result = subprocess.run([
        "curl", "-fsSL", "-C", "-",
        "--max-time", str(max_time),
        "--connect-timeout", "20",
        "-A", "AegisESG/0.2 public-disclosure-collector",
        "-e", referer,
        "-o", str(partial), url,
    ], capture_output=True, timeout=max_time + 30)
    if result.returncode:
        raise ValueError(
            f"curl退出码{result.returncode}; 已保留{partial.stat().st_size if partial.exists() else 0}字节分片; "
            + result.stderr.decode("utf-8", errors="replace")[-300:]
        )
    try:
        body = _decode_document(partial.read_bytes(), "", url)
    except ValueError:
        if partial.exists() and not partial.read_bytes()[:5] == b"%PDF-":
            partial.unlink()
        raise
    partial.unlink()
    return body, url


def _download_candidates(url: str) -> list[str]:
    candidates = [url]
    prefix = "https://www.sse.com.cn/"
    if url.startswith(prefix):
        candidates.append("https://big5.sse.com.cn/site/cht/www.sse.com.cn/" + url[len(prefix):])
    return candidates


def _decode_document(body: bytes, content_encoding: str, url: str) -> bytes:
    if "gzip" in content_encoding.lower() or body.startswith(b"\x1f\x8b"):
        body = gzip.decompress(body)
    if not body.startswith(b"%PDF-"):
        preview = body[:80].decode("utf-8", errors="replace")
        raise ValueError(f"公开文档不是有效PDF: {url}; response={preview!r}")
    if len(body) < 10_000:
        raise ValueError(f"公开PDF尺寸异常: {url}; size={len(body)}")
    return body


_SUPERSEDE_REQUEST_FIELDS = ("company_code", "report_year", "document_type", "reason")
_SUPERSEDE_LEDGER_FIELDS = tuple(DocumentRecord.__annotations__) + ("archive_path", "reason", "superseded_at")


def supersede_documents(
    index_path: str | Path,
    requests_path: str | Path,
    archive_root: str | Path,
    ledger_path: str | Path,
    summary_path: str | Path,
) -> tuple[list[DocumentRecord], list[dict], dict]:
    """归档被误登记的文档并从索引移除，保留逐条取代账本。

    只处理请求中明确列出的（公司、年度、文档类型）；本地文件必须存在且与索引
    Hash一致才允许归档，拒绝静默丢弃无法复现的字节。
    """
    index_path = Path(index_path)
    records = list(_read_document_index(index_path).values())
    with Path(requests_path).open(encoding="utf-8-sig", newline="") as stream:
        requests = list(csv.DictReader(stream))
    if not requests:
        raise ValueError("取代请求清单为空")
    archive_root = Path(archive_root)
    ledger_path = Path(ledger_path)
    existing_ledger: list[dict] = []
    if ledger_path.exists():
        with ledger_path.open(encoding="utf-8-sig", newline="") as stream:
            existing_ledger = list(csv.DictReader(stream))
    seen_keys = {
        (row["company_code"], row["report_year"], row["document_type"], row["sha256"])
        for row in existing_ledger
    }
    pending: list[tuple[DocumentRecord, str, Path, bool, bool]] = []
    seen_requests: set[tuple[str, int, str]] = set()
    for line, row in enumerate(requests, 2):
        try:
            code = row["company_code"].strip().upper()
            year = int(row["report_year"])
            kind = row["document_type"].strip()
            reason = row["reason"].strip()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"取代请求第{line}行格式错误") from error
        if not code or not kind or not reason:
            raise ValueError(f"取代请求第{line}行缺少公司、类型或原因")
        request_key = (code, year, kind)
        if request_key in seen_requests:
            raise ValueError(f"取代请求第{line}行与前序请求重复: {code} {kind}")
        seen_requests.add(request_key)
        matches = [
            item for item in records
            if (item.company_code, item.report_year, item.document_type) == request_key
        ]
        if len(matches) != 1:
            raise ValueError(f"取代请求第{line}行在索引中匹配{len(matches)}条记录: {code} {kind}")
        record = matches[0]
        local = Path(record.local_path)
        archive_path = archive_root / code / str(year) / f"{kind}_{record.sha256[:8]}{local.suffix}"
        archive_ok = (
            archive_path.exists()
            and hashlib.sha256(archive_path.read_bytes()).hexdigest() == record.sha256
        )
        ledger_key = (record.company_code, str(record.report_year), record.document_type, record.sha256)
        already_ledgered = ledger_key in seen_keys
        if archive_path.exists() and not archive_ok:
            raise ValueError(f"归档路径已存在且Hash不同，拒绝覆盖: {archive_path}")
        move_local = False
        if not archive_ok:
            if not local.exists():
                raise ValueError(f"待归档本地文件不存在且无一致归档: {local}")
            body = local.read_bytes()
            if hashlib.sha256(body).hexdigest() != record.sha256 or len(body) != record.size:
                raise ValueError(f"待归档文件与索引Hash不一致: {local}")
            move_local = True
        seen_keys.add(ledger_key)
        pending.append((record, reason, archive_path, move_local, already_ledgered))
    new_ledger_rows: list[dict] = []
    for record, reason, archive_path, move_local, already_ledgered in pending:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if move_local:
            local = Path(record.local_path)
            if archive_path.exists():
                local.unlink()
            else:
                local.replace(archive_path)
        records.remove(record)
        if already_ledgered:
            continue
        new_ledger_rows.append({
            **vars(record),
            "archive_path": str(archive_path),
            "reason": reason,
            "superseded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    records.sort(key=lambda item: (item.company_code, item.report_year, item.document_type, item.source_url))
    write_document_index(index_path, records)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(_SUPERSEDE_LEDGER_FIELDS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(existing_ledger + new_ledger_rows)
    summary = {
        "document_index": str(index_path),
        "superseded_count": len(new_ledger_rows),
        "ledger_total_count": len(existing_ledger) + len(new_ledger_rows),
        "remaining_document_count": len(records),
        "applicable": False,
    }
    summary_path = Path(summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return records, new_ledger_rows, summary


def write_document_index(path: str | Path, records: list[DocumentRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(DocumentRecord.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(vars(record) for record in records)


def write_collection_failures(path: str | Path, failures: list[CollectionFailure]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(CollectionFailure.__annotations__), lineterminator="\n")
        writer.writeheader()
        writer.writerows(vars(item) for item in failures)


def _index_lookup_key(record: DocumentRecord) -> str:
    url = (record.source_url or "").strip()
    if url:
        return url
    return f"local://{record.company_code}/{record.report_year}/{record.document_type}"


def _read_document_index(path: str | Path) -> dict[str, DocumentRecord]:
    path = Path(path)
    if not path.exists():
        return {}
    result = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                source_url = (row.get("source_url") or "").strip()
                record = DocumentRecord(
                    company_code=row["company_code"], company_name=row["company_name"],
                    report_year=int(row["report_year"]), document_type=row["document_type"],
                    source_url=source_url,
                    retrieval_url=(row.get("retrieval_url") or source_url).strip(),
                    local_path=row["local_path"], sha256=row["sha256"], size=int(row["size"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if record.report_year < 1990 or record.report_year > 2100:
                continue
            result[_index_lookup_key(record)] = record
    return result
