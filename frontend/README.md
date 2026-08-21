# DEX TRADE BOT

Professional Solana DEX trading dashboard with wallet integration and automated trading controls.

## Local development

1. Install dependencies

```bash
cd frontend
npm install
```

2. Start dev server

```bash
npm run dev
```

By default the dev server runs at `http://localhost:5173`.

## Features

- **Wallet Connection**: Connect your Solana wallet (Phantom, etc.) to view portfolio and balance
- **Trading Controls**: Buy, Sell, and Stop buttons for quick order execution
- **Live Dashboard**: Real-time position tracking and trading activity
- **DEX Integration**: Automated trading on Pump.fun and PumpSwap

## Backend Setup

Run the Python backend API:

```bash
pip install -r requirements.txt
python backend_api.py
```

The API runs on `http://localhost:8000` and provides:
- `/api/dashboard` — Live trading data
- `/api/buy`, `/api/sell`, `/api/stop` — Trading commands
- `/api/wallet/balance` — Wallet balance queries
