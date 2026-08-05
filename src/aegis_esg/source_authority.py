"""Disclosure source authority for research merges and conflict resolution.

User policy (informal research):
  exchange official disclosure > issuer official website > other channels.
On value conflicts, keep the higher-authority source. Never forges downloads.
"""
from __future__ import annotations

from enum import IntEnum

from .models import Observation

EXCHANGE_HOSTS = (
    "sse.com.cn",
    "szse.cn",
    "cninfo.com.cn",
    "hkexnews.hk",
    "hkex.com.hk",
    "bse.cn",
    "static.sse.com.cn",
    "disc.static.szse.cn",
    "www.bse.cn",
)

# Paths under data/raw that are exchange / CI harvest of exchange filings.
EXCHANGE_PATH_MARKERS = (
    "ci_collection/",
    "/sse/",
    "/szse/",
    "/bse/",
    "/hkex",
    "hkex_reports/",
    "data/raw/",  # local exchange harvest roots; refined by URL when present
)


class SourceTier(IntEnum):
    """Lower is more authoritative."""

    EXCHANGE = 0
    ISSUER_WEBSITE = 1
    OTHER = 2


def _blob(item: Observation) -> tuple[str, str, str]:
    url = (item.source_url or "").lower()
    source_file = (item.source_file or "").replace("\\", "/").lower()
    evidence = (item.evidence_text or "").lower()
    return url, source_file, evidence


def is_exchange_source(item: Observation) -> bool:
    url, source_file, _ = _blob(item)
    if any(host in url for host in EXCHANGE_HOSTS):
        return True
    if "ci_collection/" in source_file:
        return True
    if any(marker in source_file for marker in ("hkex_reports/", "/sse/", "/szse/", "/bse/")):
        return True
    # Bare local harvest without URL is treated as exchange-grade when under data/raw/<code>/
    if source_file.startswith("data/raw/") and "/20" in source_file and "issuer" not in source_file:
        if "official_website" not in source_file and "issuer_site" not in source_file:
            return True
    return False


def is_issuer_website_source(item: Observation) -> bool:
    url, source_file, evidence = _blob(item)
    if is_exchange_source(item):
        return False
    markers = (
        "issuer_official_website",
        "issuer_site",
        "official_website",
        "company website",
        "官网",
        "投资者关系",
    )
    if any(marker in source_file for marker in markers):
        return True
    if any(marker in evidence for marker in markers):
        return True
    # Non-exchange https URL that is not a known aggregator.
    if url.startswith("https://") and not any(host in url for host in EXCHANGE_HOSTS):
        aggregators = ("eastmoney.com", "sina.com", "qq.com", "baidu.com", "choice", "wind")
        if not any(host in url for host in aggregators):
            return True
    return False


def source_tier(item: Observation) -> SourceTier:
    if is_exchange_source(item):
        return SourceTier.EXCHANGE
    if is_issuer_website_source(item):
        return SourceTier.ISSUER_WEBSITE
    return SourceTier.OTHER


def disclosure_authority(item: Observation) -> tuple:
    """Lower tuple wins when selecting among conflicting observations."""
    evidence = item.evidence_text or ""
    evidence_l = evidence.lower()
    url = (item.source_url or "").lower()
    source_file = (item.source_file or "").replace("\\", "/").lower()
    tier = int(source_tier(item))
    english = (
        "english" in evidence_l
        or "英文" in evidence
        or "/en/" in url
        or "english" in source_file
    )
    derived = "派生" in evidence or "derived" in evidence_l
    ci_harvest = "ci_collection" in source_file
    return (
        tier,
        1 if english else 0,
        1 if derived else 0,
        0 if ci_harvest else 1,
        -float(item.confidence or 0),
    )


def prefer(left: Observation, right: Observation) -> Observation:
    """Return the higher-authority observation (ties keep left)."""
    return left if disclosure_authority(left) <= disclosure_authority(right) else right


AUTHORITY_POLICY_VERSION = "source-authority-v1-exchange-gt-issuer-gt-other"
