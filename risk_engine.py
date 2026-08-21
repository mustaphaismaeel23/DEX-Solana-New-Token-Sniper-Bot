"""Pure, fail-closed risk scoring for candidate entries."""
from dataclasses import dataclass, field
import logging
import math
import time
from config import settings

log = logging.getLogger("risk_engine")

CATEGORY_WEIGHTS = {
    "liquidity": 20,
    "holder_concentration": 15,
    "liquidity_security": 15,
    "contract_security": 15,
    "volume_activity": 10,
    "token_pool_age": 5,
    "volatility": 5,
    "slippage_price_impact": 5,
    "market_conditions": 10,
}


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    score: float
    category: str
    positionSizeMultiplier: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hardReject: bool = False
    circuitBreakerState: str = "NORMAL"

    @property
    def position_size_multiplier(self):
        return self.positionSizeMultiplier


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _category(score):
    if score >= 80:
        return "LOW_RISK"
    if score >= 65:
        return "MODERATE_RISK"
    if score >= 50:
        return "HIGH_RISK"
    return "EXTREME_RISK"


def position_size_multiplier(score: float, maximum: float | None = None) -> float:
    maximum = settings.MAX_POSITION_SIZE_MULTIPLIER if maximum is None else maximum
    if score >= 80:
        multiplier = 1.0
    elif score >= 65:
        multiplier = 0.75
    elif score >= 50:
        multiplier = 0.4
    else:
        multiplier = 0.0
    return max(0.0, min(float(maximum), multiplier))


def score_risk(data: dict, minimum_score: float | None = None) -> RiskDecision:
    """Score normalized category values (0-100); unknown data rejects safely."""
    minimum_score = settings.MIN_RISK_SCORE if minimum_score is None else minimum_score
    reasons, warnings = [], []
    hard_reject = False

    if not isinstance(data, dict):
        return RiskDecision(False, 0, "EXTREME_RISK", 0, ["risk data is not an object"], [], True)

    values = data.get("categoryScores") or data.get("category_scores") or data
    missing = [name for name in CATEGORY_WEIGHTS if not _number(values.get(name))]
    if missing:
        reasons.append("missing or invalid risk data: " + ", ".join(missing))
        hard_reject = True

    score = sum(float(values[name]) * weight for name, weight in CATEGORY_WEIGHTS.items() if _number(values.get(name))) / 100
    score = max(0.0, min(100.0, score))

    sell_simulation = data.get("sell_simulation_passed")
    if sell_simulation is not True:
        reasons.append("sell simulation unavailable or failed")
        hard_reject = True

    for field_name, label in (("honeypot", "honeypot detected"),
                              ("dangerous_permissions", "dangerous contract permissions"), ("critical_security_failure", "critical security failure"),
                              ("stale_data", "stale data"), ("conflicting_price_data", "conflicting price data")):
        if data.get(field_name) is True:
            reasons.append(label)
            hard_reject = True

    for field_name, label, limit in (("tax_pct", "extreme token tax", settings.MAX_TAX_PCT),
                                     ("price_impact_pct", "excessive price impact", settings.MAX_PRICE_IMPACT_PCT)):
        value = data.get(field_name)
        if value is not None and (not _number(value) or value > limit or value < 0):
            reasons.append(f"{label}: {value}")
            hard_reject = True

    liquidity = data.get("liquidity_usd")
    if liquidity is not None and (not _number(liquidity) or liquidity < settings.MIN_RISK_LIQUIDITY_USD):
        reasons.append("insufficient liquidity")
        hard_reject = True

    age = data.get("data_timestamp")
    if age is not None and (not _number(age) or time.time() - age > settings.RISK_DATA_MAX_AGE_SECONDS):
        reasons.append("stale risk data")
        hard_reject = True

    if score < minimum_score:
        reasons.append(f"risk score {score:.1f} below minimum {minimum_score:.1f}")
    approved = not hard_reject and score >= minimum_score
    if approved and not reasons:
        reasons.append("all risk thresholds passed")
    multiplier = position_size_multiplier(score) if approved else 0.0
    decision = RiskDecision(approved, round(score, 2), _category(score), multiplier, reasons, warnings, hard_reject)
    log.info("Risk decision approved=%s score=%.2f category=%s hardReject=%s reasons=%s", approved, score, decision.category, hard_reject, reasons)
    return decision


def decision_from_safety_report(report: dict, minimum_score: float | None = None) -> RiskDecision:
    """Adapter boundary for live scanners/safety checks to supply normalized data."""
    return score_risk(report, minimum_score)
