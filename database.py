import sqlite3
import time
from contextlib import contextmanager
from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mint TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,              -- pumpfun / pumpswap
    opened_at INTEGER NOT NULL,
    entry_price_sol REAL NOT NULL,     -- price per token, in SOL
    token_amount REAL NOT NULL,        -- raw token units held
    peak_price_sol REAL NOT NULL,
    trigger_active INTEGER NOT NULL DEFAULT 0,
    buy_signature TEXT,
    initial_token_amount REAL NOT NULL DEFAULT 0,
    profit_stage INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN / CLOSED
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

CREATE TABLE IF NOT EXISTS position_exits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    stage INTEGER NOT NULL,
    token_amount_raw REAL NOT NULL,
    sol_received REAL,
    sell_signature TEXT,
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    stop_requested INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
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


@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO bot_control (id, stop_requested, updated_at) VALUES (1, 0, ?)",
            (int(time.time()),),
        )
        conn.execute(
            "INSERT OR IGNORE INTO circuit_breaker_state "
            "(id, state, loss_day) VALUES (1, 'NORMAL', ?)",
            (time.strftime("%Y-%m-%d"),),
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(positions)")}
        if "initial_token_amount" not in columns:
            conn.execute("ALTER TABLE positions ADD COLUMN initial_token_amount REAL NOT NULL DEFAULT 0")
            conn.execute("UPDATE positions SET initial_token_amount=token_amount WHERE initial_token_amount=0")
        if "profit_stage" not in columns:
            conn.execute("ALTER TABLE positions ADD COLUMN profit_stage INTEGER NOT NULL DEFAULT 0")


def clear_stop_request():
    with get_conn() as conn:
        conn.execute("UPDATE bot_control SET stop_requested=0, updated_at=? WHERE id=1", (int(time.time()),))


def request_stop():
    with get_conn() as conn:
        conn.execute("UPDATE bot_control SET stop_requested=1, updated_at=? WHERE id=1", (int(time.time()),))


def is_stop_requested() -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT stop_requested FROM bot_control WHERE id=1").fetchone()
        return bool(row and row[0])


def open_position_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()
        return row[0]


def already_seen(mint: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM positions WHERE mint=? "
            "UNION SELECT 1 FROM skipped_tokens WHERE mint=? LIMIT 1",
            (mint, mint),
        ).fetchone()
        return row is not None


def record_skip(mint: str, source: str, reason: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO skipped_tokens (ts, mint, source, reason) VALUES (?,?,?,?)",
            (int(time.time()), mint, source, reason),
        )


def open_position(mint, source, entry_price_sol, token_amount, buy_signature):
    with get_conn() as conn:
        conn.execute(
                """INSERT INTO positions
                    (mint, source, opened_at, entry_price_sol, token_amount, peak_price_sol,
                     buy_signature, initial_token_amount)
                    VALUES (?,?,?,?,?,?,?,?)""",
                (mint, source, int(time.time()), entry_price_sol, token_amount, entry_price_sol,
                 buy_signature, token_amount),
        )


def get_open_positions():
    with get_conn() as conn:
        cols = ["id", "mint", "source", "opened_at", "entry_price_sol", "token_amount",
            "initial_token_amount", "profit_stage", "peak_price_sol", "trigger_active", "buy_signature"]
        rows = conn.execute(f"SELECT {','.join(cols)} FROM positions WHERE status='OPEN'").fetchall()
        return [dict(zip(cols, r)) for r in rows]


def update_position_peak(position_id: int, peak_price_sol: float, trigger_active: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE positions SET peak_price_sol=?, trigger_active=? WHERE id=?",
            (peak_price_sol, int(trigger_active), position_id),
        )


def record_partial_exit(position_id: int, remaining_token_amount: int, stage: int,
                        reason: str, sell_signature: str | None, sol_received: float | None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE positions SET token_amount=?, profit_stage=? WHERE id=?",
            (remaining_token_amount, stage, position_id),
        )
        conn.execute(
            """INSERT INTO position_exits
               (position_id, stage, token_amount_raw, sol_received, sell_signature, reason, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (position_id, stage, remaining_token_amount, sol_received, sell_signature, reason, int(time.time())),
        )


def close_position(position_id: int, reason: str, sell_signature: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE positions SET status='CLOSED', close_reason=?, sell_signature=?, closed_at=? WHERE id=?",
            (reason, sell_signature, int(time.time()), position_id),
        )


def load_circuit_breaker_state() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT state, consecutive_losses, daily_loss_sol, drawdown_pct, "
            "paused_at, last_reason, loss_day FROM circuit_breaker_state WHERE id=1"
        ).fetchone()
        if not row:
            return None
        return dict(zip(("state", "consecutive_losses", "daily_loss_sol", "drawdown_pct",
                         "paused_at", "last_reason", "loss_day"), row))


def save_circuit_breaker_state(state: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO circuit_breaker_state
               (id, state, consecutive_losses, daily_loss_sol, drawdown_pct,
                paused_at, last_reason, loss_day)
               VALUES (1,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET state=excluded.state,
                 consecutive_losses=excluded.consecutive_losses,
                 daily_loss_sol=excluded.daily_loss_sol,
                 drawdown_pct=excluded.drawdown_pct,
                 paused_at=excluded.paused_at,
                 last_reason=excluded.last_reason,
                 loss_day=excluded.loss_day""",
            (state["state"], state["consecutive_losses"], state["daily_loss_sol"],
             state["drawdown_pct"], state["paused_at"], state["last_reason"], state["loss_day"]),
        )
