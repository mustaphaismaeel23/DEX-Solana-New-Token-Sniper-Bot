import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default=None, required: bool = False):
    val = os.getenv(key, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required env var: {key}")
    return val


@dataclass(frozen=True)
class Settings:
    # --- Solana ---
    RPC_URL: str = _get("RPC_URL", required=True)
    HELIUS_API_KEY: str = _get("HELIUS_API_KEY", required=True)
    WALLET_PRIVATE_KEY: str = _get("WALLET_PRIVATE_KEY", "")

    # --- Sources ---
    WATCH_PUMPFUN: bool = _get("WATCH_PUMPFUN", "true").lower() == "true"
    WATCH_PUMPSWAP: bool = _get("WATCH_PUMPSWAP", "true").lower() == "true"
    WATCH_ESTABLISHED_TOKENS: bool = _get("WATCH_ESTABLISHED_TOKENS", "false").lower() == "true"
    ALLOWED_DEXES: tuple[str, ...] = tuple(
        item.strip().lower() for item in _get("ALLOWED_DEXES", "pumpfun,pumpswap,raydium,orca").split(",") if item.strip()
    )
    PUMPSWAP_PROGRAM_ID: str = _get("PUMPSWAP_PROGRAM_ID", "")
    PUMPPORTAL_WS_URL: str = _get("PUMPPORTAL_WS_URL", "wss://pumpportal.fun/api/data")
    DEXSCREENER_CHECK_INTERVAL_SECONDS: int = int(_get("DEXSCREENER_CHECK_INTERVAL_SECONDS", "60"))  # how often to check trending tokens

    # --- Twitter/X Social Signals ---
    ENABLE_TWITTER_SIGNALS: bool = _get("ENABLE_TWITTER_SIGNALS", "true").lower() == "true"
    TWITTER_BEARER_TOKEN: str = _get("TWITTER_BEARER_TOKEN", "")  # X/Twitter API v2 bearer token
    MIN_TWITTER_FOLLOWERS: int = int(_get("MIN_TWITTER_FOLLOWERS", "100"))  # minimum followers for credibility
    MIN_TWITTER_ENGAGEMENT_RATE: float = float(_get("MIN_TWITTER_ENGAGEMENT_RATE", "0.1"))  # minimum engagement % 
    TWITTER_SENTIMENT_THRESHOLD: float = float(_get("TWITTER_SENTIMENT_THRESHOLD", "0.3"))  # positive sentiment threshold
    REQUIRE_TWITTER_PRESENCE: bool = _get("REQUIRE_TWITTER_PRESENCE", "false").lower() == "true"  # reject if no Twitter found
    TWITTER_MENTION_WEIGHT: float = float(_get("TWITTER_MENTION_WEIGHT", "15"))  # points added for Twitter presence

    # --- Buy sizing ---
    BUY_SIZE_SOL: float = float(_get("BUY_SIZE_SOL", "0.05"))
    MAX_CONCURRENT_POSITIONS: int = int(_get("MAX_CONCURRENT_POSITIONS", "3"))
    MIN_SOL_RESERVE: float = float(_get("MIN_SOL_RESERVE", "0.05"))
    SLIPPAGE_BPS: int = int(_get("SLIPPAGE_BPS", "500"))  # new tokens are volatile; wider default

    # --- Safety filters (all must pass to buy) ---
    MIN_LIQUIDITY_USD: float = float(_get("MIN_LIQUIDITY_USD", "50000"))
    MAX_TOP_HOLDER_PCT: float = float(_get("MAX_TOP_HOLDER_PCT", "20"))  # top non-LP holder must own < this %
    REQUIRE_MINT_AUTHORITY_RENOUNCED: bool = _get("REQUIRE_MINT_AUTHORITY_RENOUNCED", "true").lower() == "true"
    REQUIRE_FREEZE_AUTHORITY_RENOUNCED: bool = _get("REQUIRE_FREEZE_AUTHORITY_RENOUNCED", "true").lower() == "true"
    # --- Age requirements for new tokens (Pump.fun/PumpSwap) ---
    MIN_TOKEN_AGE_SECONDS: int = int(_get("MIN_TOKEN_AGE_SECONDS", "21600"))  # wait 6 hours for the token to prove itself
    MAX_TOKEN_AGE_SECONDS: int = int(_get("MAX_TOKEN_AGE_SECONDS", "86400"))  # avoid stale tokens after 24 hours
    # --- Age requirements for established tokens (Raydium, Orca, etc.) ---
    MIN_ESTABLISHED_TOKEN_AGE_SECONDS: int = int(_get("MIN_ESTABLISHED_TOKEN_AGE_SECONDS", "2592000"))  # minimum 30 days old
    MAX_ESTABLISHED_TOKEN_AGE_SECONDS: int = int(_get("MAX_ESTABLISHED_TOKEN_AGE_SECONDS", "7776000"))  # maximum 90 days old (optional)
    REQUIRE_UTILITY_SIGNALS: bool = _get("REQUIRE_UTILITY_SIGNALS", "true").lower() == "true"
    MIN_UTILITY_SCORE: int = int(_get("MIN_UTILITY_SCORE", "70"))
    MIN_ESTABLISHED_UTILITY_SCORE: int = int(_get("MIN_ESTABLISHED_UTILITY_SCORE", "50"))  # lower bar for established tokens
    MIN_24H_VOLUME_USD: float = float(_get("MIN_24H_VOLUME_USD", "100000"))
    MIN_ESTABLISHED_24H_VOLUME_USD: float = float(_get("MIN_ESTABLISHED_24H_VOLUME_USD", "50000"))  # lower volume requirement
    MIN_VOLUME_LIQUIDITY_RATIO: float = float(_get("MIN_VOLUME_LIQUIDITY_RATIO", "0.5"))
    MAX_VOLUME_LIQUIDITY_RATIO: float = float(_get("MAX_VOLUME_LIQUIDITY_RATIO", "3.0"))
    MIN_24H_TRANSACTIONS: int = int(_get("MIN_24H_TRANSACTIONS", "100"))
    MIN_ESTABLISHED_24H_TRANSACTIONS: int = int(_get("MIN_ESTABLISHED_24H_TRANSACTIONS", "50"))  # lower transaction count
    MAX_24H_PRICE_CHANGE_PCT: float = float(_get("MAX_24H_PRICE_CHANGE_PCT", "400"))

    # --- Risk engine ---
    MIN_RISK_SCORE: float = float(_get("MIN_RISK_SCORE", "65"))
    MAX_POSITION_SIZE_MULTIPLIER: float = float(_get("MAX_POSITION_SIZE_MULTIPLIER", "1.0"))
    RISK_DATA_MAX_AGE_SECONDS: int = int(_get("RISK_DATA_MAX_AGE_SECONDS", "300"))
    MAX_PRICE_IMPACT_PCT: float = float(_get("MAX_PRICE_IMPACT_PCT", "5"))
    MAX_TAX_PCT: float = float(_get("MAX_TAX_PCT", "10"))
    MIN_RISK_LIQUIDITY_USD: float = float(_get("MIN_RISK_LIQUIDITY_USD", "50000"))

    # --- Circuit breaker ---
    DAILY_LOSS_THRESHOLD_SOL: float = float(_get("DAILY_LOSS_THRESHOLD_SOL", "0.25"))
    MAX_CONSECUTIVE_LOSSES: int = int(_get("MAX_CONSECUTIVE_LOSSES", "3"))
    RAPID_DRAWDOWN_PCT: float = float(_get("RAPID_DRAWDOWN_PCT", "15"))
    CIRCUIT_BREAKER_COOLDOWN_SECONDS: int = int(_get("CIRCUIT_BREAKER_COOLDOWN_SECONDS", "900"))
    CIRCUIT_BREAKER_MANUAL_RESET: bool = _get("CIRCUIT_BREAKER_MANUAL_RESET", "true").lower() == "true"
    CIRCUIT_BREAKER_RESET_TOKEN: str = _get("CIRCUIT_BREAKER_RESET_TOKEN", "")

    # --- Staged profit taking ---
    PROFIT_TAKE_2X_PCT: float = float(_get("PROFIT_TAKE_2X_PCT", "50"))
    PROFIT_TAKE_5X_PCT: float = float(_get("PROFIT_TAKE_5X_PCT", "25"))
    PROFIT_TAKE_10X_REMAINING_PCT: float = float(_get("PROFIT_TAKE_10X_REMAINING_PCT", "80"))

    # --- Exit strategy: trailing stop after a profit trigger ---
    PROFIT_TRIGGER_PCT: float = float(_get("PROFIT_TRIGGER_PCT", "50"))   # activate trailing stop at +50%
    TRAIL_PCT: float = float(_get("TRAIL_PCT", "20"))                     # sell if -20% from peak once active
    HARD_STOP_LOSS_PCT: float = float(_get("HARD_STOP_LOSS_PCT", "35"))   # sell if -35% from entry, any time
    MAX_HOLD_SECONDS: int = int(_get("MAX_HOLD_SECONDS", "3600"))         # force-exit safety timeout
    POSITION_CHECK_INTERVAL_SECONDS: float = float(_get("POSITION_CHECK_INTERVAL_SECONDS", "5"))

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = _get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = _get("TELEGRAM_CHAT_ID", "")

    # --- Misc ---
    DRY_RUN: bool = _get("DRY_RUN", "true").lower() == "true"
    DB_PATH: str = _get("DB_PATH", "sniper.db")
    WSOL_MINT: str = "So11111111111111111111111111111111111111112"


settings = Settings()
