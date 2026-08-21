"""Independent fail-closed circuit breaker for entry and trade safety."""
from dataclasses import dataclass
from enum import Enum
import logging
import time
from config import settings

log = logging.getLogger("circuit_breaker")


class CircuitState(str, Enum):
    NORMAL = "NORMAL"
    PAUSED = "PAUSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


@dataclass
class CircuitBreaker:
    persist: bool = False
    state: CircuitState = CircuitState.NORMAL
    consecutive_losses: int = 0
    daily_loss_sol: float = 0.0
    drawdown_pct: float = 0.0
    paused_at: float | None = None
    last_reason: str = ""

    def __post_init__(self):
        if not self.persist:
            return
        try:
            from database import init_db, load_circuit_breaker_state
            init_db()
            state = load_circuit_breaker_state()
            if state:
                if state["loss_day"] != time.strftime("%Y-%m-%d"):
                    self.daily_loss_sol = 0.0
                    self._persist()
                    return
                self.state = CircuitState(state["state"])
                self.consecutive_losses = int(state["consecutive_losses"])
                self.daily_loss_sol = float(state["daily_loss_sol"])
                self.drawdown_pct = float(state["drawdown_pct"])
                self.paused_at = state["paused_at"]
                self.last_reason = state["last_reason"]
        except Exception:
            self.state = CircuitState.EMERGENCY_STOP
            self.last_reason = "circuit breaker state unavailable"

    def _persist(self):
        if not self.persist:
            return
        from database import save_circuit_breaker_state
        save_circuit_breaker_state({
            "state": self.state.value,
            "consecutive_losses": self.consecutive_losses,
            "daily_loss_sol": self.daily_loss_sol,
            "drawdown_pct": self.drawdown_pct,
            "paused_at": self.paused_at,
            "last_reason": self.last_reason,
            "loss_day": time.strftime("%Y-%m-%d"),
        })

    def refresh(self):
        if not self.persist:
            return
        try:
            from database import load_circuit_breaker_state
            state = load_circuit_breaker_state()
            if state:
                self.state = CircuitState(state["state"])
                self.consecutive_losses = int(state["consecutive_losses"])
                self.daily_loss_sol = float(state["daily_loss_sol"])
                self.drawdown_pct = float(state["drawdown_pct"])
                self.paused_at = state["paused_at"]
                self.last_reason = state["last_reason"]
        except Exception:
            self.state = CircuitState.EMERGENCY_STOP
            self.last_reason = "circuit breaker state unavailable"

    def _trip(self, state: CircuitState, reason: str):
        if state == CircuitState.EMERGENCY_STOP or self.state != CircuitState.EMERGENCY_STOP:
            self.state = state
        self.last_reason = reason
        self.paused_at = time.time()
        self._persist()
        log.error("Circuit breaker state=%s reason=%s", self.state.value, reason)

    def record_loss(self, loss_sol: float):
        self.daily_loss_sol += max(0.0, loss_sol)
        self.consecutive_losses += 1
        if self.daily_loss_sol >= settings.DAILY_LOSS_THRESHOLD_SOL:
            self._trip(CircuitState.EMERGENCY_STOP, "daily loss threshold")
        elif self.consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            self._trip(CircuitState.PAUSED, "consecutive loss threshold")
        else:
            self._persist()

    def record_win(self):
        self.consecutive_losses = 0
        self._persist()

    def record_event(self, event: str, emergency: bool = False):
        state = CircuitState.EMERGENCY_STOP if emergency else CircuitState.PAUSED
        self._trip(state, event)

    def record_liquidity_collapse(self):
        self.record_event("liquidity collapse")

    def record_excessive_slippage(self):
        self.record_event("excessive slippage")

    def record_provider_failure(self):
        self.record_event("RPC/provider failure", emergency=True)

    def record_price_conflict(self):
        self.record_event("stale or conflicting price data", emergency=True)

    def record_security_failure(self):
        self.record_event("critical security/data failure", emergency=True)

    def can_enter(self) -> bool:
        self.refresh()
        return self.state == CircuitState.NORMAL

    def recovery_check(self, *, provider_ok=True, prices_ok=True, liquidity_ok=True, now=None) -> bool:
        if self.state == CircuitState.NORMAL:
            return True
        if self.state == CircuitState.EMERGENCY_STOP and settings.CIRCUIT_BREAKER_MANUAL_RESET:
            return False
        now = time.time() if now is None else now
        if self.paused_at is None or now - self.paused_at < settings.CIRCUIT_BREAKER_COOLDOWN_SECONDS:
            return False
        if not (provider_ok and prices_ok and liquidity_ok):
            return False
        self.state = CircuitState.NORMAL
        self.paused_at = None
        self.last_reason = "recovery checks passed"
        self._persist()
        log.warning("Circuit breaker recovered to NORMAL")
        return True

    def manual_reset(self, *, provider_ok=True, prices_ok=True, liquidity_ok=True) -> bool:
        if not (provider_ok and prices_ok and liquidity_ok):
            return False
        self.state = CircuitState.NORMAL
        self.paused_at = None
        self.last_reason = "manual reset"
        self.consecutive_losses = 0
        self._persist()
        return True


_default_breaker = CircuitBreaker(persist=True)


def get_circuit_breaker() -> CircuitBreaker:
    return _default_breaker
