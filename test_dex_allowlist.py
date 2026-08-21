import os
from types import SimpleNamespace

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

import dex_allowlist


def test_unknown_and_unsupported_sources_are_rejected(monkeypatch):
    monkeypatch.setattr(dex_allowlist, "settings", SimpleNamespace(ALLOWED_DEXES=("pumpfun", "pumpswap")))
    assert dex_allowlist.validate_discovery({})[0] is False
    assert dex_allowlist.validate_discovery({"source": "raydium"})[0] is False
    assert dex_allowlist.validate_discovery({"source": "pumpfun"})[0] is True


def test_pool_must_be_pumpswap(monkeypatch):
    monkeypatch.setattr(dex_allowlist, "settings", SimpleNamespace(ALLOWED_DEXES=("pumpfun", "pumpswap")))
    assert dex_allowlist.validate_pool({"source": "pumpfun"}, {"dexId": "pumpswap"})[0] is True
    assert dex_allowlist.validate_pool({"source": "pumpfun"}, {"dexId": "raydium"})[0] is False


def test_quote_cannot_contain_unknown_route(monkeypatch):
    monkeypatch.setattr(dex_allowlist, "settings", SimpleNamespace(ALLOWED_DEXES=("pumpfun", "pumpswap")))
    quote = {"routePlan": [{"swapInfo": {"label": "PumpSwap"}}]}
    assert dex_allowlist.validate_quote_routes(quote)[0] is True
    quote["routePlan"].append({"swapInfo": {"label": "Raydium"}})
    assert dex_allowlist.validate_quote_routes(quote)[0] is False
