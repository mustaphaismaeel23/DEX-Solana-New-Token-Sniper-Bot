import os
import asyncio
import time
from types import SimpleNamespace

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

import buyer
from circuit_breaker import CircuitBreaker


GOOD_DATA = {"dex": "pumpswap", "sell_simulation_passed": True, "categoryScores": {
    "liquidity": 90, "holder_concentration": 90, "liquidity_security": 90,
    "contract_security": 100, "volume_activity": 90, "token_pool_age": 90,
    "volatility": 80, "slippage_price_impact": 90, "market_conditions": 80,
}}


def test_entry_pipeline_sizes_only_after_all_gates(monkeypatch):
    calls = {}
    monkeypatch.setattr(buyer, "settings", SimpleNamespace(
        MIN_TOKEN_AGE_SECONDS=0, MAX_TOKEN_AGE_SECONDS=1000,
        MAX_CONCURRENT_POSITIONS=3, DRY_RUN=False, BUY_SIZE_SOL=0.05,
        MAX_POSITION_SIZE_MULTIPLIER=1.0, MIN_SOL_RESERVE=0.01,
        SLIPPAGE_BPS=500,
    ))
    monkeypatch.setattr(buyer, "already_seen", lambda mint: False)
    monkeypatch.setattr(buyer, "open_position_count", lambda: 0)
    monkeypatch.setattr(buyer, "record_skip", lambda *args: calls.setdefault("skip", args))
    monkeypatch.setattr(buyer, "run_all_checks", lambda *args: asyncio.sleep(0, result=(True, "ok")))
    monkeypatch.setattr(buyer, "build_risk_data", lambda *args, **kwargs: asyncio.sleep(0, result=GOOD_DATA))
    monkeypatch.setattr(buyer, "get_sol_balance", lambda *args: asyncio.sleep(0, result=1.0))
    monkeypatch.setattr(buyer, "open_position", lambda *args, **kwargs: None)
    monkeypatch.setattr(buyer, "notify", lambda *args: asyncio.sleep(0))

    async def fake_buy(*args):
        calls["amount"] = args[4]
        return "sig", 100, 0.001

    monkeypatch.setattr(buyer, "buy_token", fake_buy)
    candidate = {"mint": "mint", "source": "pumpfun", "created_at": time.time(), "risk_data": GOOD_DATA}
    asyncio.run(buyer.try_buy(object(), object(), SimpleNamespace(pubkey=lambda: "wallet"), candidate, CircuitBreaker()))
    assert calls["amount"] == 0.05
    assert "skip" not in calls
