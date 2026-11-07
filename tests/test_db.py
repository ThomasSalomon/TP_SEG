from datetime import timedelta

import pytest

from app.db import DEMO_PASSWORDS, connect, init_db, verify_password
from tests.conftest import NOW


def test_init_db_crea_clientes_y_pedidos(tmp_path):
    path = tmp_path / "x.sqlite3"
    init_db(path, NOW)
    conn = connect(path)
    clientes = {r["id"] for r in conn.execute("SELECT id FROM customers")}
    pedidos = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM orders")}
    assert clientes == {"alice", "bob"}
    assert set(pedidos) == {1001, 1002, 2001}
    assert pedidos[1001]["customer_id"] == "alice" and pedidos[1001]["total"] == 100
    assert pedidos[1002]["customer_id"] == "alice" and pedidos[1002]["total"] == 80
    assert pedidos[2001]["customer_id"] == "bob" and pedidos[2001]["total"] == 150
    conn.close()


@pytest.mark.parametrize("order_id, dias", [(1001, 5), (1002, 90), (2001, 5)])
def test_fechas_relativas_a_now(conn, order_id, dias):
    from datetime import datetime

    creado = datetime.fromisoformat(conn.execute("SELECT created_at FROM orders WHERE id = ?", (order_id,)).fetchone()[0])
    assert NOW - creado == timedelta(days=dias)


def test_tablas_de_efectos_empiezan_vacias(conn):
    assert conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0] == 0


def test_init_db_es_idempotente(db_path):
    init_db(db_path, NOW)
    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
    conn.close()


def test_passwords_guardadas_con_hash(conn):
    guardada = conn.execute("SELECT password_hash FROM customers WHERE id = 'alice'").fetchone()[0]
    assert DEMO_PASSWORDS["alice"] not in guardada
    assert verify_password(conn, "alice", DEMO_PASSWORDS["alice"])
    assert not verify_password(conn, "alice", "otra")
    assert not verify_password(conn, "nadie", "x")
