import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent
ENV = dotenv_values(ROOT / ".env")
DB_PATH = ROOT / ENV.get("DB_PATH", "sniper.db")

st.set_page_config(
    page_title="Sniper Control Room",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap');
    :root { --ink:#162329; --muted:#617178; --line:#d9e3e3; --mint:#d9f5e8; --mint-strong:#1b8a63; --coral:#e87961; --paper:#f7faf8; }
    .stApp { background: var(--paper); color: var(--ink); }
    [data-testid="stSidebar"] { background:#162329; }
    [data-testid="stSidebar"] * { color:#e9f4ef !important; }
    h1,h2,h3,p,div,span { font-family:'Space Grotesk', sans-serif; }
    code, .mono { font-family:'DM Mono', monospace !important; }
    h1 { letter-spacing:-1px; font-size:2.4rem !important; margin-bottom:0; }
    .eyebrow { color:var(--mint-strong); font-family:'DM Mono',monospace; font-size:.72rem; letter-spacing:.12em; text-transform:uppercase; font-weight:500; }
    .subtle { color:var(--muted); font-size:.92rem; }
    .status { display:inline-flex; align-items:center; gap:.45rem; padding:.38rem .7rem; border:1px solid var(--line); border-radius:999px; background:white; font-family:'DM Mono',monospace; font-size:.72rem; }
    .dot { width:8px; height:8px; border-radius:50%; display:inline-block; background:var(--mint-strong); }
    .dot.off { background:var(--coral); }
    .panel { border:1px solid var(--line); background:#fff; padding:1.1rem 1.2rem; border-radius:8px; }
    .mint { background:var(--mint); border-color:#bde8d5; }
    .stButton button { border-radius:5px; border:1px solid #a8c8bc; background:#fff; color:var(--ink); font-family:'Space Grotesk',sans-serif; }
    [data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:8px; padding:1rem; }
    [data-testid="stMetricLabel"] { color:var(--muted); }
    [data-testid="stMetricValue"] { color:var(--ink); font-family:'DM Mono',monospace; }
    </style>
    """,
    unsafe_allow_html=True,
)


def format_time(value):
    if not value:
        return "-"
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%d %b %H:%M UTC")


def shorten(value, length=16):
    if not value:
        return "-"
    return f"{value[:length]}...{value[-6:]}" if len(value) > length + 6 else value


def query(sql, params=()):
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


@st.cache_data(ttl=5)
def load_dashboard_data():
    positions = query(
        """SELECT id, mint, source, opened_at, entry_price_sol, token_amount,
                  peak_price_sol, trigger_active, buy_signature
           FROM positions WHERE status='OPEN' ORDER BY opened_at DESC"""
    )
    closed = query(
        """SELECT mint, source, opened_at, entry_price_sol, peak_price_sol,
                  close_reason, sell_signature, closed_at
           FROM positions WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT 12"""
    )
    skips = query(
        """SELECT ts, mint, source, reason FROM skipped_tokens
           ORDER BY ts DESC LIMIT 12"""
    )
    counts = query(
        """SELECT
             (SELECT COUNT(*) FROM positions WHERE status='OPEN') AS open_count,
             (SELECT COUNT(*) FROM positions WHERE status='CLOSED') AS closed_count,
             (SELECT COUNT(*) FROM skipped_tokens) AS skip_count"""
    )
    return positions, closed, skips, counts[0] if counts else {"open_count": 0, "closed_count": 0, "skip_count": 0}


positions, closed, skips, counts = load_dashboard_data()
db_ready = DB_PATH.exists()
dry_run = str(ENV.get("DRY_RUN", "true")).lower() == "true"

with st.sidebar:
    st.markdown('<div class="eyebrow">SNIPER / OPS</div>', unsafe_allow_html=True)
    st.markdown("## Control room")
    st.caption("Read-only telemetry for the trading process.")
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.markdown("**Runtime**")
    st.write(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    st.write(f"Database: `{DB_PATH.name}`")
    st.write(f"Last file update: {datetime.fromtimestamp(DB_PATH.stat().st_mtime, tz=timezone.utc).strftime('%H:%M:%S UTC') if db_ready else 'not created'}")
    st.divider()
    st.markdown("**Strategy guardrails**")
    st.write(f"Buy size: `{ENV.get('BUY_SIZE_SOL', '0.05')} SOL`")
    st.write(f"Max positions: `{ENV.get('MAX_CONCURRENT_POSITIONS', '3')}`")
    st.write(f"Stop loss: `-{ENV.get('HARD_STOP_LOSS_PCT', '35')}%`")
    st.write(f"Trail: `{ENV.get('TRAIL_PCT', '20')}%`")

st.markdown('<div class="eyebrow">LIVE OPERATIONS / SOLANA</div>', unsafe_allow_html=True)
header_left, header_right = st.columns([3, 1])
with header_left:
    st.title("Sniper Control Room")
    st.markdown('<p class="subtle">A quiet view of exposure, exits, and the filters protecting the wallet.</p>', unsafe_allow_html=True)
with header_right:
    label = "DRY RUN" if dry_run else "LIVE TRADING"
    dot_class = "" if dry_run else "off"
    st.markdown(f'<div class="status"><span class="dot {dot_class}"></span>{label}</div>', unsafe_allow_html=True)

st.write("")
metric_cols = st.columns(4)
metric_cols[0].metric("Open positions", counts["open_count"])
metric_cols[1].metric("Closed positions", counts["closed_count"])
metric_cols[2].metric("Skipped tokens", counts["skip_count"])
metric_cols[3].metric("Database", "READY" if db_ready else "WAITING")

st.write("")
if not db_ready:
    st.markdown('<div class="panel mint"><b>Waiting for the bot</b><br><span class="subtle">The SQLite database will appear after the bot starts and initializes its tables.</span></div>', unsafe_allow_html=True)

st.markdown("### Exposure")
if positions:
    rows = []
    for position in positions:
        rows.append({
            "Token": shorten(position["mint"]),
            "Source": position["source"].upper(),
            "Opened": format_time(position["opened_at"]),
            "Entry (SOL)": f'{position["entry_price_sol"]:.10f}',
            "Peak (SOL)": f'{position["peak_price_sol"]:.10f}',
            "Trail": "ARMED" if position["trigger_active"] else "WATCHING",
            "Signature": shorten(position["buy_signature"]),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.markdown('<div class="panel"><b>No open positions</b><br><span class="subtle">Exposure will appear here after a candidate passes every safety check.</span></div>', unsafe_allow_html=True)

left, right = st.columns(2)
with left:
    st.markdown("### Recent exits")
    if closed:
        rows = [{
            "Token": shorten(row["mint"]),
            "Source": row["source"].upper(),
            "Closed": format_time(row["closed_at"]),
            "Reason": row["close_reason"] or "-",
        } for row in closed]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="panel"><span class="subtle">No exits recorded yet.</span></div>', unsafe_allow_html=True)

with right:
    st.markdown("### Filter activity")
    if skips:
        rows = [{
            "Token": shorten(row["mint"]),
            "Source": row["source"].upper(),
            "Reason": row["reason"],
            "When": format_time(row["ts"]),
        } for row in skips]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="panel"><span class="subtle">No skipped candidates recorded yet.</span></div>', unsafe_allow_html=True)

st.caption("Prices and wallet balance are intentionally not estimated here. The current database stores entry and peak prices only; live valuation belongs in the bot telemetry layer.")
