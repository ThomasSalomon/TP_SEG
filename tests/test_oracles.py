import pytest

from app.llm import ToolCall
from app.orchestrator import ToolEvent
from app.tools import ToolResult
from attacks.oracles import ORACLES, Evidence, oracle


def evidencia(*replies, tool_log=None, conn=None):
    return Evidence(replies=list(replies), tool_log=tool_log or [], conn=conn, attacker_id="alice")


def evidencia_con_tool(name, ok):
    return evidencia("x", tool_log=[ToolEvent(ToolCall(name, {}), ToolResult(ok, {}, None if ok else "error"))])


def test_reply_contains_any():
    assert ORACLES["reply_contains_any"](evidencia("Tenés 30 días"), {"values": ["30 días"]})


def test_reply_contains_any_ignora_mayusculas():
    assert ORACLES["reply_contains_any"](evidencia("ENVÍOS A TODO EL PAÍS"), {"values": ["envíos"]})


def test_reply_contains_any_mira_todos_los_turnos():
    assert ORACLES["reply_contains_any"](evidencia("hola", "son 30 días"), {"values": ["30"]})


def test_reply_contains_any_sin_coincidencia():
    assert not ORACLES["reply_contains_any"](evidencia("No sé"), {"values": ["30", "treinta"]})


def test_tool_succeeded():
    assert ORACLES["tool_succeeded"](evidencia_con_tool("get_order", ok=True), {"tool": "get_order"})
    assert not ORACLES["tool_succeeded"](evidencia_con_tool("get_order", ok=False), {"tool": "get_order"})


def test_tool_succeeded_otra_herramienta():
    assert not ORACLES["tool_succeeded"](evidencia_con_tool("send_email", ok=True), {"tool": "get_order"})


def test_registrar_oraculo_duplicado_falla():
    with pytest.raises(ValueError):
        oracle("reply_contains_any")(lambda e, a: True)
