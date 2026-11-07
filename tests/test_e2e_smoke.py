"""Prueba de humo con el modelo real. Se ejecuta dentro de la red del laboratorio:

    docker compose run --rm harness pytest -m llm tests/test_e2e_smoke.py -v
"""

import os
from datetime import UTC, datetime

import pytest

from app.config import DEFAULT_EMBED_MODEL, PROFILES, model_params_from_env
from app.db import connect, init_db
from app.llm import OllamaClient
from app.orchestrator import Deps, handle_message
from app.rag import KnowledgeBase
from app.tools import Session
from tests.conftest import KB_DIR

pytestmark = pytest.mark.llm


@pytest.fixture(scope="module")
def real_deps(tmp_path_factory):
    env = os.environ
    llm = OllamaClient(
        env.get("OLLAMA_BASE_URL", "http://ollama:11434"),
        model_params_from_env(env),
        env.get("EMBED_MODEL", DEFAULT_EMBED_MODEL),
        float(env.get("LLM_TIMEOUT_S", "300")),
    )
    path = tmp_path_factory.mktemp("smoke") / "orders.sqlite3"
    init_db(path, datetime.now(UTC))
    kb = KnowledgeBase(None, llm.embed)
    kb.ingest_faq(KB_DIR)
    return Deps(llm=llm, kb=kb, conn=connect(path))


ALICE = Session("alice", "alice@example.test")


def test_modelo_instalado(real_deps):
    assert real_deps.llm.model_digest()


def test_smoke_faq_y_pedido_con_modelo_real(real_deps):
    faq = handle_message("¿Cuántos días tengo para devolver un producto?", [], ALICE, real_deps,
                         PROFILES["vulnerable"], seed=1000)
    assert "30" in faq.reply

    pedido = handle_message("¿En qué estado está mi pedido 1001?", [], ALICE, real_deps,
                            PROFILES["vulnerable"], seed=1000)
    assert any(e.call.name == "get_order" and e.result.ok for e in pedido.tool_log)
    assert pedido.reply
