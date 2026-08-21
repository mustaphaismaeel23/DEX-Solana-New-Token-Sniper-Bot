import base64
import logging
import httpx
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from config import settings
from dex_allowlist import validate_quote_routes

log = logging.getLogger("jupiter_swap")

JUPITER_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"


def load_keypair() -> Keypair:
    if not settings.WALLET_PRIVATE_KEY:
        if settings.DRY_RUN:
            log.warning("WALLET_PRIVATE_KEY is empty; using a temporary dry-run wallet")
            return Keypair()
        raise RuntimeError(
            "WALLET_PRIVATE_KEY is required when DRY_RUN=false. "
            "The browser wallet connection does not configure the autonomous bot wallet."
        )
    return Keypair.from_base58_string(settings.WALLET_PRIVATE_KEY)


async def get_sol_balance(rpc: AsyncClient, pubkey) -> float:
    resp = await rpc.get_balance(pubkey, commitment=Confirmed)
    return resp.value / 1_000_000_000


async def get_token_balance_raw(rpc: AsyncClient, owner_pubkey, mint: str) -> int:
    resp = await rpc.get_token_accounts_by_owner_json_parsed(
        owner_pubkey, {"mint": Pubkey.from_string(mint)}
    )
    total = 0
    for acc in resp.value:
        info = acc.account.data.parsed["info"]
        total += int(info["tokenAmount"]["amount"])
    return total


async def get_quote(client: httpx.AsyncClient, input_mint: str, output_mint: str,
                     amount: int, slippage_bps: int) -> dict:
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount,
        "slippageBps": slippage_bps,
    }
    resp = await client.get(JUPITER_QUOTE_URL, params=params, timeout=15)
    if resp.status_code >= 400:
        detail = resp.text[:300].replace("\n", " ")
        raise RuntimeError(f"Jupiter quote HTTP {resp.status_code}: {detail}")
    return resp.json()


async def get_token_price_in_sol(client: httpx.AsyncClient, mint: str, probe_lamports: int = 10_000_000) -> float | None:
    """
    Price of `mint` in SOL, derived from a small Jupiter quote (SOL -> mint).
    Using a live quote (rather than a market-data API) means the price reflects
    what you could actually transact at, including current pool depth.
    Returns None if no route exists (e.g. rugged / delisted).
    """
    try:
        quote = await get_quote(client, settings.WSOL_MINT, mint, probe_lamports, settings.SLIPPAGE_BPS)
        out_amount = int(quote["outAmount"])
        if out_amount <= 0:
            return None
        sol_in = probe_lamports / 1_000_000_000
        return sol_in / out_amount  # SOL per raw token unit
    except httpx.RequestError as e:
        log.warning(f"Price lookup network failure for {mint}: {e}")
        return None
    except RuntimeError as e:
        log.warning(f"Price lookup rejected for {mint}: {e}")
        return None
    except (KeyError, TypeError, ValueError) as e:
        log.warning(f"Price lookup returned invalid data for {mint}: {e}")
        return None


async def build_swap_transaction(client: httpx.AsyncClient, owner_pubkey, quote: dict) -> dict:
    route_ok, route_reason = validate_quote_routes(quote)
    if not route_ok:
        raise RuntimeError(f"DEX allowlist rejected quote: {route_reason}")
    response = await client.post(JUPITER_SWAP_URL, json={
        "quoteResponse": quote,
        "userPublicKey": str(owner_pubkey),
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }, timeout=20)
    response.raise_for_status()
    return response.json()


async def execute_swap(client: httpx.AsyncClient, rpc: AsyncClient, keypair: Keypair, quote: dict) -> str:
    route_ok, route_reason = validate_quote_routes(quote)
    if not route_ok:
        raise RuntimeError(f"DEX allowlist rejected quote: {route_reason}")
    swap_tx_b64 = (await build_swap_transaction(client, keypair.pubkey(), quote))["swapTransaction"]

    raw_tx = VersionedTransaction.from_bytes(base64.b64decode(swap_tx_b64))
    signed_tx = VersionedTransaction(raw_tx.message, [keypair])

    result = await rpc.send_raw_transaction(
        bytes(signed_tx),
        opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed),
    )
    sig = str(result.value)
    await rpc.confirm_transaction(result.value, commitment=Confirmed)
    return sig


async def buy_token(client, rpc, keypair, mint: str, sol_amount: float, slippage_bps: int):
    lamports = int(sol_amount * 1_000_000_000)
    quote = await get_quote(client, settings.WSOL_MINT, mint, lamports, slippage_bps)
    sig = await execute_swap(client, rpc, keypair, quote)
    tokens_received = int(quote["outAmount"])
    entry_price_sol = sol_amount / tokens_received
    return sig, tokens_received, entry_price_sol


async def sell_token(client, rpc, keypair, mint: str, token_amount_raw: int, slippage_bps: int):
    quote = await get_quote(client, mint, settings.WSOL_MINT, token_amount_raw, slippage_bps)
    sig = await execute_swap(client, rpc, keypair, quote)
    sol_received = int(quote["outAmount"]) / 1_000_000_000
    return sig, sol_received
