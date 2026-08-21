# DEX TRADE BOT - Quick Start Guide

## Prerequisites
- Python 3.9+
- Node.js 16+
- npm

## ⚡ Start the Application

### Step 1: Install Python Dependencies
```bash
cd "C:\Users\HP\Desktop\bot trade"
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Step 2: Start Backend API (Terminal 1)
```bash
cd "C:\Users\HP\Desktop\bot trade"
venv\Scripts\python.exe backend_api.py
```
You should see:
```
* Serving Flask app 'backend_api'
* Running on http://127.0.0.1:8000
```

### Step 3: Install Frontend Dependencies (Terminal 2)
```bash
cd "C:\Users\HP\Desktop\bot trade\frontend"
npm install
```

### Step 4: Start Frontend Dev Server (Terminal 2)
```bash
npm run dev
```
You should see:
```
VITE v4.5.14  ready in 1247 ms
Local:   http://localhost:5173/
```

### Step 5: Open in Browser
Visit **http://localhost:5173**

## ✅ Troubleshooting

### Error: "Backend unreachable" on dashboard

**Check 1: Backend is running**
- Open Terminal 1 and verify `venv\Scripts\python.exe backend_api.py` is running
- If not, run: `venv\Scripts\python.exe backend_api.py`

**Check 2: Port 8000 is free**
```bash
netstat -ano | findstr :8000
```
If something is using port 8000, kill it or restart your PC.

**Check 3: Firewall**
- Windows Defender Firewall might block Flask
- Add exception for Python in Windows Firewall

**Check 4: Clear browser cache**
- Press Ctrl+Shift+Delete in browser → Clear cache
- Refresh page (Ctrl+R)

### Error: npm: command not found

- Install Node.js from https://nodejs.org/
- Restart terminal after installation

### Error: ModuleNotFoundError in Python

```bash
pip install -r requirements.txt --upgrade
```

## 🎯 Features

- **Dashboard** - Overview of positions and auto-trading status
- **Scanner** - Find low-cap tokens and detect rugpull risks
- **Positions** - Track open and closed trades
- **Alerts** - View trading alerts and skipped tokens
- **Wallet** - Connect Solana wallet to view portfolio

## 🚀 Usage

1. **Connect Wallet** - Click "Connect Wallet" button in navbar
2. **Start Auto-Trading** - Click "▶ START AUTO-TRADE" to begin
3. **Scan Tokens** - Use Scanner tab to find opportunities
4. **Monitor Positions** - Check Positions tab for open trades
5. **View Alerts** - See rugpull alerts in Alerts tab

## 📝 Environment Variables

Edit `.env` file:
```
DB_PATH=sniper.db
DRY_RUN=true
BUY_SIZE_SOL=0.05
MAX_CONCURRENT_POSITIONS=3
ALLOWED_DEXES=pumpfun,pumpswap
CIRCUIT_BREAKER_RESET_TOKEN=change-this-before-live-use
```

## 🔗 API Endpoints

- `GET /api/health` - Health check
- `GET /api/dashboard` - Get dashboard data
- `POST /api/buy` - Trigger buy
- `POST /api/sell` - Trigger sell
- `POST /api/stop` - Stop bot
- `POST /api/autotrading/start` - Start auto-trading
- `POST /api/autotrading/stop` - Stop auto-trading
- `GET /api/scanner/tokens` - List tokens with risk scores
- `GET /api/wallet/balance?address=XXX` - Get wallet balance
