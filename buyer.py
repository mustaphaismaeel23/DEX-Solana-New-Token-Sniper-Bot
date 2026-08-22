import logging
import time
import httpx
from solana.rpc.async_api import AsyncClient
from config import settings
from safety_checks import build_risk_data, run_all_checks
from dataclasses import replace
from risk_engine import decision_from_safety_report
from circuit_breaker import CircuitBreaker, get_circuit_breaker
from dex_allowlist import validate_discovery, validate_pool
from security_adapters import PumpSwapLiquiditySecurityProvider, JupiterRpcSellSimulator
from jupiter_swap import get_sol_balance, buy_token
from database import already_seen, record_skip, open_position, open_position_count
from notifier import notify

log = logging.getLogger("buyer")


def _event_age_seconds(created_at) -> float:
    if not isinstance(created_at, (int, float)):
        return float("inf")
    timestamp = float(created_at)
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return time.time() - timestamp


def _risk_data(candidate: dict) -> dict:
    """Adapter boundary for scanner/security providers; unknown fields stay unknown."""
    data = candidate.get("risk_data") or {}
    return data if isinstance(data, dict) else {}


async def try_buy(client: httpx.AsyncClient, rpc: AsyncClient, keypair, candidate: dict,
                  breaker: CircuitBreaker | None = None):
    breaker = breaker or get_circuit_breaker()
    mint = candidate["mint"]
    source = candidate["source"]
    is_established = candidate.get("is_established", False)

    allowed, allowlist_reason = validate_discovery(candidate)
    if not allowed:
        record_skip(mint, source, allowlist_reason)
        log.warning("Skipped %s before safety checks: %s", mint, allowlist_reason)
        return

    if already_seen(mint):
        return

    age = _event_age_seconds(candidate.get("created_at"))
    
    # Use different age requirements based on token type
    if is_established:
        min_age = settings.MIN_ESTABLISHED_TOKEN_AGE_SECONDS
        max_age = settings.MAX_ESTABLISHED_TOKEN_AGE_SECONDS
    else:
        min_age = settings.MIN_TOKEN_AGE_SECONDS
        max_age = settings.MAX_TOKEN_AGE_SECONDS
    
    if age < min_age:
        if is_established:
            record_skip(mint, source, f"not established yet ({age/86400:.1f} days; min {min_age/86400:.0f} days)")
        else:
            record_skip(mint, source, f"too new ({age:.0f}s; min {min_age}s)")
        return
    
    if max_age > 0 and age > max_age:
        if is_established:
            record_skip(mint, source, f"too old ({age/86400:.1f} days; max {max_age/86400:.0f} days)")
        else:
            record_skip(mint, source, f"too old ({age:.0f}s)")
        return

    if open_position_count() >= settings.MAX_CONCURRENT_POSITIONS:
        record_skip(mint, source, "max concurrent positions reached")
        return

    if not settings.DRY_RUN:
        our_balance = await get_sol_balance(rpc, keypair.pubkey())
        if our_balance < settings.BUY_SIZE_SOL + settings.MIN_SOL_RESERVE:
            record_skip(mint, source, f"insufficient balance ({our_balance:.4f} SOL)")
            await notify(f"⚠️ Skipping buys — balance too low ({our_balance:.4f} SOL)")
            return

    try:
        ok, reason = await run_all_checks(client, rpc, mint, is_established)
    except Exception as e:
        breaker.record_event("safety checks failed", emergency=True)
        record_skip(mint, source, f"safety checks failed closed: {e}")
        log.exception("Safety checks failed for %s", mint)
        return
    if not ok:
        record_skip(mint, source, reason)
        log.info(f"Skipped {mint} ({source}): {reason}")
        return

    try:
        risk_data = await build_risk_data(
            client, rpc, mint, candidate,
            liquidity_provider=PumpSwapLiquiditySecurityProvider(),
            sell_simulator=JupiterRpcSellSimulator(),
            owner_pubkey=keypair.pubkey(),
        )
        pool_ok, pool_reason = validate_pool(candidate, risk_data)
        if not pool_ok:
            record_skip(mint, source, pool_reason)
            log.warning("Skipped %s: %s", mint, pool_reason)
            return
        decision = decision_from_safety_report(risk_data)
    except Exception as e:
        breaker.record_event("risk engine failure", emergency=True)
        record_skip(mint, source, f"risk engine failed closed: {e}")
        log.exception("Risk engine failed for %s", mint)
        return
    if not decision.approved:
        record_skip(mint, source, "; ".join(decision.reasons))
        log.info("Skipped %s (%s): risk decision=%s", mint, source, decision)
        return

    if not breaker.can_enter():
        decision = replace(decision, approved=False, circuitBreakerState=breaker.state.value,
                           reasons=[*decision.reasons, f"circuit breaker {breaker.state.value}: {breaker.last_reason}"])
        record_skip(mint, source, "; ".join(decision.reasons))
        log.warning("Skipped %s: circuit breaker %s", mint, breaker.state.value)
        return

    amount = min(settings.BUY_SIZE_SOL * decision.positionSizeMultiplier,
                 settings.BUY_SIZE_SOL * settings.MAX_POSITION_SIZE_MULTIPLIER)
    if amount <= 0:
        record_skip(mint, source, "risk position size is zero")
        return

    try:
        if settings.DRY_RUN:
            log.info(f"[DRY RUN] Would buy {mint} ({source}) for {settings.BUY_SIZE_SOL} SOL — {reason}")
            open_position(mint, source, entry_price_sol=0.000001, token_amount=1_000_000, buy_signature=None)
            await notify(f"🧪 DRY RUN buy `{mint[:6]}...` ({source}) — checks passed: {reason}")
            return

        sig, tokens_received, entry_price = await buy_token(
            client, rpc, keypair, mint, amount, settings.SLIPPAGE_BPS
        )
        open_position(mint, source, entry_price, tokens_received, sig)
        await notify(
            f"🎯 Bought `{mint[:6]}...` ({source})\n"
            f"Spent: {settings.BUY_SIZE_SOL} SOL | Received: {tokens_received}\nTx: `{sig}`"
        )
        log.info(f"Bought {mint}: sig={sig}")
    except Exception as e:
        log.exception(f"Buy failed for {mint}")
        record_skip(mint, source, f"buy execution failed: {e}")
        await notify(f"❌ Buy FAILED for `{mint[:6]}...`: {e}")
