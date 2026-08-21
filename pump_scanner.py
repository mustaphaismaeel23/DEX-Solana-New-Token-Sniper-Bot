"""
Streams new pump.fun token launches via PumpPortal's public websocket API
(https://pumpportal.fun/data-api/real-time). Free, no API key needed.
"""
import asyncio
import json
import logging
import time
import websockets
from config import settings

log = logging.getLogger("pump_scanner")


def _timestamp_seconds(value):
    if not isinstance(value, (int, float)):
        return time.time()
    value = float(value)
    return value / 1000 if value > 10_000_000_000 else value


async def watch_pumpfun(queue: asyncio.Queue):
    """Reconnects forever; pushes {'mint','source','created_at'} dicts onto queue."""
    while True:
        try:
            async with websockets.connect(settings.PUMPPORTAL_WS_URL, ping_interval=20) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                log.info("Connected to PumpPortal, subscribed to new token events")
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    mint = data.get("mint")
                    if not mint:
                        continue
                    await queue.put({
                        "mint": mint,
                        "source": "pumpfun",
                        "created_at": time.time(),
                        "name": data.get("name"),
                        "symbol": data.get("symbol"),
                    })
        except Exception as e:
            log.warning(f"PumpPortal websocket error, reconnecting in 5s: {e}")
            await asyncio.sleep(5)


async def watch_pumpswap(queue: asyncio.Queue):
    """Stream Pump.fun migrations and label their destination as PumpSwap."""
    while True:
        try:
            async with websockets.connect(settings.PUMPPORTAL_WS_URL, ping_interval=20) as ws:
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                log.info("Connected to PumpPortal, subscribed to PumpSwap migrations")
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    mint = data.get("mint")
                    if not mint:
                        continue
                    await queue.put({
                        "mint": mint,
                        "source": "pumpswap",
                        "dex": "pumpswap",
                        "pool": data.get("pool") or data.get("amm") or "pumpswap",
                        "created_at": _timestamp_seconds(data.get("timestamp")),
                        "name": data.get("name"),
                        "symbol": data.get("symbol"),
                    })
        except Exception as e:
            log.warning(f"PumpSwap migration websocket error, reconnecting in 5s: {e}")
            await asyncio.sleep(5)
