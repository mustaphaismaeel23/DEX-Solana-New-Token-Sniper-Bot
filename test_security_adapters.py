import os
from types import SimpleNamespace
import asyncio

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

import security_adapters


def test_sell_simulator_rejects_missing_inventory():
    result = asyncio.run(security_adapters.JupiterRpcSellSimulator().simulate(object(), object(), "mint", 0, "owner"))
    assert result[0] is False


def test_liquidity_provider_fails_closed_without_program_id(monkeypatch):
    monkeypatch.setattr(security_adapters, "settings", SimpleNamespace(PUMPSWAP_PROGRAM_ID=""))
    result = asyncio.run(security_adapters.PumpSwapLiquiditySecurityProvider().verify(object(), "pool"))
    assert result.verified is False
    assert result.score is None
