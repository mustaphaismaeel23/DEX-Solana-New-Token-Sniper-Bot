import os
import asyncio
from types import SimpleNamespace

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

import safety_checks


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class DummyClient:
    def __init__(self, payload):
        self.payload = payload

    async def get(self, url, timeout=None):
        return DummyResponse(self.payload)


def test_utility_signals_accept_strong_public_evidence(monkeypatch):
    monkeypatch.setattr(safety_checks, "settings", SimpleNamespace(
        REQUIRE_UTILITY_SIGNALS=True,
        MIN_UTILITY_SCORE=70,
        MIN_24H_VOLUME_USD=25_000,
        MIN_VOLUME_LIQUIDITY_RATIO=0.25,
        MAX_VOLUME_LIQUIDITY_RATIO=3.0,
        MIN_24H_TRANSACTIONS=100,
        MAX_24H_PRICE_CHANGE_PCT=400,
        MIN_LIQUIDITY_USD=50_000,
    ))
    client = DummyClient({
        "pairs": [{
            "liquidity": {"usd": 100_000},
            "volume": {"h24": 50_000},
            "txns": {"h24": {"buys": 60, "sells": 60}},
            "info": {"websites": [{"url": "https://example.com"}], "socials": [{"type": "twitter"}]},
        }],
    })

    ok, reason = asyncio.run(safety_checks.check_utility_signals(client, "mint"))

    assert ok is True
    assert "100/100" in reason


def test_utility_signals_reject_weak_public_evidence(monkeypatch):
    monkeypatch.setattr(safety_checks, "settings", SimpleNamespace(
        REQUIRE_UTILITY_SIGNALS=True,
        MIN_UTILITY_SCORE=70,
        MIN_24H_VOLUME_USD=25_000,
        MIN_VOLUME_LIQUIDITY_RATIO=0.25,
        MAX_VOLUME_LIQUIDITY_RATIO=3.0,
        MIN_24H_TRANSACTIONS=100,
        MAX_24H_PRICE_CHANGE_PCT=400,
        MIN_LIQUIDITY_USD=50_000,
    ))
    client = DummyClient({
        "pairs": [{
            "liquidity": {"usd": 100_000},
            "volume": {"h24": 1_000},
            "info": {},
        }],
    })

    ok, reason = asyncio.run(safety_checks.check_utility_signals(client, "mint"))

    assert ok is False
    assert "below min" in reason
