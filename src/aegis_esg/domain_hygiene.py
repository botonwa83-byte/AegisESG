"""Shared issuer-domain hygiene for discovery, review, and same-domain report finding."""
from __future__ import annotations

import re
from urllib.parse import urlparse

# Platforms that appear in reports but are not issuer official websites.
NON_ISSUER_HOST_SUFFIXES = (
    "sse.com.cn", "szse.cn", "hkex.com.hk", "hkexnews.hk", "bse.cn",
    "cninfo.com.cn", "cninfo.com", "cninfo.cn", "cninfo.co",
    "sseinfo.com", "p5w.net", "todayir.com", "eastmoney.com",
    "sina.com.cn", "sina.cn", "sohu.com", "qq.com", "weixin.qq.com",
    "jrj.com.cn", "hexun.com", "10jqka.com.cn", "cls.cn",
    "chinaclear.cn", "csrc.gov.cn", "gov.cn", "edu.cn",
    "lnsthj.cn", "gdeei.cn", "xjpmic.cn", "cnstock.com", "mbalib.com",
    "people.com.cn", "xinhuanet.com", "cctv.com",
    "book118.com", "ir-online.com.cn", "iwencai.com", "baidu.com",
)

# Path-style disclosure portals often reuse shared regional hosts.
NON_ISSUER_HOST_MARKERS = (
    "qyxxpl", "gdeepub", "xxpl.", "hkexnews", "cninfo", "sseinfo",
)

VALID_PUBLIC_SUFFIXES = (
    ".com.cn", ".com.hk", ".net.cn", ".org.cn", ".gov.cn",
    ".com", ".net", ".org", ".cc", ".co", ".hk", ".cn", ".info", ".biz",
)

URL_RE = re.compile(
    r"https?://(?:www\.)?([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+)"
    r"(?:/[A-Za-z0-9_./?%=&+#:@~,-]*)?",
    re.I,
)


def normalize_host(host: str) -> str:
    return (host or "").strip().lower().removeprefix("www.").rstrip(".")


def is_non_issuer_host(host: str) -> bool:
    host = normalize_host(host)
    if not host:
        return True
    if any(host == item or host.endswith("." + item) for item in NON_ISSUER_HOST_SUFFIXES):
        return True
    return any(marker in host for marker in NON_ISSUER_HOST_MARKERS)


def has_valid_public_suffix(host: str) -> bool:
    host = normalize_host(host)
    return any(host.endswith(suffix) for suffix in VALID_PUBLIC_SUFFIXES)


def is_plausible_issuer_domain(host: str) -> bool:
    """Reject truncated OCR/PDF fragments and non-issuer platforms."""
    host = normalize_host(host)
    if not host or "." not in host or is_non_issuer_host(host):
        return False
    if not has_valid_public_suffix(host):
        return False
    labels = host.split(".")
    if any(not label or len(label) > 63 for label in labels):
        return False
    # Single-char final label before a real TLD is almost always OCR truncation (ir.p).
    if len(labels) >= 2 and len(labels[-2]) == 1 and labels[-1] in {"com", "net", "org", "cn", "hk"}:
        return False
    # Extremely short registrable names like s.com are almost always fragments.
    registrable = labels[-2] if labels[-1] in {"com", "net", "org", "cn", "hk", "info", "biz", "cc", "co"} else labels[0]
    if labels[-2:] == ["com", "cn"] or labels[-2:] == ["com", "hk"] or labels[-2:] == ["net", "cn"]:
        registrable = labels[-3] if len(labels) >= 3 else ""
    if len(registrable) < 3:
        return False
    return True


def same_registered_domain(url_host: str, official_domain: str) -> bool:
    url_host = normalize_host(url_host)
    official_domain = normalize_host(official_domain)
    if not url_host or not official_domain:
        return False
    return url_host == official_domain or url_host.endswith("." + official_domain)


def extract_urls(text: str) -> list[str]:
    return [match.group(0).rstrip(".,);]") for match in URL_RE.finditer(text or "")]


def host_from_url(url: str) -> str:
    return normalize_host(urlparse(url).hostname or "")
