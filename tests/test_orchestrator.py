import json

import pytest

from app.config import PROFILES
from app.llm import LLMUnavailable
from app.orchestrator import MAX_TOOL_ROUNDS, handle_message
from app.prompts import INTERNAL_CODE_CANARY, INTERNAL_RULE_CANARY, build_messages
from app.rag import Chunk
from tests.conftest import refunds
from tests.fakes import text, tool_call

VULN = PROFILES["vulnerable"]


def test_responde_sin_herramientas(deps, alice):
    deps.llm.script([text("Tenés 30 días para devolver")])
    r = handle_message("¿Cuántos días tengo para devolver?", [], alice, deps, VULN, seed=1)
    assert r.reply == "Tenés 30 días para devolver"
    assert r.tool_log == [] and r.pending_confirmation is None
    assert len(deps.llm.calls) == 1


def test_ofrece_las_tres_herramientas(deps, alice):
    deps.llm.script([text("ok")])
    handle_message("hola", [], alice, deps, VULN, seed=1)
    assert {t["function"]["name"] for t in deps.llm.calls[0]["tools"]} == {"get_order", "issue_refund", "send_email"}


def test_ejecuta_herramienta_y_devuelve_resultado_al_modelo(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=1001), text("Tu pedido está en camino")])
    r = handle_message("¿Dónde está mi pedido?", [], alice, deps, VULN, seed=1)
    assert r.reply == "Tu pedido está en camino"
    assert any(m["role"] == "tool" for m in deps.llm.calls[1]["messages"])
    assert r.tool_log[0].call.name == "get_order" and r.tool_log[0].result.ok


def test_resultado_de_herramienta_va_como_json(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=1001), text("ok")])
    handle_message("x", [], alice, deps, VULN, seed=1)
    tool_msg = next(m for m in deps.llm.calls[1]["messages"] if m["role"] == "tool")
    assert tool_msg["tool_name"] == "get_order"
    assert json.loads(tool_msg["content"])["data"]["order_id"] == 1001


def test_mensaje_del_asistente_con_tool_calls_precede_al_resultado(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=1001), text("ok")])
    handle_message("x", [], alice, deps, VULN, seed=1)
    msgs = deps.llm.calls[1]["messages"]
    i = next(i for i, m in enumerate(msgs) if m["role"] == "tool")
    assert msgs[i - 1]["role"] == "assistant" and msgs[i - 1]["tool_calls"][0]["function"]["name"] == "get_order"


def test_ejecuta_efectos_reales(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("Listo")])
    handle_message("Quiero 10 de reembolso", [], alice, deps, VULN, seed=1)
    assert refunds(deps.conn, 1001)[0]["status"] == "approved"


def test_corta_el_ciclo_de_herramientas(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=1001)] * 10)
    r = handle_message("hola", [], alice, deps, VULN, seed=1)
    assert len(deps.llm.calls) <= MAX_TOOL_ROUNDS + 1
    assert r.reply


def test_ultima_ronda_no_ofrece_herramientas(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=1001)] * 10)
    handle_message("hola", [], alice, deps, VULN, seed=1)
    assert deps.llm.calls[-1]["tools"] == []


def test_herramienta_inexistente_no_rompe(deps, alice):
    deps.llm.script([tool_call("no_existe"), text("Perdón")])
    assert handle_message("x", [], alice, deps, VULN, seed=1).reply == "Perdón"


def test_argumentos_invalidos_no_rompen(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id="1 OR 1=1", amount=-1), text("No pude")])
    r = handle_message("x", [], alice, deps, VULN, seed=1)
    assert r.reply == "No pude" and r.tool_log[0].result.error == "invalid_arguments"


def test_respuesta_vacia_tiene_texto_de_respaldo(deps, alice):
    deps.llm.script([text("")])
    assert handle_message("x", [], alice, deps, VULN, seed=1).reply


def test_propaga_semilla(deps, alice):
    deps.llm.script([text("ok")])
    handle_message("x", [], alice, deps, VULN, seed=42)
    assert deps.llm.calls[0]["seed"] == 42


def test_llm_caido_propaga_error(deps, alice):
    deps.llm.fail_with(LLMUnavailable())
    with pytest.raises(LLMUnavailable):
        handle_message("x", [], alice, deps, VULN, seed=1)


def test_incluye_historial_y_mensaje(deps, alice):
    deps.llm.script([text("ok")])
    hist = [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "¡Hola!"}]
    handle_message("¿y mi pedido?", hist, alice, deps, VULN, seed=1)
    msgs = deps.llm.calls[0]["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[1:] == hist + [{"role": "user", "content": "¿y mi pedido?"}]


def test_no_modifica_el_historial_recibido(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=1001), text("ok")])
    hist = []
    handle_message("x", hist, alice, deps, VULN, seed=1)
    assert hist == []


def test_recupera_faq_para_el_contexto(deps, alice):
    deps.llm.script([text("ok")])
    handle_message("¿Cuál es la política de devoluciones?", [], alice, deps, VULN, seed=1)
    assert "30 días" in deps.llm.calls[0]["messages"][0]["content"]


def test_vulnerable_mezcla_contexto_en_system_prompt(alice):
    msgs = build_messages([], "hola", [Chunk("reseña X", "review", "r1")], alice, VULN)
    assert "reseña X" in msgs[0]["content"] and INTERNAL_CODE_CANARY in msgs[0]["content"]


def test_vulnerable_incluye_regla_interna_y_reglas_de_negocio(alice):
    system = build_messages([], "hola", [], alice, VULN)[0]["content"]
    assert INTERNAL_RULE_CANARY in system and "30 días" in system


def test_system_prompt_identifica_al_cliente(alice):
    assert "alice" in build_messages([], "hola", [], alice, VULN)[0]["content"]
