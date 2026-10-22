"""Order state, kept server-side so cart tokens and keys never pass through the model.

status: draft -> link_sent -> paid -> finalizing -> finalized
        (flagged = held for a human; unconfirmed = finalized in Bumpa but not yet seen in the order list)
"""
import contextlib
import json
import os
import sqlite3
import time

DB_PATH = os.getenv("STORE_PATH", "orders.db")


@contextlib.contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        checkout_id TEXT PRIMARY KEY,
        cart_token TEXT,
        customer TEXT,
        items TEXT,
        expected_total REAL,
        payment_reference TEXT,
        payment_url TEXT,
        status TEXT,
        bumpa_order_id TEXT,
        imei TEXT,
        created_at REAL,
        updated_at REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS flags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        checkout_id TEXT,
        reason TEXT,
        details TEXT,
        created_at REAL)""")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save(checkout_id, **fields):
    now = time.time()
    for k in ("customer", "items"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    with _db() as c:
        exists = c.execute("SELECT 1 FROM orders WHERE checkout_id=?", (checkout_id,)).fetchone()
        if exists:
            sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=?"
            c.execute(f"UPDATE orders SET {sets} WHERE checkout_id=?", (*fields.values(), now, checkout_id))
        else:
            cols = ", ".join(["checkout_id", *fields, "created_at", "updated_at"])
            marks = ", ".join("?" * (len(fields) + 3))
            c.execute(f"INSERT INTO orders ({cols}) VALUES ({marks})", (checkout_id, *fields.values(), now, now))


def get(checkout_id):
    with _db() as c:
        row = c.execute("SELECT * FROM orders WHERE checkout_id=?", (checkout_id,)).fetchone()
    return dict(row) if row else None


def add_flag(checkout_id, reason, details):
    with _db() as c:
        c.execute("INSERT INTO flags (checkout_id, reason, details, created_at) VALUES (?,?,?,?)",
                  (checkout_id, reason, details, time.time()))


def since(ts):
    with _db() as c:
        orders = [dict(r) for r in c.execute("SELECT * FROM orders WHERE created_at>=?", (ts,))]
        flags = [dict(r) for r in c.execute("SELECT * FROM flags WHERE created_at>=?", (ts,))]
    return orders, flags


def claim(checkout_id, from_statuses, to_status):
    """Atomically move an order to to_status only if it is currently in from_statuses.
    Returns True for exactly one caller, so concurrent finalize calls can't both proceed."""
    marks = ", ".join("?" * len(from_statuses))
    with _db() as c:
        cur = c.execute(f"UPDATE orders SET status=?, updated_at=? WHERE checkout_id=? AND status IN ({marks})",
                        (to_status, time.time(), checkout_id, *from_statuses))
        return cur.rowcount == 1


def imei_used(imei, exclude_checkout_id):
    with _db() as c:
        row = c.execute("SELECT checkout_id FROM orders WHERE imei=? AND checkout_id!=?",
                        (imei, exclude_checkout_id)).fetchone()
    return row["checkout_id"] if row else None
