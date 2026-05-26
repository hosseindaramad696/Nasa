import sqlite3
import os
from datetime import datetime

DB_FILE = "bot.db"

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            username     TEXT,
            first_name   TEXT,
            last_name    TEXT,
            language     TEXT,
            coins        INTEGER DEFAULT 0,
            msg_received INTEGER DEFAULT 0,
            msg_sent     INTEGER DEFAULT 0,
            bio          TEXT DEFAULT '',
            lat          REAL,
            lon          REAL,
            location_time TEXT,
            joined_at    TEXT,
            referred_by  INTEGER DEFAULT NULL,
            is_blocked   INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id  INTEGER,
            to_id    INTEGER,
            sent_at  TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER,
            PRIMARY KEY (referrer_id, referred_id)
        )
    """)

    # پرداخت‌های در انتظار تایید
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            amount_toman INTEGER,
            coins       INTEGER,
            status      TEXT DEFAULT 'pending',
            receipt_file_id TEXT,
            created_at  TEXT,
            reviewed_at TEXT
        )
    """)

    conn.commit()
    conn.close()

# ── User ──────────────────────────────────────────────────────────────────────
def upsert_user(user):
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (user_id, username, first_name, last_name, language, joined_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username   = excluded.username,
            first_name = excluded.first_name,
            last_name  = excluded.last_name,
            language   = excluded.language
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        user.last_name or "",
        user.language_code or "",
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row

def get_all_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return rows

def is_blocked(user_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return bool(row and row["is_blocked"])

def set_blocked(user_id: int, blocked: bool):
    conn = get_conn()
    conn.execute("UPDATE users SET is_blocked=? WHERE user_id=?", (int(blocked), user_id))
    conn.commit()
    conn.close()

def get_blocked_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users WHERE is_blocked=1").fetchall()
    conn.close()
    return rows

# ── Coins ─────────────────────────────────────────────────────────────────────
def add_coins(user_id: int, amount: int):
    conn = get_conn()
    conn.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_coins(user_id: int) -> int:
    conn = get_conn()
    row = conn.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row["coins"] if row else 0

# ── Payments ──────────────────────────────────────────────────────────────────
def create_payment(user_id: int, amount_toman: int, coins: int, receipt_file_id: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO payments (user_id, amount_toman, coins, receipt_file_id, created_at) VALUES (?,?,?,?,?)",
        (user_id, amount_toman, coins, receipt_file_id, datetime.now().isoformat())
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid

def get_payment(payment_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    conn.close()
    return row

def confirm_payment(payment_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE payments SET status='confirmed', reviewed_at=? WHERE id=?",
        (datetime.now().isoformat(), payment_id)
    )
    conn.commit()
    conn.close()

def reject_payment(payment_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE payments SET status='rejected', reviewed_at=? WHERE id=?",
        (datetime.now().isoformat(), payment_id)
    )
    conn.commit()
    conn.close()

def get_pending_payments():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM payments WHERE status='pending'").fetchall()
    conn.close()
    return rows

# ── Messages ──────────────────────────────────────────────────────────────────
def log_message(from_id: int, to_id: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (from_id, to_id, sent_at) VALUES (?, ?, ?)",
        (from_id, to_id, datetime.now().isoformat())
    )
    conn.execute("UPDATE users SET msg_received = msg_received + 1 WHERE user_id=?", (to_id,))
    conn.execute("UPDATE users SET msg_sent     = msg_sent     + 1 WHERE user_id=?", (from_id,))
    conn.commit()
    conn.close()

def get_stats():
    conn = get_conn()
    total_users  = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    total_msgs   = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
    today        = datetime.now().strftime("%Y-%m-%d")
    today_msgs   = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE sent_at LIKE ?", (f"{today}%",)
    ).fetchone()["c"]
    blocked      = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_blocked=1").fetchone()["c"]
    pending_pay  = conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='pending'").fetchone()["c"]
    confirmed_pay= conn.execute("SELECT COUNT(*) as c FROM payments WHERE status='confirmed'").fetchone()["c"]
    conn.close()
    return {
        "total_users": total_users, "total_msgs": total_msgs,
        "today_msgs": today_msgs, "blocked": blocked,
        "pending_pay": pending_pay, "confirmed_pay": confirmed_pay
    }

# ── Location ──────────────────────────────────────────────────────────────────
def update_location(user_id: int, lat: float, lon: float):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET lat=?, lon=?, location_time=? WHERE user_id=?",
        (lat, lon, datetime.now().isoformat(), user_id)
    )
    conn.commit()
    conn.close()

def get_nearby_users(lat: float, lon: float, radius_km: float = 50):
    import math
    deg = radius_km / 111.0
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM users WHERE lat IS NOT NULL AND lon IS NOT NULL "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (lat - deg, lat + deg, lon - deg, lon + deg)
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        dlat = r["lat"] - lat
        dlon = r["lon"] - lon
        dist = math.sqrt(dlat**2 + dlon**2) * 111
        results.append((dist, r))
    results.sort(key=lambda x: x[0])
    return results

# ── Referrals ─────────────────────────────────────────────────────────────────
def add_referral(referrer_id: int, referred_id: int) -> bool:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
            (referrer_id, referred_id)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_referral_count(user_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM referrals WHERE referrer_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row["c"] if row else 0

# ── Bio / Search ──────────────────────────────────────────────────────────────
def update_bio(user_id: int, bio: str):
    conn = get_conn()
    conn.execute("UPDATE users SET bio=? WHERE user_id=?", (bio, user_id))
    conn.commit()
    conn.close()

def search_users(query: str):
    conn = get_conn()
    q = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM users WHERE (first_name LIKE ? OR username LIKE ?) AND is_blocked=0",
        (q, q)
    ).fetchall()
    conn.close()
    return rows
