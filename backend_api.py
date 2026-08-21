import sqlite3
import json
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import dotenv_values
from dex_allowlist import allowed_dexes, normalize_dex, validate_quote_routes

ROOT = Path(__file__).resolve().parent
ENV = dotenv_values(ROOT / ".env")


def env_value(name, default):
    value = ENV.get(name)
    return value if value not in (None, "") else default


DB_PATH = ROOT / env_value("DB_PATH", "sniper.db")

# Use requests for Solana RPC calls
import requests
import time
import hmac

SOLANA_RPC = env_value("SOLANA_RPC", env_value("RPC_URL", "https://api.mainnet-beta.solana.com"))
JUPITER_API = env_value("JUPITER_API", "https://lite-api.jup.ag/swap/v1")
DEXSCREENER_API = "https://api.dexscreener.com"
SOLANA_AVAILABLE = True
HELIUS_API_KEY = env_value("HELIUS_API_KEY", "")
MIN_TRADE_SOL = float(env_value("MIN_TRADE_SOL", env_value("BUY_SIZE_SOL", "0.05")))
MIN_START_BALANCE_SOL = float(env_value("MIN_START_BALANCE_SOL", "0.02"))
SLIPPAGE_BPS = int(env_value("SLIPPAGE_BPS", "500"))
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL_MINT = "So11111111111111111111111111111111111111112"

app = Flask(__name__)
# Enable CORS for all routes
cors_config = {
    "origins": ["*"],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type"]
}
CORS(app, resources={r"/*": cors_config})


SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mint TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL DEFAULT 'dashboard',
    opened_at INTEGER NOT NULL,
    entry_price_sol REAL NOT NULL DEFAULT 0,
    token_amount REAL NOT NULL DEFAULT 0,
    peak_price_sol REAL NOT NULL DEFAULT 0,
    trigger_active INTEGER NOT NULL DEFAULT 0,
    buy_signature TEXT,
    owner_wallet TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    close_reason TEXT,
    sell_signature TEXT,
    closed_at INTEGER
);
CREATE TABLE IF NOT EXISTS skipped_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    mint TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trade_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    mint TEXT,
    wallet TEXT,
    amount REAL,
    signature TEXT,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL,
    consecutive_losses INTEGER NOT NULL DEFAULT 0,
    daily_loss_sol REAL NOT NULL DEFAULT 0,
    drawdown_pct REAL NOT NULL DEFAULT 0,
    paused_at REAL,
    last_reason TEXT NOT NULL DEFAULT '',
    loss_day TEXT NOT NULL
);
"""


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS bot_control (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                stop_requested INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            "INSERT OR IGNORE INTO bot_control (id, stop_requested, updated_at) VALUES (1, 0, ?)",
            (int(time.time()),),
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(positions)")}
        if "owner_wallet" not in columns:
            conn.execute("ALTER TABLE positions ADD COLUMN owner_wallet TEXT")
        conn.execute(
            "INSERT OR IGNORE INTO circuit_breaker_state (id, state, loss_day) VALUES (1, 'NORMAL', ?)",
            (time.strftime("%Y-%m-%d"),),
        )


init_db()


def circuit_breaker_reset_token():
    return env_value("CIRCUIT_BREAKER_RESET_TOKEN", "")


@app.get("/api/health")
def health():
    """Report service and dependency state without masking failures."""
    database_ok = True
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("SELECT 1")
    except sqlite3.Error:
        database_ok = False
    status = "ok" if database_ok else "degraded"
    return jsonify({
        "status": status,
        "database": "ok" if database_ok else "error",
        "rpc_configured": bool(SOLANA_RPC),
        "helius_configured": bool(HELIUS_API_KEY),
        "timestamp": datetime.now().isoformat(),
    }), (200 if database_ok else 503)


@app.get("/api/circuit-breaker")
def circuit_breaker_status():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM circuit_breaker_state WHERE id=1").fetchone()
    return jsonify(dict(row) if row else {"state": "EMERGENCY_STOP", "last_reason": "state unavailable"})


@app.post("/api/circuit-breaker/reset")
def reset_circuit_breaker():
    configured = circuit_breaker_reset_token()
    supplied = request.headers.get("X-Circuit-Breaker-Token", "")
    if not configured or not hmac.compare_digest(supplied, configured):
        return jsonify({"error": "valid circuit-breaker reset token required"}), 403
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """UPDATE circuit_breaker_state SET state='NORMAL', consecutive_losses=0,
               paused_at=NULL, last_reason='manual reset' WHERE id=1"""
        )
    return jsonify({"state": "NORMAL", "status": "reset"})

def query(sql, params=()):
    if not DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except Exception as e:
        print(f"Database error: {e}")
        return []


def rpc_call(method, params):
    response = requests.post(
        SOLANA_RPC,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=8,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", "Solana RPC error"))
    return data.get("result")


def helius_rpc_call(method, params):
    if not HELIUS_API_KEY:
        return None
    response = requests.post(
        f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", "Helius RPC error"))
    return data.get("result")


def record_action(action, status="requested", mint=None, wallet=None, amount=None, signature=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO trade_actions (action, mint, wallet, amount, signature, status, created_at) VALUES (?,?,?,?,?,?,?)",
            (action, mint, wallet, amount, signature, status, int(time.time())),
        )


def request_bot_stop():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE bot_control SET stop_requested=1, updated_at=? WHERE id=1", (int(time.time()),))


def get_live_balance_sol(address):
    result = rpc_call("getBalance", [address])
    if not result:
        raise ValueError("wallet balance unavailable")
    return float(result["value"]) / 1e9


def get_sol_amount_for_usd(usd_amount):
    """Convert a USD/USDC threshold to lamports using a live Jupiter quote."""
    slippage_bps = int(env_value("SLIPPAGE_BPS", str(SLIPPAGE_BPS)))
    response = requests.get(
        f"{JUPITER_API}/quote",
        params={
            "inputMint": USDC_MINT,
            "outputMint": WSOL_MINT,
            "amount": int(usd_amount * 1_000_000),
            "slippageBps": slippage_bps,
        },
        timeout=10,
    )
    response.raise_for_status()
    out_amount = int(response.json().get("outAmount") or 0)
    if out_amount <= 0:
        raise ValueError("SOL price unavailable")
    return out_amount / 1e9


def record_wallet_position(action, payload):
    """Persist a position only after the browser wallet reports a signature."""
    mint = payload.get("mint")
    signature = payload.get("signature")
    wallet = payload.get("wallet")
    quote = payload.get("quote") or {}
    if not mint or not signature or not wallet:
        return False

    with sqlite3.connect(DB_PATH) as conn:
        if action == "buy":
            token_amount = int(quote.get("outAmount") or 0)
            sol_amount = float(payload.get("amount") or 0)
            if token_amount <= 0 or sol_amount <= 0:
                return False
            entry_price = sol_amount / token_amount
            conn.execute(
                """INSERT OR REPLACE INTO positions
                         (mint, source, opened_at, entry_price_sol, token_amount, peak_price_sol, buy_signature, owner_wallet, status)
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                     (mint, "jupiter-wallet", int(time.time()), entry_price, token_amount, entry_price, signature, wallet, "OPEN"),
            )
            return True

        if action == "sell":
            cursor = conn.execute(
                """UPDATE positions SET status='CLOSED', close_reason='wallet sell',
                   sell_signature=?, closed_at=? WHERE id=(
                         SELECT id FROM positions WHERE mint=? AND owner_wallet=? AND status='OPEN' ORDER BY opened_at DESC LIMIT 1
                   )""",
                     (signature, int(time.time()), mint, wallet),
            )
            return cursor.rowcount > 0

    return False


@app.post("/api/buy")
def buy():
    """Trigger a buy signal to the bot"""
    payload = request.get_json(silent=True) or {}
    position_opened = record_wallet_position("buy", payload) if payload.get("signature") else False
    record_action("buy", status="submitted" if payload.get("signature") else "requested", mint=payload.get("mint"), wallet=payload.get("wallet"), amount=payload.get("amount"), signature=payload.get("signature"))
    return jsonify({
        "status": "success",
        "action": "buy",
        "position_opened": position_opened,
        "timestamp": datetime.now().isoformat()
    })


@app.post("/api/sell")
def sell():
    """Trigger a sell signal to the bot"""
    payload = request.get_json(silent=True) or {}
    position_closed = record_wallet_position("sell", payload) if payload.get("signature") else False
    record_action("sell", status="submitted" if payload.get("signature") else "requested", mint=payload.get("mint"), wallet=payload.get("wallet"), amount=payload.get("amount"), signature=payload.get("signature"))
    return jsonify({
        "status": "success",
        "action": "sell",
        "position_closed": position_closed,
        "timestamp": datetime.now().isoformat()
    })


@app.post("/api/stop")
def stop_bot():
    """Stop the bot or exit all positions"""
    request_bot_stop()
    record_action("stop")
    return jsonify({
        "status": "success",
        "action": "stop",
        "timestamp": datetime.now().isoformat()
    })


# Auto-trading state
auto_trading = {"active": False, "trades_executed": 0}


def open_paper_position(token):
    """Open a visible paper position until a browser wallet signs a real swap."""
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        existing = conn.execute(
            "SELECT id FROM positions WHERE mint=? AND status='OPEN'",
            (token["mint"],),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """INSERT OR IGNORE INTO positions
               (mint, source, opened_at, entry_price_sol, token_amount, peak_price_sol, buy_signature, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (token["mint"], "auto-paper", now, 0, 1, 0, "paper", "OPEN"),
        )
        return True


@app.post("/api/autotrading/start")
def start_autotrading():
    """Start paper auto-trading and select a live low-risk candidate."""
    payload = request.get_json(silent=True) or {}
    wallet = payload.get("wallet")
    if not wallet:
        return jsonify({"error": "Connect a wallet before starting auto-trading"}), 400
    try:
        balance = get_live_balance_sol(wallet)
    except Exception as error:
        return jsonify({"error": f"Could not verify wallet balance: {error}"}), 502
    required_balance = MIN_START_BALANCE_SOL
    if balance < required_balance:
        return jsonify({
            "error": f"Minimum balance is {required_balance:.6f} SOL",
            "balance": balance,
            "required_balance": required_balance,
            "minimum_sol": required_balance,
        }), 400

    global tokens_scanned
    try:
        live_tokens = fetch_live_tokens()
        if live_tokens:
            tokens_scanned = live_tokens
    except requests.RequestException as error:
        print(f"Auto-trade scan unavailable, using cached tokens: {error}")

    candidates = [token for token in tokens_scanned if token.get("risk_score", 100) < 70 and token.get("mint")]
    candidate = candidates[0] if candidates else None
    position_opened = open_paper_position(candidate) if candidate else False
    auto_trading["active"] = True
    auto_trading["trades_executed"] = 1 if position_opened else 0
    auto_trading["candidate"] = candidate
    record_action("auto_buy", status="paper", mint=candidate.get("mint") if candidate else None, amount=0)
    return jsonify({
        "status": "success",
        "action": "autotrading_started",
        "mode": "paper",
        "position_opened": position_opened,
        "candidate": candidate,
        "timestamp": datetime.now().isoformat()
    })


@app.post("/api/autotrading/stop")
def stop_autotrading():
    """Stop automated trading"""
    auto_trading["active"] = False
    return jsonify({
        "status": "success",
        "action": "autotrading_stopped",
        "trades_executed": auto_trading["trades_executed"],
        "candidate": auto_trading.get("candidate"),
        "timestamp": datetime.now().isoformat()
    })


# Do not display stale or unverified fallback tokens.
tokens_scanned = []


def risk_for_pair(pair, include_holders=False):
    liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
    market_cap = float(pair.get("marketCap") or pair.get("fdv") or 0)
    volume = float((pair.get("volume") or {}).get("h24") or 0)
    created_at = int((pair.get("pairCreatedAt") or time.time() * 1000) / 1000)
    age = max(0, time.time() - created_at)
    risk_factors = {
        "low_market_cap": market_cap < 500000,
        "low_liquidity": liquidity < 100000,
        "thin_volume": volume < max(liquidity * 0.05, 1000),
        "new_token": age < 86400,
        "negative_price_trend": float((pair.get("priceChange") or {}).get("h24") or 0) < -25,
    }

    holder_metrics = get_holder_metrics(pair.get("baseToken", {}).get("address")) if include_holders else {
        "holders": None,
        "top10_holdings": None,
    }
    risk_score = min(100, sum(value * weight for value, weight in [
        (risk_factors["low_market_cap"], 20),
        (risk_factors["low_liquidity"], 30),
        (risk_factors["thin_volume"], 20),
        (risk_factors["new_token"], 15),
        (risk_factors["negative_price_trend"], 15),
    ]))
    if holder_metrics["holders"] is not None:
        risk_factors["few_holders"] = holder_metrics["holders"] < 1000
        risk_factors["high_concentration"] = (holder_metrics["top10_holdings"] or 0) > 50
        risk_score = min(100, risk_score + (10 if risk_factors["few_holders"] else 0) + (10 if risk_factors["high_concentration"] else 0))
    return {
        "id": pair.get("pairAddress") or pair.get("url"),
        "mint": pair.get("baseToken", {}).get("address"),
        "name": pair.get("baseToken", {}).get("name") or "Unknown token",
        "symbol": pair.get("baseToken", {}).get("symbol") or "???",
        "market_cap": market_cap,
        "liquidity": liquidity,
        "volume_24h": volume,
        "price_usd": float(pair.get("priceUsd") or 0),
        "price_change_24h": float((pair.get("priceChange") or {}).get("h24") or 0),
        "created_at": created_at,
        "holders": holder_metrics["holders"],
        "holders_estimated": holder_metrics.get("holders_estimated", False),
        "top10_holdings": holder_metrics["top10_holdings"],
        "risk_score": risk_score,
        "rugpull_probability": round(risk_score / 100, 2),
        "dex": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"),
        "risk_factors": risk_factors,
    }


def get_holder_metrics(mint):
    """Read non-zero token account count and concentration from chain data."""
    if not mint:
        return {"holders": None, "top10_holdings": None}

    try:
        if HELIUS_API_KEY:
            helius_url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
            response = requests.post(
                helius_url,
                json={
                    "jsonrpc": "2.0",
                    "id": "holders",
                    "method": "getTokenAccounts",
                    "params": [mint, None, None, None, None, None, {}, None],
                },
                timeout=8,
            )
            response.raise_for_status()
            result = response.json().get("result") or {}
            accounts = result.get("token_accounts") or result.get("accounts") or []
            if accounts:
                amounts = sorted(
                    [int(account.get("amount") or account.get("tokenAmount", {}).get("amount") or 0) for account in accounts],
                    reverse=True,
                )
                total = sum(amounts)
                top10 = (sum(amounts[:10]) / total * 100) if total else None
                return {"holders": int(result.get("total") or len(accounts)), "top10_holdings": top10}
    except (requests.RequestException, RuntimeError, ValueError, TypeError) as error:
        print(f"Holder lookup failed for {mint}: {error}")

    try:
        largest = helius_rpc_call("getTokenLargestAccounts", [mint]) or rpc_call("getTokenLargestAccounts", [mint])
        accounts = (largest or {}).get("value") or []
        if accounts:
            amounts = sorted([int(account.get("amount") or 0) for account in accounts], reverse=True)
            total = sum(amounts)
            return {
                "holders": len(accounts),
                "holders_estimated": True,
                "top10_holdings": (sum(amounts[:10]) / total * 100) if total else None,
            }
    except (requests.RequestException, RuntimeError, ValueError, TypeError) as error:
        print(f"Largest-holder lookup failed for {mint}: {error}")

    return {"holders": None, "top10_holdings": None}


def fetch_live_tokens():
    profiles_response = requests.get(f"{DEXSCREENER_API}/token-profiles/latest/v1", timeout=10)
    profiles_response.raise_for_status()
    profiles = [profile for profile in profiles_response.json() if profile.get("chainId") == "solana"][:30]
    addresses = ",".join(profile["tokenAddress"] for profile in profiles if profile.get("tokenAddress"))
    if not addresses:
        return []
    response = requests.get(f"{DEXSCREENER_API}/latest/dex/tokens/{addresses}", timeout=10)
    response.raise_for_status()
    pairs = [pair for pair in response.json().get("pairs", [])
             if pair.get("chainId") == "solana"
             and normalize_dex(pair.get("dexId")) in allowed_dexes()]
    best_pairs = {}
    for pair in pairs:
        mint = pair.get("baseToken", {}).get("address")
        if not mint:
            continue
        liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
        volume = float((pair.get("volume") or {}).get("h24") or 0)
        ranking = (liquidity, volume, pair.get("pairCreatedAt") or 0)
        current = best_pairs.get(mint)
        if current is None or ranking > current[0]:
            best_pairs[mint] = (ranking, pair)

    tokens = [risk_for_pair(pair) for _, pair in best_pairs.values()]
    tokens.sort(key=lambda token: (token["created_at"], token["liquidity"]), reverse=True)
    return tokens[:30]


def fetch_best_pair(mint):
    response = requests.get(f"{DEXSCREENER_API}/latest/dex/tokens/{mint}", timeout=10)
    response.raise_for_status()
    pairs = [pair for pair in response.json().get("pairs", [])
             if pair.get("chainId") == "solana"
             and normalize_dex(pair.get("dexId")) in allowed_dexes()]
    if not pairs:
        return None
    return max(
        pairs,
        key=lambda pair: (
            float((pair.get("liquidity") or {}).get("usd") or 0),
            float((pair.get("volume") or {}).get("h24") or 0),
            pair.get("pairCreatedAt") or 0,
        ),
    )


@app.get("/api/scanner/tokens")
def scan_tokens():
    """Get newly created tokens with risk analysis"""
    global tokens_scanned
    try:
        live_tokens = fetch_live_tokens()
        if live_tokens:
            tokens_scanned = live_tokens
    except requests.RequestException as error:
        print(f"DexScreener unavailable, using cached tokens: {error}")
    return jsonify({
        "tokens": tokens_scanned,
        "source": "dexscreener" if tokens_scanned and tokens_scanned[0].get("pair_address") else "cached",
        "timestamp": datetime.now().isoformat()
    })


@app.get("/api/scanner/token/<mint>")
def token_details(mint):
    """Get detailed risk analysis for a specific token"""
    token = next((t for t in tokens_scanned if t["mint"] == mint), None)
    if not token:
        return jsonify({"error": "Token not found"}), 404

    try:
        pair = fetch_best_pair(mint)
        token = risk_for_pair(pair, include_holders=True) if pair else dict(token)
    except requests.RequestException as error:
        print(f"Live token detail lookup failed for {mint}: {error}")
        token = dict(token)
        holder_metrics = get_holder_metrics(mint)
        token.update(holder_metrics)
        token["holders_estimated"] = holder_metrics.get("holders_estimated", False)
    
    risk_factors = token.get("risk_factors") or {
        "low_market_cap": token["market_cap"] < 500000,
        "low_liquidity": token["liquidity"] < 100000,
        "high_concentration": (token.get("top10_holdings") or 0) > 50,
        "few_holders": (token.get("holders") or 0) < 1000,
        "new_token": (datetime.now().timestamp() - token["created_at"]) < 86400,
    }
    
    return jsonify({
        "token": token,
        "risk_factors": risk_factors,
        "timestamp": datetime.now().isoformat()
    })


@app.post("/api/scanner/alert/<mint>")
def alert_rugpull(mint):
    """Alert when rugpull detected for a token"""
    token = next((t for t in tokens_scanned if t["mint"] == mint), None)
    if not token:
        return jsonify({"error": "Token not found"}), 404
    
    return jsonify({
        "status": "alert_sent",
        "token": token["symbol"],
        "mint": mint,
        "rugpull_probability": token["rugpull_probability"],
        "action": "SELL_ALL" if token["rugpull_probability"] > 0.5 else "HOLD",
        "timestamp": datetime.now().isoformat()
    })


@app.get("/api/autotrading/status")
def autotrading_status():
    """Get auto-trading status"""
    return jsonify({
        "active": auto_trading["active"],
        "trades_executed": auto_trading["trades_executed"],
        "candidate": auto_trading.get("candidate"),
    })


@app.get("/api/wallet/balance")
def wallet_balance():
    """Get SOL balance for a wallet address"""
    address = request.args.get('address')
    if not address:
        return jsonify({"error": "address parameter required"}), 400
    
    try:
        # Query Solana RPC for wallet balance
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }
        response = requests.post(SOLANA_RPC, json=payload, timeout=5)
        data = response.json()
        
        if "result" in data and data["result"]:
            balance_lamports = data["result"]["value"]
            balance_sol = balance_lamports / 1e9
            return jsonify({
                "address": address,
                "balance": round(balance_sol, 4),
                "lamports": balance_lamports,
                "source": "live"
            })
        else:
                raise RuntimeError("RPC response did not contain a balance")
    except Exception as e:
        print(f"Error fetching balance: {e}")
        return jsonify({
            "address": address,
                "error": "Could not fetch wallet balance from Solana RPC",
                "source": "unavailable",
            }), 502


@app.get("/api/trading/requirements")
def trading_requirements():
    return jsonify({
        "minimum_trade_sol": MIN_TRADE_SOL,
        "minimum_start_sol": MIN_START_BALANCE_SOL,
    })


@app.post("/api/trade/quote")
def trade_quote():
    """Return a Jupiter quote; the connected wallet remains the signer."""
    payload = request.get_json(silent=True) or {}
    input_mint = payload.get("input_mint")
    output_mint = payload.get("output_mint")
    amount = payload.get("amount")
    if not input_mint or not output_mint or not isinstance(amount, int) or amount <= 0:
        return jsonify({"error": "input_mint, output_mint, and positive integer amount are required"}), 400
    if input_mint == WSOL_MINT:
        amount_sol = amount / 1e9
        if amount_sol < MIN_TRADE_SOL:
            return jsonify({"error": f"Minimum BUY amount is {MIN_TRADE_SOL:.6f} SOL"}), 400
    try:
        response = requests.get(
            f"{JUPITER_API}/quote",
            params={
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": amount,
                "slippageBps": SLIPPAGE_BPS,
            },
            timeout=15,
        )
        response.raise_for_status()
        quote = response.json()
        route_ok, route_reason = validate_quote_routes(quote)
        if not route_ok:
            return jsonify({"error": f"DEX allowlist rejected quote: {route_reason}"}), 403
        return jsonify(quote)
    except requests.RequestException as error:
        return jsonify({"error": f"Jupiter quote unavailable: {error}"}), 502


@app.post("/api/trade/swap-transaction")
def swap_transaction():
    """Build an unsigned Jupiter transaction for a browser wallet to sign."""
    payload = request.get_json(silent=True) or {}
    quote = payload.get("quote")
    wallet = payload.get("wallet")
    if not quote or not wallet:
        return jsonify({"error": "quote and wallet are required"}), 400
    route_ok, route_reason = validate_quote_routes(quote)
    if not route_ok:
        return jsonify({"error": f"DEX allowlist rejected quote: {route_reason}"}), 403
    try:
        response = requests.post(
            f"{JUPITER_API}/swap",
            json={
                "quoteResponse": quote,
                "userPublicKey": wallet,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
            },
            timeout=20,
        )
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as error:
        return jsonify({"error": f"Could not build swap transaction: {error}"}), 502


@app.get("/api/dashboard")
def dashboard():
    wallet = request.args.get("wallet")
    if wallet:
        position_filter = "owner_wallet=?"
        position_params = (wallet,)
    else:
        position_filter = "1=0"
        position_params = ()
    positions = query(
        """SELECT id, mint, source, opened_at, entry_price_sol, token_amount,
                  peak_price_sol, trigger_active, buy_signature
           FROM positions WHERE status='OPEN' AND """ + position_filter + " ORDER BY opened_at DESC",
        position_params,
    )
    closed = query(
        """SELECT mint, source, opened_at, entry_price_sol, peak_price_sol,
                  close_reason, sell_signature, closed_at
           FROM positions WHERE status='CLOSED' AND """ + position_filter + " ORDER BY closed_at DESC LIMIT 12",
        position_params,
    )
    skips = query(
        """SELECT ts, mint, source, reason FROM skipped_tokens
           ORDER BY ts DESC LIMIT 12"""
    )
    counts = query(
           f"""SELECT
               (SELECT COUNT(*) FROM positions WHERE status='OPEN' AND {position_filter}) AS open_count,
               (SELECT COUNT(*) FROM positions WHERE status='CLOSED' AND {position_filter}) AS closed_count,
               (SELECT COUNT(*) FROM skipped_tokens) AS skip_count""",
           position_params + position_params,
    )
    
    # Provide mock data if database is empty/missing
    if not counts:
        counts = [{"open_count": 0, "closed_count": 0, "skip_count": 0}]
    
    return jsonify({
        "positions": positions or [],
        "closed": closed or [],
        "skips": skips or [],
        "counts": counts[0] if counts else {"open_count": 0, "closed_count": 0, "skip_count": 0}
    })


if __name__ == '__main__':
    host = env_value("API_HOST", "127.0.0.1")
    port = int(env_value("API_PORT", "8000"))
    debug = env_value("API_DEBUG", "false").lower() == "true"
    app.run(host=host, port=port, debug=debug)
