import importlib.util
from pathlib import Path


path = Path(__file__).parents[1] / "scripts/prepare_official_download_manifest.py"
spec = importlib.util.spec_from_file_location("official_manifest", path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_verified_same_domain_is_eligible():
    assert module.is_valid({"official_domain": "example.com", "candidate_url": "https://www.example.com/esg.pdf", "domain_verification": "verified"})


def test_exchange_domain_is_rejected():
    assert not module.is_valid({"official_domain": "example.com", "candidate_url": "https://www.sse.com.cn/esg.pdf", "domain_verification": "verified"})


def test_unverified_domain_is_rejected():
    assert not module.is_valid({"official_domain": "example.com", "candidate_url": "https://example.com/esg.pdf", "domain_verification": "not_submitted"})
