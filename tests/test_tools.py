import pytest

from app.config import PROFILES
from app.llm import ToolCall
from app.tools import ALL_TOOLS, TOOL_SCHEMAS, execute_tool
from tests.conftest import emails, refunds, refunds_todos


def test_esquemas_de_las_tres_herramientas():
    assert {s["function"]["name"] for s in TOOL_SCHEMAS} == set(ALL_TOOLS) == {"get_order", "issue_refund", "send_email"}


def test_get_order_devuelve_el_pedido(conn, alice):
    r = execute_tool(ToolCall("get_order", {"order_id": 1001}), alice, conn, PROFILES["vulnerable"])
    assert r.ok and r.data["order_id"] == 1001


def test_get_order_acepta_id_como_texto_numerico(conn, alice):
    r = execute_tool(ToolCall("get_order", {"order_id": "1001"}), alice, conn, PROFILES["vulnerable"])
    assert r.ok and r.data["order_id"] == 1001


def test_get_order_inexistente(conn, alice):
    r = execute_tool(ToolCall("get_order", {"order_id": 9999}), alice, conn, PROFILES["vulnerable"])
    assert not r.ok and r.error == "not_found"


def test_vulnerable_get_order_devuelve_pedido_ajeno_con_datos_personales(conn, alice):
    # VULN-V4: no se controla que el pedido sea del cliente de la sesión
    r = execute_tool(ToolCall("get_order", {"order_id": 2001}), alice, conn, PROFILES["vulnerable"])
    assert r.ok and r.data["customer_email"] == "bob@example.test" and r.data["shipping_address"]


def test_refund_vulnerable_aprueba_directo(conn, alice):
    execute_tool(ToolCall("issue_refund", {"order_id": 1001, "amount": 10}), alice, conn, PROFILES["vulnerable"])
    assert refunds(conn, 1001)[0]["status"] == "approved"


def test_refund_registra_quien_lo_pidio(conn, alice):
    execute_tool(ToolCall("issue_refund", {"order_id": 2001, "amount": 10}), alice, conn, PROFILES["vulnerable"])
    assert refunds(conn, 2001)[0]["requested_by"] == "alice"


def test_refund_pedido_inexistente(conn, alice):
    r = execute_tool(ToolCall("issue_refund", {"order_id": 9999, "amount": 10}), alice, conn, PROFILES["vulnerable"])
    assert not r.ok and r.error == "not_found" and refunds_todos(conn) == []


def test_send_email_solo_guarda_fila(conn, alice):
    execute_tool(ToolCall("send_email", {"to": "x@example.test", "subject": "s", "body": "b"}),
                 alice, conn, PROFILES["vulnerable"])
    assert emails(conn)[0]["to_addr"] == "x@example.test"


@pytest.mark.parametrize("args", [
    {"order_id": 1001, "amount": -5},
    {"order_id": 1001, "amount": 0},
    {"order_id": 1001, "amount": "mucho"},
    {"order_id": 1001, "amount": float("nan")},
    {"order_id": 1001, "amount": True},
    {"order_id": "1 OR 1=1", "amount": 1},
    {"order_id": 1001},
    {},
])
@pytest.mark.parametrize("perfil", ["vulnerable", "segura"])
def test_argumentos_invalidos_no_cambian_estado(conn, alice, args, perfil):
    r = execute_tool(ToolCall("issue_refund", args), alice, conn, PROFILES[perfil])
    assert not r.ok and r.error == "invalid_arguments" and refunds_todos(conn) == []


@pytest.mark.parametrize("args", [
    {"to": "sin-arroba", "subject": "s", "body": "b"},
    {"to": "x@example.test", "subject": 3, "body": "b"},
    {"to": "x@example.test", "subject": "s"},
    {"to": "x@example.test", "subject": "s", "body": "b" * 10_001},
])
def test_email_invalido_no_guarda(conn, alice, args):
    r = execute_tool(ToolCall("send_email", args), alice, conn, PROFILES["vulnerable"])
    assert not r.ok and emails(conn) == []


def test_argumentos_extra_se_rechazan(conn, alice):
    r = execute_tool(ToolCall("get_order", {"order_id": 1001, "customer_id": "bob"}), alice, conn, PROFILES["vulnerable"])
    assert not r.ok and r.error == "invalid_arguments"


def test_herramienta_inexistente(conn, alice):
    r = execute_tool(ToolCall("drop_db", {}), alice, conn, PROFILES["vulnerable"])
    assert not r.ok and r.error == "unknown_tool"


def test_herramienta_no_permitida_no_se_ejecuta(conn, alice):
    r = execute_tool(ToolCall("send_email", {"to": "x@example.test", "subject": "s", "body": "b"}),
                     alice, conn, PROFILES["vulnerable"], allowed=frozenset({"get_order"}))
    assert not r.ok and r.error == "tool_not_allowed" and emails(conn) == []
