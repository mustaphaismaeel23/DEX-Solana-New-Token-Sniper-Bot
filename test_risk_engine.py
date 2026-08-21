import os
from types import SimpleNamespace

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

import risk_engine


ALL_GOOD = {
    "liquidity": 90, "holder_concentration": 90, "liquidity_security": 80,
    "contract_security": 100, "volume_activity": 80, "token_pool_age": 80,
    "volatility": 75, "slippage_price_impact": 85, "market_conditions": 70,
}


def test_score_category_and_position_size():
    decision = risk_engine.score_risk({"categoryScores": ALL_GOOD, "sell_simulation_passed": True}, minimum_score=65)
    assert decision.approved is True
    assert decision.category == "LOW_RISK"
    assert 0 < decision.positionSizeMultiplier <= 1


def test_missing_data_fails_closed():
    decision = risk_engine.score_risk({"categoryScores": {"liquidity": 100}})
    assert decision.approved is False
    assert decision.hardReject is True
    assert "missing or invalid risk data" in decision.reasons[0]


def test_honeypot_and_price_impact_are_hard_rejects():
    decision = risk_engine.score_risk({"categoryScores": ALL_GOOD, "sell_simulation_passed": True, "honeypot": True, "price_impact_pct": 10})
    assert decision.approved is False
    assert decision.hardReject is True
    assert any("honeypot" in reason for reason in decision.reasons)


def test_multiplier_never_exceeds_configured_max(monkeypatch):
    monkeypatch.setattr(risk_engine, "settings", SimpleNamespace(MAX_POSITION_SIZE_MULTIPLIER=0.5))
    assert risk_engine.position_size_multiplier(95) == 0.5


def test_nested_security_evidence_is_supported():
    report = {"categoryScores": {"liquidity_security": 90}, "sell_simulation_passed": True}
    assert report["categoryScores"]["liquidity_security"] == 90
    assert report["sell_simulation_passed"] is True
