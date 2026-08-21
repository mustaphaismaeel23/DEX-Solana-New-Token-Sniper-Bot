import asyncio
import logging
import httpx
from solana.rpc.async_api import AsyncClient

from config import settings
from database import init_db, clear_stop_request, is_stop_requested
from jupiter_swap import load_keypair, get_sol_balance
from pump_scanner import watch_pumpfun, watch_pumpswap
from buyer import try_buy
from position_manager import check_positions
from notifier import notify
from circuit_breaker import CircuitBreaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


async def consume_candidates(queue: asyncio.Queue, client, rpc, keypair, breaker):
    while not is_stop_requested():
        try:
            candidate = await asyncio.wait_for(queue.get(), timeout=1)
        except asyncio.TimeoutError:
            continue
        try:
            await try_buy(client, rpc, keypair, candidate, breaker)
        except Exception:
            log.exception(f"Unexpected error handling candidate {candidate}")
        finally:
            queue.task_done()


async def position_monitor_loop(client, rpc, keypair, breaker):
    while not is_stop_requested():
        try:
            await check_positions(client, rpc, keypair, breaker)
        except Exception:
            log.exception("Error in position monitor loop")
        await asyncio.sleep(settings.POSITION_CHECK_INTERVAL_SECONDS)


async def stop_watcher(tasks):
    while not is_stop_requested():
        await asyncio.sleep(1)
    log.warning("Stop requested from dashboard; shutting down bot tasks")
    for task in tasks:
        task.cancel()


async def main_loop():
    init_db()
    clear_stop_request()
    keypair = load_keypair()
    log.info(f"Bot wallet: {keypair.pubkey()}")
    log.info(f"Watching pump.fun={settings.WATCH_PUMPFUN} PumpSwap={settings.WATCH_PUMPSWAP}")
    log.info(f"DRY_RUN = {settings.DRY_RUN}")

    queue: asyncio.Queue = asyncio.Queue()
    breaker = CircuitBreaker(persist=True)

    async with httpx.AsyncClient() as client, AsyncClient(settings.RPC_URL) as rpc:
        our_balance = await get_sol_balance(rpc, keypair.pubkey())
        await notify(
            f"🚀 Sniper bot started\nWallet: `{keypair.pubkey()}`\n"
            f"Balance: {our_balance:.4f} SOL\nDry run: {settings.DRY_RUN}\n"
            f"Buy size: {settings.BUY_SIZE_SOL} SOL | Max positions: {settings.MAX_CONCURRENT_POSITIONS}\n"
            f"Profit trigger: +{settings.PROFIT_TRIGGER_PCT}% | Trail: {settings.TRAIL_PCT}% | "
            f"Hard stop: -{settings.HARD_STOP_LOSS_PCT}%"
        )

        tasks = [
            asyncio.create_task(consume_candidates(queue, client, rpc, keypair, breaker)),
            asyncio.create_task(position_monitor_loop(client, rpc, keypair, breaker)),
        ]
        if settings.WATCH_PUMPFUN:
            tasks.append(asyncio.create_task(watch_pumpfun(queue)))
        if settings.WATCH_PUMPSWAP:
            tasks.append(asyncio.create_task(watch_pumpswap(queue)))

        watcher = asyncio.create_task(stop_watcher(tasks))
        try:
            await asyncio.gather(*tasks, watcher, return_exceptions=True)
        finally:
            for task in tasks + [watcher]:
                if not task.done():
                    task.cancel()


if __name__ == "__main__":
    asyncio.run(main_loop())
