"""Provider interfaces for security evidence that public market APIs do not prove."""
from dataclasses import dataclass
from typing import Protocol
import base64
import logging
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from config import settings
from jupiter_swap import get_quote, build_swap_transaction

log = logging.getLogger("security_adapters")


@dataclass(frozen=True)
class LiquiditySecurityResult:
    verified: bool
    score: float | None
    reason: str


class LiquiditySecurityProvider(Protocol):
    async def verify(self, rpc: AsyncClient, pool_address: str) -> LiquiditySecurityResult:
        ...


class SellSimulationProvider(Protocol):
    async def simulate(self, client, rpc: AsyncClient, mint: str,
                       token_amount_raw: int, owner_pubkey) -> tuple[bool, str]:
        ...


class PumpSwapLiquiditySecurityProvider:
    """Verifies pool account ownership; it does not claim LP locking."""

    async def verify(self, rpc: AsyncClient, pool_address: str) -> LiquiditySecurityResult:
        program_id = getattr(settings, "PUMPSWAP_PROGRAM_ID", "")
        if not program_id:
            return LiquiditySecurityResult(False, None, "PumpSwap program ID is not configured")
        try:
            from solders.pubkey import Pubkey
            response = await rpc.get_account_info(Pubkey.from_string(pool_address))
            if not response.value:
                return LiquiditySecurityResult(False, None, "PumpSwap pool account not found")
            if str(response.value.owner) != program_id:
                return LiquiditySecurityResult(False, None, "pool is not owned by configured PumpSwap program")
            return LiquiditySecurityResult(
                True,
                None,
                "PumpSwap pool owner verified; LP lock status still requires a lock provider",
            )
        except Exception as error:
            log.warning("PumpSwap pool verification failed: %s", error)
            return LiquiditySecurityResult(False, None, f"pool verification failed: {error}")


class JupiterRpcSellSimulator:
    """Build and simulate a real sell transaction without submitting it."""

    async def simulate(self, client, rpc: AsyncClient, mint: str,
                       token_amount_raw: int, owner_pubkey) -> tuple[bool, str]:
        if token_amount_raw <= 0:
            return False, "sell simulation amount must be positive"
        try:
            quote = await get_quote(client, mint, settings.WSOL_MINT,
                                    token_amount_raw, settings.SLIPPAGE_BPS)
            transaction = await build_swap_transaction(client, owner_pubkey, quote)
            raw_transaction = VersionedTransaction.from_bytes(
                base64.b64decode(transaction["swapTransaction"])
            )
            result = await rpc.simulate_transaction(raw_transaction, sig_verify=False)
            value = result.value
            if value.err is not None:
                return False, f"sell simulation failed: {value.err}"
            return True, "sell transaction simulation succeeded"
        except Exception as error:
            log.warning("Sell simulation failed for %s: %s", mint, error)
            return False, f"sell simulation unavailable: {error}"
