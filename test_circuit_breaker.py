import os
from types import SimpleNamespace

os.environ.setdefault("RPC_URL", "http://localhost")
os.environ.setdefault("HELIUS_API_KEY", "test")
os.environ.setdefault("WALLET_PRIVATE_KEY", "test")

import circuit_breaker


def test_consecutive_losses_pause_and_cooldown_recovers(monkeypatch):
    monkeypatch.setattr(circuit_breaker, "settings", SimpleNamespace(
        MAX_CONSECUTIVE_LOSSES=2, DAILY_LOSS_THRESHOLD_SOL=10,
        CIRCUIT_BREAKER_MANUAL_RESET=False, CIRCUIT_BREAKER_COOLDOWN_SECONDS=10,
    ))
    breaker = circuit_breaker.CircuitBreaker()
    breaker.record_loss(1)
    breaker.record_loss(1)
    assert breaker.state == circuit_breaker.CircuitState.PAUSED
    assert breaker.can_enter() is False
    assert breaker.recovery_check(now=(breaker.paused_at or 0) + 9) is False
    assert breaker.recovery_check(now=(breaker.paused_at or 0) + 11) is True
    assert breaker.can_enter() is True


def test_emergency_stop_requires_manual_reset(monkeypatch):
    monkeypatch.setattr(circuit_breaker, "settings", SimpleNamespace(
        MAX_CONSECUTIVE_LOSSES=10, DAILY_LOSS_THRESHOLD_SOL=1,
        CIRCUIT_BREAKER_MANUAL_RESET=True, CIRCUIT_BREAKER_COOLDOWN_SECONDS=0,
    ))
    breaker = circuit_breaker.CircuitBreaker()
    breaker.record_loss(1)
    assert breaker.state == circuit_breaker.CircuitState.EMERGENCY_STOP
    assert breaker.recovery_check(provider_ok=True, prices_ok=True, liquidity_ok=True) is False
    assert breaker.manual_reset(provider_ok=True, prices_ok=True, liquidity_ok=True) is True
    assert breaker.state == circuit_breaker.CircuitState.NORMAL
