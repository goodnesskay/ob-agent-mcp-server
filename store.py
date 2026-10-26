"""Order state in Postgres, kept server-side so cart tokens and keys never pass through the model.

status: draft -> link_sent -> paid -> finalizing -> finalized
        (flagged = held for a human; unconfirmed = finalized in Bumpa but not yet seen in the order list)
"""
import contextlib
import json
import os
import time

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    checkout_id TEXT PRIMARY KEY,
    cart_token TEXT,
    customer TEXT,
    items TEXT,
    expected_total DOUBLE PRECISION,
    payment_reference TEXT,
    payment_url TEXT,
    status TEXT,
    bumpa_order_id TEXT,
    imei TEXT,
    created_at DOUBLE PRECISION,
    updated_at DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS flags (
    id BIGSERIAL PRIMARY KEY,
    checkout_id TEXT,
    reason TEXT,
    details TEXT,
    created_at DOUBLE PRECISION);
"""
_ready = False


@contextlib.contextmanager
def _db():
    global _ready
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    with psycopg.connect(url, row_factory=dict_row) as conn:  # commits on success, rolls back on error, then closes
        if not _ready:
            conn.execute(SCHEMA)
            _ready = True
        yield conn


def save(checkout_id, **fields):
    now = time.time()
    for k in ("customer", "items"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    cols = ["checkout_id", *fields, "created_at", "updated_at"]
    sets = ", ".join(f"{k}=EXCLUDED.{k}" for k in [*fields, "updated_at"])
    with _db() as c:  # upsert: created_at is only written on insert
        c.execute(f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                  f"ON CONFLICT (checkout_id) DO UPDATE SET {sets}",
                  (checkout_id, *fields.values(), now, now))


def get(checkout_id):
    with _db() as c:
        return c.execute("SELECT * FROM orders WHERE checkout_id=%s", (checkout_id,)).fetchone()


def add_flag(checkout_id, reason, details):
    with _db() as c:
        c.execute("INSERT INTO flags (checkout_id, reason, details, created_at) VALUES (%s,%s,%s,%s)",
                  (checkout_id, reason, details, time.time()))


def since(ts):
    with _db() as c:
        orders = c.execute("SELECT * FROM orders WHERE created_at>=%s", (ts,)).fetchall()
        flags = c.execute("SELECT * FROM flags WHERE created_at>=%s", (ts,)).fetchall()
    return orders, flags


def claim(checkout_id, from_statuses, to_status):
    """Atomically move an order to to_status only if it is currently in from_statuses.
    Returns True for exactly one caller, so concurrent finalize calls can't both proceed."""
    with _db() as c:
        cur = c.execute("UPDATE orders SET status=%s, updated_at=%s WHERE checkout_id=%s AND status = ANY(%s)",
                        (to_status, time.time(), checkout_id, list(from_statuses)))
        return cur.rowcount == 1


def imei_used(imei, exclude_checkout_id):
    with _db() as c:
        row = c.execute("SELECT checkout_id FROM orders WHERE imei=%s AND checkout_id!=%s",
                        (imei, exclude_checkout_id)).fetchone()
    return row["checkout_id"] if row else None


def find_for_phone(phone, open_only=True, days=7):
    """Newest-first orders for a customer phone (matched on the last 10 digits, so +234 and 0 prefixes agree).
    The model can lose a checkout id between WhatsApp messages; the customer's phone is always in the chat."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    if len(digits) < 7:
        return []
    with _db() as c:
        rows = c.execute("SELECT * FROM orders WHERE created_at>=%s ORDER BY created_at DESC",
                         (time.time() - days * 86400,)).fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["customer"] or "{}").get("phone", "")
        except ValueError:
            continue
        if "".join(ch for ch in p if ch.isdigit())[-10:] == digits and (not open_only or r["status"] != "finalized"):
            out.append(r)
    return out
