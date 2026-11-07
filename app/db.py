"""Base de pedidos (SQLite) con datos ficticios.

Las fechas se calculan desde `now`, así los pedidos siempre tienen la misma antigüedad
relativa y los tests no "vencen". Todas las consultas son parametrizadas: la inyección
SQL no es parte de este laboratorio.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    address       TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    created_at  TEXT NOT NULL,
    total       REAL NOT NULL,
    status      TEXT NOT NULL,
    items       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refunds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     INTEGER NOT NULL REFERENCES orders(id),
    requested_by TEXT NOT NULL,
    amount       REAL NOT NULL,
    status       TEXT NOT NULL,   -- approved | pending_confirmation | rejected
    token        TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emails (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    to_addr    TEXT NOT NULL,
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    sent_by    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Credenciales de demostración de clientes ficticios. No son secretos reales.
DEMO_PASSWORDS = {"alice": "alice-demo", "bob": "bob-demo"}

CUSTOMERS = [
    ("alice", "Alice Ficticia", "alice@example.test", "Calle Falsa 123, Córdoba"),
    ("bob", "Bob Inventado", "bob@example.test", "Av. Siempreviva 742, Rosario"),
]

# (id, cliente, días de antigüedad, total, estado, ítems)
ORDERS = [
    (1001, "alice", 5, 100.0, "entregado", "Auriculares inalámbricos"),
    (1002, "alice", 90, 80.0, "entregado", "Mochila urbana"),
    (2001, "bob", 5, 150.0, "entregado", "Teclado mecánico"),
]

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _check_hash(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def verify_password(conn: sqlite3.Connection, customer_id: str, password: str) -> bool:
    row = conn.execute("SELECT password_hash FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        _check_hash(password, _demo_hash("alice"))  # tiempo similar exista o no el cliente
        return False
    return _check_hash(password, row["password_hash"])


@functools.cache
def _demo_hash(customer_id: str) -> str:
    # Se calcula una vez por proceso: PBKDF2 es lento a propósito y los tests crean muchas bases.
    return hash_password(DEMO_PASSWORDS[customer_id])


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path, now: datetime) -> None:
    """Crea el esquema y carga los datos ficticios. Si ya existen, no los duplica."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        with conn:
            conn.executescript(SCHEMA)
            for cid, name, email, address in CUSTOMERS:
                conn.execute(
                    "INSERT OR IGNORE INTO customers (id, name, email, address, password_hash) VALUES (?, ?, ?, ?, ?)",
                    (cid, name, email, address, _demo_hash(cid)),
                )
            for oid, cid, days, total, status, items in ORDERS:
                conn.execute(
                    "INSERT OR IGNORE INTO orders (id, customer_id, created_at, total, status, items) VALUES (?, ?, ?, ?, ?, ?)",
                    (oid, cid, (now - timedelta(days=days)).isoformat(), total, status, items),
                )
    finally:
        conn.close()
