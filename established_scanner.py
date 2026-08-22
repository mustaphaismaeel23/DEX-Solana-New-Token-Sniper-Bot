"""
Scans for established tokens with good metrics from various DEXes.
Periodically checks trending and high-volume tokens from Raydium, Orca, and other major DEXes.
Unlike new token scanners, this looks for tokens that have proven liquidity and volume.
"""
import asyncio
import json
import logging
import time
import httpx
from config import settings

log = logging.getLogger("established_scanner")

DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/latest/dex"
SOLSCAN_TOKENS_URL = "https://api.solscan.io/v2/token/token_list"


async def _fetch_trending_tokens(client: httpx.AsyncClient, dex: str) -> list[dict]:
    """Fetch trending tokens from a specific DEX via DexScreener."""
    try:
        response = await client.get(
            f"{DEXSCREENER_TOKENS_URL}/tokens/{dex}",
            timeout=15,
            params={"order": "volume", "limit": 50}
        )
        response.raise_for_status()
        data = response.json()
        tokens = []
        for item in data.get("tokens", [])[:50]:
            tokens.append({
                "mint": item.get("address"),
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "dex": dex,
                "volume_24h": float(item.get("volume24hUsd") or 0),
                "liquidity": float(item.get("liquidityUsd") or 0),
                "price": float(item.get("priceUsd") or 0),
            })
        return tokens
    except Exception as e:
        log.warning(f"Failed to fetch trending tokens from {dex}: {e}")
        return []


async def _fetch_top_performers(client: httpx.AsyncClient, dex: str) -> list[dict]:
    """Fetch top-performing tokens (by 24h price increase) from a DEX."""
    try:
        response = await client.get(
            f"{DEXSCREENER_TOKENS_URL}/tokens/{dex}",
            timeout=15,
            params={"order": "priceChange", "limit": 30}
        )
        response.raise_for_status()
        data = response.json()
        tokens = []
        for item in data.get("tokens", [])[:30]:
            price_change = float(item.get("priceChange24hPercent") or 0)
            # Only include tokens with moderate gains (avoid pump-and-dumps)
            if -50 < price_change < 150:  # Between -50% and +150%
                tokens.append({
                    "mint": item.get("address"),
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "dex": dex,
                    "price_change_24h": price_change,
                    "volume_24h": float(item.get("volume24hUsd") or 0),
                    "liquidity": float(item.get("liquidityUsd") or 0),
                })
        return tokens
    except Exception as e:
        log.warning(f"Failed to fetch top performers from {dex}: {e}")
        return []


async def _filter_quality_tokens(tokens: list[dict]) -> list[dict]:
    """Filter tokens by quality metrics."""
    filtered = []
    for token in tokens:
        # Skip if no mint address
        if not token.get("mint"):
            continue
        
        # Enforce minimum liquidity
        if token.get("liquidity", 0) < settings.MIN_LIQUIDITY_USD:
            continue
        
        # Enforce minimum volume
        volume = token.get("volume_24h", 0)
        min_volume = settings.MIN_ESTABLISHED_24H_VOLUME_USD
        if volume < min_volume:
            continue
        
        # Volume/Liquidity ratio should be reasonable
        if token.get("liquidity", 0) > 0:
            ratio = volume / token.get("liquidity", 1)
            if ratio < settings.MIN_VOLUME_LIQUIDITY_RATIO or ratio > settings.MAX_VOLUME_LIQUIDITY_RATIO:
                continue
        
        filtered.append(token)
    
    return filtered


async def watch_established_tokens(queue: asyncio.Queue, client: httpx.AsyncClient):
    """Periodically scan established tokens and add them to the queue."""
    dexes = ["raydium", "orca", "meteora", "invariant"]
    seen_mints = set()
    
    while True:
        try:
            log.info("Scanning established tokens from DEXes...")
            all_tokens = []
            
            # Fetch trending and top performers from each DEX
            for dex in dexes:
                if dex.lower() not in settings.ALLOWED_DEXES:
                    continue
                
                trending = await _fetch_trending_tokens(client, dex)
                performers = await _fetch_top_performers(client, dex)
                all_tokens.extend(trending + performers)
            
            # Filter by quality metrics
            quality_tokens = await _filter_quality_tokens(all_tokens)
            
            # Add new tokens to queue (avoid duplicates)
            new_count = 0
            for token in quality_tokens:
                mint = token.get("mint")
                if mint and mint not in seen_mints:
                    seen_mints.add(mint)
                    await queue.put({
                        "mint": mint,
                        "source": "established",
                        "dex": token.get("dex", "unknown").lower(),
                        "created_at": time.time(),
                        "name": token.get("name"),
                        "symbol": token.get("symbol"),
                        "volume_24h": token.get("volume_24h"),
                        "liquidity": token.get("liquidity"),
                        "is_established": True,
                    })
                    new_count += 1
            
            log.info(f"Found {new_count} new established tokens to evaluate")
            
            # Keep only recent mints in memory to allow reprocessing after cooldown
            if len(seen_mints) > 500:
                seen_mints.clear()
                log.info("Cleared seen mints cache")
            
            # Wait before next check
            await asyncio.sleep(settings.DEXSCREENER_CHECK_INTERVAL_SECONDS)
            
        except Exception as e:
            log.warning(f"Error scanning established tokens, retrying in 30s: {e}")
            await asyncio.sleep(30)
