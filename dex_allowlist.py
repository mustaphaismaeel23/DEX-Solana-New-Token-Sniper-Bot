"""Centralized DEX/source policy for autonomous trading."""
import re
import os

settings = None


def normalize_dex(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return {
        "pumpfunamm": "pumpfun",
        "pumpswapamm": "pumpswap",
    }.get(normalized, normalized)


def allowed_dexes() -> frozenset[str]:
    configured = os.getenv("ALLOWED_DEXES")
    if configured is None and settings is not None:
        configured = settings.ALLOWED_DEXES
    if configured is None:
        try:
            from config import settings as configured_settings
            configured = configured_settings.ALLOWED_DEXES
        except (ImportError, RuntimeError):
            configured = ("pumpfun", "pumpswap")
    if isinstance(configured, str):
        configured = configured.split(",")
    return frozenset(normalize_dex(value) for value in configured if normalize_dex(value))


def identify_dex(candidate: dict | None = None, pair: dict | None = None) -> str:
    candidate = candidate or {}
    pair = pair or {}
    values = (pair.get("dexId"), pair.get("dex"), pair.get("label"),
              candidate.get("dex"), candidate.get("dex_id"), candidate.get("pool"),
              candidate.get("label"), candidate.get("source"))
    for value in values:
        normalized = normalize_dex(value)
        if normalized:
            return normalized
    return ""


def validate_discovery(candidate: dict) -> tuple[bool, str]:
    """Validate the source label before any network balance/quote work."""
    dex = identify_dex(candidate)
    if not dex:
        return False, "DEX cannot be identified"
    if dex not in allowed_dexes():
        return False, f"unsupported DEX/source: {dex}"
    return True, dex


def validate_pool(candidate: dict, pair: dict | None = None) -> tuple[bool, str]:
    """Require an explicitly identified PumpSwap pool for autonomous entries."""
    dex = identify_dex(candidate, pair)
    if dex != "pumpswap":
        return False, f"PumpSwap pool not verified (identified={dex or 'unknown'})"
    return True, "PumpSwap pool verified"


def validate_quote_routes(quote: dict) -> tuple[bool, str]:
    """Reject Jupiter routes containing unknown or omitted AMM identification."""
    routes = quote.get("routePlan") if isinstance(quote, dict) else None
    if not routes:
        return False, "quote route cannot be verified"
    allowed = allowed_dexes()
    labels = []
    for route in routes:
        label = identify_dex(route.get("swapInfo") or {})
        if not label or label not in allowed:
            return False, f"quote uses unsupported or unknown DEX: {label or 'unknown'}"
        labels.append(label)
    return True, ",".join(labels)
