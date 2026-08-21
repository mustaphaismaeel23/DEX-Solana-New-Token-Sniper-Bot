# DEX Solana New-Token Sniper Bot

Watches Pump.fun launches and PumpSwap migrations, runs safety checks
on each candidate, buys the ones that pass, then exits automatically using a
profit-trigger + trailing stop (with a hard stop-loss and max-hold timeout
underneath it).

**This is meaningfully riskier than copy-trading a known wallet.** Most
brand-new tokens go to zero. Read the Limitations section before funding it
with anything you'd miss.

## Client Overview

This system is an automated monitoring and trading tool for newly launched
Solana tokens. It continuously watches selected token launch and liquidity
venues, evaluates new opportunities against configurable safety rules, and can
execute trades without requiring manual intervention for every token.

The workflow is:

1. **Discover** — detect Pump.fun launches and PumpSwap migrations only.
2. **Evaluate** — check token permissions, holder concentration, liquidity,
  market activity, public project signals, and token age.
3. **Enter** — buy only candidates that pass the ordered security, data,
  risk-score, circuit-breaker, slippage, and final-validation gates. Risk
  score also reduces position size; it never increases configured limits.
4. **Manage** — monitor open positions and automatically take partial profits
  or exit using a hard stop-loss, trailing stop, or maximum holding period.
5. **Review** — record trades, exits, and rejected candidates in the database
  and expose activity through the read-only dashboard.

The system is designed to make decisions consistently and reduce the need for
constant manual monitoring. It does not predict which token will succeed,
remove the risk of scams or market volatility, or guarantee profits. Dry-run
mode is available so the strategy can be observed and tuned before any real
funds are used.

## How it works

**Scanning** (`pump_scanner.py`)
- Pump.fun: subscribes to PumpPortal's free public websocket for new token
  creation events — real-time, no API key.
- PumpSwap: subscribes to PumpPortal migration events and then validates the
  live DexScreener pair as PumpSwap before an entry.
- Any source outside the centralized allowlist is rejected.

**Filtering** (`safety_checks.py`) — a candidate must pass ALL of:
1. Mint authority renounced (creator can't mint unlimited new supply)
2. Freeze authority renounced (creator can't freeze your tokens)
3. Top holder owns less than `MAX_TOP_HOLDER_PCT`% of supply
4. Liquidity (DexScreener) above `MIN_LIQUIDITY_USD`
5. Utility evidence score above `MIN_UTILITY_SCORE`, based on public website/social metadata, 24h volume, and volume/liquidity turnover
6. Token age between `MIN_TOKEN_AGE_SECONDS` and `MAX_TOKEN_AGE_SECONDS`
  (waits for six hours of proof and skips stale candidates after 24 hours)

The utility score is an evidence filter, not a promise of product quality or
profit. It deliberately rejects tokens when public market/project data is
missing. Adjust `REQUIRE_UTILITY_SIGNALS`, `MIN_UTILITY_SCORE`,
`MIN_24H_VOLUME_USD`, and `MIN_VOLUME_LIQUIDITY_RATIO` only after reviewing
dry-run results.

**Buying** (`buyer.py`) — fixed `BUY_SIZE_SOL` per token, capped by
`MAX_CONCURRENT_POSITIONS` open positions at once. The entry pipeline fails
closed if normalized `risk_data` is absent or invalid. Scanner/security
adapters must provide the nine `categoryScores` fields used by
`risk_engine.py`, plus available hard-reject fields such as `honeypot`,
`sell_simulation_passed`, `dangerous_permissions`, `tax_pct`, and
`price_impact_pct`; unavailable critical data is rejected rather than guessed.

The independent circuit breaker has `NORMAL`, `PAUSED`, and
`EMERGENCY_STOP` states. Paused and emergency states block new entries while
existing positions continue through the position manager. Emergency stop
requires manual reset by default. State, daily loss, and consecutive losses
are persisted in SQLite. Set `CIRCUIT_BREAKER_RESET_TOKEN` and send it as the
`X-Circuit-Breaker-Token` header to `POST /api/circuit-breaker/reset`; status
is available at `GET /api/circuit-breaker`.

**Exiting** (`position_manager.py`) — checked every
`POSITION_CHECK_INTERVAL_SECONDS`:
- **Hard stop-loss**: sell immediately if price drops `HARD_STOP_LOSS_PCT`%
  below entry, any time.
- **Profit trigger + trailing stop**: once price rises `PROFIT_TRIGGER_PCT`%
  above entry, the trailing stop arms. From there it tracks the peak price
  and sells if price pulls back `TRAIL_PCT`% from that peak — locking in
  gains without capping the upside while it keeps running.
- **Max hold timeout**: force-sells after `MAX_HOLD_SECONDS` regardless, so
  dead/illiquid positions don't sit forever.

Staged profit targets are enabled: 50% of the original token amount is sold
at 2x, 25% of the original amount at 5x, and 80% of the remaining amount at
10x. This leaves a small moonbag while the hard stop and trailing stop remain
active for the balance.

Price is read live from a small Jupiter quote (not a market-data API), so it
reflects what you could actually transact at right now, pool depth included.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

- **RPC_URL / HELIUS_API_KEY** — free key at https://helius.dev.
- **WALLET_PRIVATE_KEY** — required only for autonomous live trading. It is a
  *dedicated* wallet, separate from anything else you hold. In `DRY_RUN=true`
  mode it may be empty and the bot creates a temporary in-memory wallet. The
  browser wallet connected in the dashboard is a separate signer for manual
  dashboard trades. Generate the bot wallet key with:
  ```bash
  python3 -c "from solders.keypair import Keypair; k=Keypair(); print('pubkey:',k.pubkey()); print('privkey:', str(k))"
  ```
  Fund it with only what you're fully prepared to lose.
- **TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID** — optional, via @BotFather.
- **PUMPSWAP_PROGRAM_ID** — required for the on-chain PumpSwap pool-owner
  adapter. Leave live trading disabled until this is verified against the
  current PumpSwap deployment.

## Dashboard

The read-only operations dashboard shows dry-run status, open exposure,
recent exits, and skipped-token filter activity from SQLite. Run it in a
second terminal while the bot is running:

```bash
python3 -m streamlit run dashboard.py
```

Open http://localhost:8501. The dashboard does not require wallet credentials
to display database activity, and it never submits trades.

## Running

```bash
python3 main.py
```

**Start with `DRY_RUN=true` and let it run for a day or two.** Watch how
many candidates it finds and how many pass the safety filters. Only flip to
live once you've seen it behave sensibly in dry run.

## Deployment

The React dashboard can be deployed to Vercel. In the Vercel project, set
**Root Directory** to `frontend`; `frontend/vercel.json` configures `npm ci`,
`npm run build`, and the `dist` output. Add this public frontend variable:

```env
VITE_API_URL=https://your-backend-domain.example
```

Run the Python bot and Flask API on a persistent host such as a VPS, Render,
Railway, or Fly.io. They require long-running WebSocket connections, position
monitoring, SQLite state, and access to private trading credentials. Never put
`WALLET_PRIVATE_KEY`, RPC credentials, or API secrets in Vercel frontend
variables.

Same pattern as any long-running bot — a small VPS with `systemd`:

```ini
# /etc/systemd/system/sniper-bot.service
[Unit]
Description=Solana Sniper Bot
After=network.target

[Service]
WorkingDirectory=/opt/sniper-bot
ExecStart=/opt/sniper-bot/venv/bin/python3 main.py
Restart=always
RestartSec=5
User=sniper

[Install]
WantedBy=multi-user.target
```

## Tuning

| Setting | What it does |
|---|---|
| `BUY_SIZE_SOL` | Fixed SOL spent per snipe |
| `MAX_CONCURRENT_POSITIONS` | Caps total exposure at once |
| `MIN_LIQUIDITY_USD` | Liquidity floor to even consider a token |
| `MAX_TOP_HOLDER_PCT` | Rejects tokens with a whale concentration risk |
| `PROFIT_TRIGGER_PCT` | Gain % that arms the trailing stop |
| `TRAIL_PCT` | Pullback % from peak that triggers the sell once armed |
| `HARD_STOP_LOSS_PCT` | Loss % that force-sells regardless of the trailing logic |
| `MAX_HOLD_SECONDS` | Force-exit timeout for dead positions |
| `SLIPPAGE_BPS` | Wider than the copy-trade bot by default (500 = 5%) since new-token pools are thin and volatile |
| `MIN_UTILITY_SCORE` | Minimum public utility-evidence score required before buying |
| `MIN_24H_VOLUME_USD` | Minimum DexScreener 24-hour volume used by the utility score |
| `MIN_VOLUME_LIQUIDITY_RATIO` | Minimum 24-hour volume divided by liquidity used by the utility score |
| `MIN_RISK_SCORE` | Minimum weighted risk score (default 65) |
| `MAX_POSITION_SIZE_MULTIPLIER` | Absolute cap applied after risk-based sizing |
| `DAILY_LOSS_THRESHOLD_SOL` | Loss threshold that triggers emergency stop |
| `MAX_CONSECUTIVE_LOSSES` | Consecutive losses that pause new entries |
| `CIRCUIT_BREAKER_COOLDOWN_SECONDS` | Recovery cooldown for a pause |
| `CIRCUIT_BREAKER_MANUAL_RESET` | Require manual recovery from emergency stop |

## Limitations — read before funding real money

- **Safety checks reduce risk, they don't eliminate it.** Renounced
  authorities and holder concentration catch the laziest rugs. They don't
  catch: LP that isn't locked/burned (can still be pulled), coordinated
  wash trading to fake volume, or a dev simply dumping their allocation
  slowly. There is no filter here that makes new-token sniping safe.
- **Live entries remain fail-closed until unavailable security evidence is
  supplied.** The current public APIs do not prove LP locking or perform a
  sell simulation. Supply `categoryScores.liquidity_security` and
  `sell_simulation_passed=true` through the `risk_data` adapter before live
  buys can be approved.
- **Sell simulation requires token inventory.** Configure a provider or probe
  workflow that supplies `sell_simulation_token_amount`; a quote alone is not
  treated as a successful sell simulation.
- **PumpPortal migration detection is best-effort.** Its event names and
  payload fields can change — verify migration events during dry run.
- **Price/liquidity can vanish between detection and your buy landing.**
  Sniping is a latency race; by design you're often buying within seconds of
  launch, which is also when it's most likely to be a scam.
- **DexScreener may not have indexed a pump.fun token yet** at launch,
  which means the liquidity check will correctly skip it as "not liquid
  yet" — you'll miss some legitimate early ones. That's the safer failure
  mode versus removing the check.
- **Not financial advice, not audited.** Test thoroughly in `DRY_RUN`, size
  positions small, and monitor actively — especially in the first few days.
