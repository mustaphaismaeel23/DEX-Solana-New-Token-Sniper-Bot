"""
Safety screens run on every candidate token before buying.
These catch the most common obvious rug patterns but are NOT a guarantee —
see README limitations.
"""
import logging
import time
import httpx
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from config import settings
from jupiter_swap import get_quote

log = logging.getLogger("safety_checks")

DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"


def _bounded_score(value: float) -> float:
    return max(0.0, min(100.0, value))


async def build_risk_data(client: httpx.AsyncClient, rpc: AsyncClient, mint: str,
                          candidate: dict | None = None) -> dict:
    """Normalize live provider data for the risk engine.

    Provider-specific fields are kept at this boundary. Missing proof is left
    absent so the risk engine can reject it instead of treating it as safe.
    """
    candidate = candidate or {}
    data = dict(candidate.get("risk_data") or {})
    provided_scores = dict(data.get("categoryScores") or data.get("category_scores") or {})
    sell_simulation_passed = data.get("sell_simulation_passed", candidate.get("sell_simulation_passed"))
    response = await client.get(DEXSCREENER_TOKEN_URL.format(mint=mint), timeout=10)
    response.raise_for_status()
    pairs = response.json().get("pairs") or []
    if not pairs:
        raise ValueError("no pair data")
    pair = max(pairs, key=lambda item: float((item.get("liquidity") or {}).get("usd") or 0))

    liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
    volume = float((pair.get("volume") or {}).get("h24") or 0)
    price_change = abs(float((pair.get("priceChange") or {}).get("h24") or 0))
    txns = (pair.get("txns") or {}).get("h24") or {}
    transaction_count = int(txns.get("buys") or 0) + int(txns.get("sells") or 0)
    volume_ratio = volume / liquidity if liquidity else 0

    holder_resp = await rpc.get_token_largest_accounts(Pubkey.from_string(mint))
    supply_resp = await rpc.get_token_supply(Pubkey.from_string(mint))
    total_supply = int(supply_resp.value.amount)
    if not holder_resp.value or total_supply <= 0:
        raise ValueError("holder or supply data unavailable")
    top_pct = int(holder_resp.value[0].amount) / total_supply * 100

    authority_resp = await rpc.get_account_info_json_parsed(Pubkey.from_string(mint))
    if not authority_resp.value:
        raise ValueError("mint account unavailable")
    authority_info = authority_resp.value.data.parsed["info"]
    authorities_safe = authority_info.get("mintAuthority") is None and authority_info.get("freezeAuthority") is None

    pair_created_at = pair.get("pairCreatedAt")
    age_seconds = time.time() - float(pair_created_at) / 1000 if pair_created_at else None
    quote = await get_quote(client, settings.WSOL_MINT, mint, 10_000_000, settings.SLIPPAGE_BPS)
    price_impact = float(quote.get("priceImpactPct") or 0)
    route_available = int(quote.get("outAmount") or 0) > 0

    data.update({
        "dex": pair.get("dexId"),
        "liquidity_usd": liquidity,
        "data_timestamp": time.time(),
        "tax_pct": candidate.get("tax_pct"),
        "price_impact_pct": price_impact,
        "sell_route_available": route_available,
        "sell_simulation_passed": sell_simulation_passed,
        "categoryScores": {
            "liquidity": _bounded_score(liquidity / settings.MIN_LIQUIDITY_USD * 100),
            "holder_concentration": _bounded_score((1 - top_pct / 100) * 100),
            # DexScreener does not prove LP locking; accept only an explicit provider field.
            "liquidity_security": provided_scores.get("liquidity_security"),
            "contract_security": 100 if authorities_safe else 0,
            "volume_activity": _bounded_score(min(volume / max(settings.MIN_24H_VOLUME_USD, 1), 2) * 50),
            "token_pool_age": _bounded_score((age_seconds or 0) / max(settings.MIN_TOKEN_AGE_SECONDS, 1) * 100),
            "volatility": _bounded_score(100 - price_change / max(settings.MAX_24H_PRICE_CHANGE_PCT, 1) * 100),
            "slippage_price_impact": _bounded_score(100 - price_impact / max(settings.MAX_PRICE_IMPACT_PCT, 1) * 100),
            "market_conditions": _bounded_score(min(volume_ratio / max(settings.MIN_VOLUME_LIQUIDITY_RATIO, 0.01), 2) * 50),
        },
        "volume_usd": volume,
        "transaction_count": transaction_count,
        "top_holder_pct": top_pct,
        "age_seconds": age_seconds,
    })
    return data


async def check_mint_and_freeze_authority(rpc: AsyncClient, mint: str) -> tuple[bool, str]:
    """Reject if mint or freeze authority is still active (creator can mint more
    supply or freeze your tokens at will) — the single biggest rug lever."""
    try:
        resp = await rpc.get_account_info_json_parsed(Pubkey.from_string(mint))
        if not resp.value:
            return False, "mint account not found"
        info = resp.value.data.parsed["info"]
        mint_auth = info.get("mintAuthority")
        freeze_auth = info.get("freezeAuthority")

        if settings.REQUIRE_MINT_AUTHORITY_RENOUNCED and mint_auth is not None:
            return False, "mint authority not renounced"
        if settings.REQUIRE_FREEZE_AUTHORITY_RENOUNCED and freeze_auth is not None:
            return False, "freeze authority not renounced"
        return True, "ok"
    except Exception as e:
        return False, f"authority check failed: {e}"


async def check_holder_concentration(rpc: AsyncClient, mint: str) -> tuple[bool, str]:
    """Reject if the single largest holder (excluding the LP itself, which we
    can't cleanly distinguish here, so this is conservative) owns more than
    MAX_TOP_HOLDER_PCT of supply."""
    try:
        mint_pubkey = Pubkey.from_string(mint)
        largest = await rpc.get_token_largest_accounts(mint_pubkey)
        supply_resp = await rpc.get_token_supply(mint_pubkey)
        total_supply = int(supply_resp.value.amount)
        if total_supply == 0 or not largest.value:
            return False, "no supply/holder data"

        top_amount = int(largest.value[0].amount)
        top_pct = (top_amount / total_supply) * 100
        if top_pct > settings.MAX_TOP_HOLDER_PCT:
            return False, f"top holder owns {top_pct:.1f}% (max {settings.MAX_TOP_HOLDER_PCT}%)"
        return True, f"top holder {top_pct:.1f}%"
    except Exception as e:
        return False, f"holder check failed: {e}"


async def check_liquidity(client: httpx.AsyncClient, mint: str) -> tuple[bool, str]:
    """DexScreener liquidity check. Fresh pump.fun launches often won't be
    indexed yet — if no pair data exists at all, treat as not-yet-liquid and skip."""
    try:
        resp = await client.get(DEXSCREENER_TOKEN_URL.format(mint=mint), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        pairs = data.get("pairs") or []
        if not pairs:
            return False, "no liquidity pair found yet"
        best_liquidity = max((p.get("liquidity", {}).get("usd", 0) or 0) for p in pairs)
        if best_liquidity < settings.MIN_LIQUIDITY_USD:
            return False, f"liquidity ${best_liquidity:,.0f} below min ${settings.MIN_LIQUIDITY_USD:,.0f}"
        return True, f"liquidity ${best_liquidity:,.0f}"
    except Exception as e:
        return False, f"liquidity check failed: {e}"


async def check_utility_signals(client: httpx.AsyncClient, mint: str) -> tuple[bool, str]:
    """Require public traction and project metadata before a live buy.

    These are utility proxies, not proof of product quality or profitability.
    """
    if not settings.REQUIRE_UTILITY_SIGNALS:
        return True, "utility signal gate disabled"
    try:
        resp = await client.get(DEXSCREENER_TOKEN_URL.format(mint=mint), timeout=10)
        resp.raise_for_status()
        pairs = resp.json().get("pairs") or []
        if not pairs:
            return False, "no pair data for utility signals"
        pair = max(
            pairs,
            key=lambda item: float((item.get("liquidity") or {}).get("usd") or 0),
        )
        liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
        volume_24h = float((pair.get("volume") or {}).get("h24") or 0)
        price_change_24h = float((pair.get("priceChange") or {}).get("h24") or 0)
        transactions = (pair.get("txns") or {}).get("h24") or {}
        buys = int(transactions.get("buys") or 0)
        sells = int(transactions.get("sells") or 0)
        transaction_count = buys + sells
        info = pair.get("info") or {}
        websites = info.get("websites") or []
        socials = info.get("socials") or []
        volume_ratio = volume_24h / liquidity if liquidity > 0 else 0

        if liquidity < settings.MIN_LIQUIDITY_USD:
            return False, f"liquidity ${liquidity:,.0f} below min ${settings.MIN_LIQUIDITY_USD:,.0f}"
        if volume_24h < settings.MIN_24H_VOLUME_USD:
            return False, f"24h volume ${volume_24h:,.0f} below min ${settings.MIN_24H_VOLUME_USD:,.0f}"
        if not settings.MIN_VOLUME_LIQUIDITY_RATIO <= volume_ratio <= settings.MAX_VOLUME_LIQUIDITY_RATIO:
            return False, f"volume/liquidity ratio {volume_ratio:.2f} outside {settings.MIN_VOLUME_LIQUIDITY_RATIO:.1f}-{settings.MAX_VOLUME_LIQUIDITY_RATIO:.1f}"
        if transaction_count < settings.MIN_24H_TRANSACTIONS:
            return False, f"only {transaction_count} transactions in 24h (min {settings.MIN_24H_TRANSACTIONS})"
        if price_change_24h >= settings.MAX_24H_PRICE_CHANGE_PCT:
            return False, f"already up {price_change_24h:.0f}% in 24h; do not chase"

        score = 0
        evidence = []
        if websites:
            score += 25
            evidence.append("website")
        if socials:
            score += 15
            evidence.append("socials")
        if volume_24h >= settings.MIN_24H_VOLUME_USD:
            score += 35
            evidence.append(f"24h volume ${volume_24h:,.0f}")
        if settings.MIN_VOLUME_LIQUIDITY_RATIO <= volume_ratio <= settings.MAX_VOLUME_LIQUIDITY_RATIO:
            score += 25
            evidence.append(f"volume/liquidity {volume_ratio:.2f}")

        if score < settings.MIN_UTILITY_SCORE:
            return False, (
                f"utility evidence score {score}/100 below min "
                f"{settings.MIN_UTILITY_SCORE} ({', '.join(evidence) or 'no public signals'})"
            )
        return True, f"utility evidence score {score}/100 ({', '.join(evidence)})"
    except Exception as e:
        return False, f"utility signal check failed: {e}"


async def run_all_checks(client: httpx.AsyncClient, rpc: AsyncClient, mint: str) -> tuple[bool, str]:
    ok, reason = await check_mint_and_freeze_authority(rpc, mint)
    if not ok:
        return False, reason

    ok, reason = await check_holder_concentration(rpc, mint)
    if not ok:
        return False, reason

    ok, reason = await check_liquidity(client, mint)
    if not ok:
        return False, reason

    ok, reason = await check_utility_signals(client, mint)
    if not ok:
        return False, reason

    return True, f"passed all checks; {reason}"
