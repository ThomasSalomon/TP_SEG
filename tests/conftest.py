from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.db import connect, init_db
from app.tools import Session

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
KB_DIR = Path(__file__).resolve().parent.parent / "data" / "kb"


@pytest.fixture
def deps(conn):
    from app.orchestrator import Deps
    from app.rag import KnowledgeBase
    from tests.fakes import ScriptedLLM, keyword_embed

    kb = KnowledgeBase(None, keyword_embed)
    kb.ingest_faq(KB_DIR)
    return Deps(llm=ScriptedLLM(), kb=kb, conn=conn)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "orders.sqlite3"
    init_db(path, NOW)
    return path


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def alice():
    return Session(customer_id="alice", email="alice@example.test")


@pytest.fixture
def bob():
    return Session(customer_id="bob", email="bob@example.test")


def refunds(conn, order_id):
    return [dict(r) for r in conn.execute("SELECT * FROM refunds WHERE order_id = ? ORDER BY id", (order_id,))]


def refunds_todos(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM refunds ORDER BY id")]


def emails(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM emails ORDER BY id")]
