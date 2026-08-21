"""
Exit logic for open positions.

Rules, checked in this order each tick:
1. Hard stop-loss: price <= entry * (1 - HARD_STOP_LOSS_PCT/100) -> SELL always,
   whether or not the trailing stop has activated yet.
2. Once price >= entry * (1 + PROFIT_TRIGGER_PCT/100), the trailing stop
   activates. From then on we track the peak price seen.
3. While active, if price <= peak * (1 - TRAIL_PCT/100) -> SELL (locks in
   profit as it pulls back from the high).
4. Safety timeout: if held longer than MAX_HOLD_SECONDS -> SELL regardless
   (protects against illiquid tokens that never move either way).
"""
import logging
import time
import httpx
from solana.rpc.async_api import AsyncClient
from config import settings
from jupiter_swap import get_token_price_in_sol, sell_token
from database import get_open_positions, update_position_peak, record_partial_exit, close_position
from notifier import notify
from circuit_breaker import CircuitBreaker, get_circuit_breaker

log = logging.getLogger("position_manager")


def evaluate_exit(entry_price, peak_price, current_price, trigger_active, opened_at, now):
    """Pure function, easy to unit test. Returns (should_sell, new_peak, new_trigger_active, reason)."""
    if entry_price <= 0 or current_price is None:
        return False, peak_price, trigger_active, ""

    change_pct = (current_price - entry_price) / entry_price * 100

    # 1. Hard stop-loss always wins
    if change_pct <= -settings.HARD_STOP_LOSS_PCT:
        return True, peak_price, trigger_active, f"hard stop-loss ({change_pct:.1f}%)"

    # 2. Activate trailing stop once profit target is hit
    new_trigger_active = trigger_active
    new_peak = max(peak_price, current_price)
    if not trigger_active and change_pct >= settings.PROFIT_TRIGGER_PCT:
        new_trigger_active = True

    # 3. If active, check trail
    if new_trigger_active:
        drawdown_pct = (new_peak - current_price) / new_peak * 100
        if drawdown_pct >= settings.TRAIL_PCT:
            return True, new_peak, new_trigger_active, f"trailing stop (-{drawdown_pct:.1f}% from peak)"

    # 4. Max hold timeout
    if now - opened_at >= settings.MAX_HOLD_SECONDS:
        return True, new_peak, new_trigger_active, "max hold time reached"

    return False, new_peak, new_trigger_active, ""


def evaluate_profit_take(entry_price, current_price, initial_token_amount, remaining_token_amount, profit_stage):
    """Return the next staged sell as (amount, next_stage, reason)."""
    if entry_price <= 0 or current_price is None or remaining_token_amount <= 0:
        return 0, profit_stage, ""

    multiple = current_price / entry_price
    initial_amount = initial_token_amount or remaining_token_amount
    if profit_stage < 1 and multiple >= 2:
        amount = min(remaining_token_amount, int(initial_amount * settings.PROFIT_TAKE_2X_PCT / 100))
        return amount, 1, "profit target 2x"
    if profit_stage < 2 and multiple >= 5:
        amount = min(remaining_token_amount, int(initial_amount * settings.PROFIT_TAKE_5X_PCT / 100))
        return amount, 2, "profit target 5x"
    if profit_stage < 3 and multiple >= 10:
        amount = min(remaining_token_amount, int(remaining_token_amount * settings.PROFIT_TAKE_10X_REMAINING_PCT / 100))
        return amount, 3, "profit target 10x"
    return 0, profit_stage, ""


async def check_positions(client: httpx.AsyncClient, rpc: AsyncClient, keypair,
                          breaker: CircuitBreaker | None = None):
    breaker = breaker or get_circuit_breaker()
    positions = get_open_positions()
    for pos in positions:
        current_price = await get_token_price_in_sol(client, pos["mint"])
        if current_price is None:
            log.warning(f"No route/price for {pos['mint']} — possibly rugged or delisted")
            continue

        should_sell, new_peak, new_trigger, reason = evaluate_exit(
            entry_price=pos["entry_price_sol"],
            peak_price=pos["peak_price_sol"],
            current_price=current_price,
            trigger_active=bool(pos["trigger_active"]),
            opened_at=pos["opened_at"],
            now=time.time(),
        )

        if not should_sell:
            if new_peak != pos["peak_price_sol"] or new_trigger != bool(pos["trigger_active"]):
                update_position_peak(pos["id"], new_peak, new_trigger)
            profit_amount, next_stage, profit_reason = evaluate_profit_take(
                pos["entry_price_sol"], current_price, pos["initial_token_amount"],
                int(pos["token_amount"]), pos["profit_stage"],
            )
            if profit_amount <= 0:
                continue
            remaining_amount = int(pos["token_amount"]) - profit_amount
            try:
                if settings.DRY_RUN:
                    record_partial_exit(pos["id"], remaining_amount, next_stage, f"DRY_RUN: {profit_reason}", None, None)
                    await notify(f"🧪 DRY RUN partial sell `{pos['mint'][:6]}...` — {profit_reason}")
                    continue

                sig, sol_received = await sell_token(
                    client, rpc, keypair, pos["mint"], profit_amount, settings.SLIPPAGE_BPS
                )
                record_partial_exit(pos["id"], remaining_amount, next_stage, profit_reason, sig, sol_received)
                invested = pos["entry_price_sol"] * profit_amount
                pnl = sol_received - invested
                breaker.record_loss(-pnl if pnl < 0 else 0) if pnl < 0 else breaker.record_win()
                await notify(
                    f"💰 Partial sell `{pos['mint'][:6]}...` — {profit_reason}\n"
                    f"Remaining tokens: {remaining_amount} | Received: {sol_received:.4f} SOL\nTx: `{sig}`"
                )
            except Exception as e:
                log.exception(f"Partial sell failed for {pos['mint']}")
                await notify(f"❌ PARTIAL SELL FAILED for `{pos['mint'][:6]}...`: {e} — retrying next tick")
            continue

        change_pct = (current_price - pos["entry_price_sol"]) / pos["entry_price_sol"] * 100
        try:
            if settings.DRY_RUN:
                log.info(f"[DRY RUN] Would sell {pos['mint']} ({reason}, {change_pct:+.1f}%)")
                close_position(pos["id"], f"DRY_RUN: {reason}", None)
                await notify(f"🧪 DRY RUN sell `{pos['mint'][:6]}...` — {reason} ({change_pct:+.1f}%)")
                continue

            sig, sol_received = await sell_token(
                client, rpc, keypair, pos["mint"], int(pos["token_amount"]), settings.SLIPPAGE_BPS
            )
            close_position(pos["id"], reason, sig)
            invested = pos["entry_price_sol"] * int(pos["token_amount"])
            pnl = sol_received - invested
            breaker.record_loss(-pnl if pnl < 0 else 0) if pnl < 0 else breaker.record_win()
            await notify(
                f"💰 Sold `{pos['mint'][:6]}...` — {reason}\n"
                f"P&L: {change_pct:+.1f}% | Received: {sol_received:.4f} SOL\nTx: `{sig}`"
            )
            log.info(f"Sold {pos['mint']}: {reason}, {change_pct:+.1f}%, sig={sig}")
        except Exception as e:
            breaker.record_provider_failure()
            log.exception(f"Sell failed for {pos['mint']}")
            await notify(f"❌ SELL FAILED for `{pos['mint'][:6]}...`: {e} — retrying next tick")
