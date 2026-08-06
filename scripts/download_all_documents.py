#!/usr/bin/env python3
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

INDEX_FILES = [
    "data/raw/all_markets_document_index.csv",
    "data/raw/bse_document_index.csv",
    "data/raw/document_index.csv",
    "data/raw/hkex_annual_gap_2025_document_index.csv",
    "data/raw/hkex_annual_gap_document_index.csv",
    "data/raw/hkex_continuity_all_document_index.csv",
    "data/raw/hkex_continuity_complete_document_index.csv",
    "data/raw/hkex_continuity_document_index.csv",
    "data/raw/hkex_continuity_missing_document_index.csv",
    "data/raw/hkex_reports_all_document_index.csv",
    "data/raw/hkex_reports_complete_document_index.csv",
    "data/raw/rediscovery_document_index.csv",
    "data/raw/sse_all_document_index.csv",
    "data/raw/szse_document_index.csv",
]

UA = "AegisESG/0.2 public-disclosure-collector"
HAVE_CURL = shutil.which("curl") is not None


def _referer_for(url: str) -> str:
    if "hkexnews.hk" in url:
        return "https://www1.hkexnews.hk/"
    if "sse.com.cn" in url:
        return "https://www.sse.com.cn/"
    if "szse.cn" in url:
        return "https://www.szse.cn/disclosure/"
    if "cninfo.com.cn" in url:
        return "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
    if "bseinfo.net" in url or "bse.cn" in url:
        return "https://www.bseinfo.net/disclosure/announcement.html"
    if "static.sse.com.cn" in url:
        return "https://www.sse.com.cn/"
    return "https://www.google.com/"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_curl(url, dest, max_time=300, retries=3):
    referer = _referer_for(url)
    partial = Path(dest + ".part")
    for attempt in range(retries):
        if partial.exists() and partial.read_bytes()[:5] != b"%PDF-":
            try:
                partial.unlink()
            except OSError:
                pass
        result = subprocess.run([
            "curl", "-fsSL", "-C", "-",
            "--max-time", str(max_time),
            "--connect-timeout", "20",
            "--retry", "2",
            "-A", UA,
            "-e", referer,
            "-o", str(partial), url,
        ], capture_output=True, timeout=max_time + 60)
        if result.returncode == 0 and partial.exists() and partial.stat().st_size > 0:
            os.replace(partial, dest)
            return True, Path(dest).stat().st_size
        err = result.stderr.decode("utf-8", "ignore").strip().splitlines()
        last_err = err[-1] if err else f"curl exit {result.returncode}"
        if attempt == retries - 1:
            try:
                if partial.exists():
                    partial.unlink()
            except OSError:
                pass
            return False, last_err
        time.sleep(3 * (attempt + 1))
    return False, "curl exhausted"


def download(url, dest, timeout=90, retries=1):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if HAVE_CURL:
        return download_curl(url, dest, max_time=timeout * 3, retries=retries)
    referer = _referer_for(url)
    tmp = dest + ".part"
    last_err = "unknown"
    for attempt in range(retries):
        try:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            headers = {"User-Agent": UA, "Referer": referer}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                got = 0
                with open(tmp, "wb") as out:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                if got == 0:
                    last_err = "0-byte response"
                    if attempt == retries - 1:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                        return False, last_err
                    time.sleep(2 * (attempt + 1))
                    continue
                if os.path.exists(tmp):
                    os.replace(tmp, dest)
                    return True, got
                else:
                    last_err = f"missing tmp after write ({got} bytes)"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        if attempt == retries - 1:
            return False, last_err
        time.sleep(2 * (attempt + 1))
    return False, last_err

def load_entries():
    seen = {}
    for idx in INDEX_FILES:
        if not os.path.exists(idx):
            continue
        with open(idx, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lp = row.get("local_path", "").strip()
                url = (row.get("retrieval_url") or row.get("source_url") or "").strip()
                sha = row.get("sha256", "").strip()
                if not lp or not url:
                    continue
                if lp not in seen:
                    seen[lp] = {"url": url, "sha": sha, "src": idx}
    return seen

def main():
    entries = load_entries()
    print(f"[INFO] total unique document entries: {len(entries)}")
    ok = skip = fail = mismatch = 0
    failures = []
    os.makedirs("var", exist_ok=True)
    for i, (lp, meta) in enumerate(sorted(entries.items()), 1):
        dest = os.path.join(os.getcwd(), lp) if not os.path.isabs(lp) else lp
        sha = meta["sha"]
        try:
            if os.path.exists(dest):
                if sha:
                    actual = sha256_file(dest)
                    if actual == sha:
                        skip += 1
                        print(f"[{i}/{len(entries)}] OK (exists+hash): {lp}")
                        continue
                    else:
                        print(f"[{i}/{len(entries)}] existing hash mismatch, keep file: {lp}")
                        mismatch += 1
                        failures.append((lp, meta["url"], f"existing sha256 mismatch want={sha} got={actual}"))
                        continue
                else:
                    skip += 1
                    print(f"[{i}/{len(entries)}] OK (exists, no hash): {lp}")
                    continue
            print(f"[{i}/{len(entries)}] GET {meta['url'][:90]} -> {lp}")
            success, info = download(meta["url"], dest)
            if not success:
                fail += 1
                failures.append((lp, meta["url"], info))
                print(f"  !! FAIL: {info}")
                continue
            if sha:
                actual = sha256_file(dest)
                if actual != sha:
                    fail += 1
                    mismatch += 1
                    bad = dest + ".mismatch_sha256"
                    try:
                        os.replace(dest, bad)
                    except OSError:
                        pass
                    failures.append((lp, meta["url"], f"sha256 mismatch want={sha} got={actual} (saved as .mismatch_sha256)"))
                    print(f"  !! sha256 mismatch, saved to .mismatch_sha256 ({info} bytes)")
                    continue
            ok += 1
            print(f"  OK {info} bytes")
        except Exception as e:
            fail += 1
            failures.append((lp, meta["url"], f"UNEXPECTED {type(e).__name__}: {e}"))
            print(f"  !! UNEXPECTED {type(e).__name__}: {e}")
        sys.stdout.flush()
    print(f"\n=== SUMMARY: ok={ok} skipped={skip} mismatch(kept)={mismatch} failed={fail}")
    if failures:
        with open("var/download_failures.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["local_path", "url", "error"])
            for r in failures:
                w.writerow(r)
        print(f"Failures written to var/download_failures.csv")
    sys.exit(0 if not fail else 1)

if __name__ == "__main__":
    main()
