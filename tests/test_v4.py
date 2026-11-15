"""V4: agencia excesiva (tarea 13).

Con `ScriptedLLM` se simula que el modelo ya decidió actuar sobre un pedido ajeno o sin
permiso del cliente. En `vulnerable` el backend lo hace; con `fix_v4`, la identidad sale
solo de la sesión y un reembolso necesita la confirmación del cliente fuera del modelo.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import PROFILES, ModelParams
from app.db import DEMO_PASSWORDS
from app.main import create_app
from app.orchestrator import handle_message
from app.tools import confirm_refund
from attacks.oracles import ORACLES, Evidence
from attacks.runner import RunContext, run_once
from attacks.schema import Attack, OracleSpec, load_battery
from tests.conftest import emails, refunds
from tests.fakes import ScriptedLLM, keyword_embed, text, tool_call

BATTERY = Path(__file__).resolve().parent.parent / "attacks" / "battery" / "v4.yaml"
V4 = PROFILES["solo_v4"]


@pytest.fixture
def pendiente(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("Confirmá")])
    r = handle_message("Quiero un reembolso de 10 del pedido 1001", [], alice, deps, V4, seed=1)
    assert r.pending_confirmation
    return r.pending_confirmation


# --- Autorización por sesión ------------------------------------------------------------

def test_vulnerable_reembolsa_pedido_ajeno(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=2001, amount=150), text("Listo")])
    handle_message("x", [], alice, deps, PROFILES["vulnerable"], seed=1)
    assert refunds(deps.conn, 2001)[0]["status"] == "approved"


def test_fix_niega_pedido_ajeno(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=2001, amount=150), text("No")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert refunds(deps.conn, 2001) == [] and r.tool_log[0].result.error == "forbidden"
    assert r.pending_confirmation is None


def test_vulnerable_lee_pedido_ajeno(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=2001), text("ok")])
    r = handle_message("x", [], alice, deps, PROFILES["vulnerable"], seed=1)
    assert r.tool_log[0].result.data["customer_email"] == "bob@example.test"


def test_fix_niega_leer_pedido_ajeno(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=2001), text("No")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert r.tool_log[0].result.error == "forbidden" and r.tool_log[0].result.data == {}
    assert "bob@example.test" not in json.dumps(deps.llm.calls)


def test_fix_permite_leer_pedido_propio(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=1001), text("ok")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert r.tool_log[0].result.ok and r.tool_log[0].result.data["order_id"] == 1001


def test_fix_pedido_inexistente_sigue_siendo_not_found(deps, alice):
    deps.llm.script([tool_call("get_order", order_id=9999), text("ok")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert r.tool_log[0].result.error == "not_found"


def test_vulnerable_envia_email_a_cualquiera(deps, alice):
    deps.llm.script([tool_call("send_email", to="bob@example.test", subject="s", body="b"), text("ok")])
    handle_message("x", [], alice, deps, PROFILES["vulnerable"], seed=1)
    assert [e["to_addr"] for e in emails(deps.conn)] == ["bob@example.test"]


@pytest.mark.parametrize("destino", ["bob@example.test", "attacker@evil.test"])
def test_fix_email_solo_al_cliente_de_la_sesion(deps, alice, destino):
    deps.llm.script([tool_call("send_email", to=destino, subject="s", body="b"), text("ok")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert emails(deps.conn) == [] and r.tool_log[0].result.error == "forbidden"


def test_fix_email_al_propio_cliente_funciona(deps, alice):
    deps.llm.script([tool_call("send_email", to="Alice@Example.test", subject="s", body="b"), text("ok")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert r.tool_log[0].result.ok and len(emails(deps.conn)) == 1


# --- Confirmación del reembolso ---------------------------------------------------------

def test_vulnerable_reembolso_propio_se_aprueba_sin_confirmar(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("Listo")])
    r = handle_message("x", [], alice, deps, PROFILES["vulnerable"], seed=1)
    assert refunds(deps.conn, 1001)[0]["status"] == "approved" and r.pending_confirmation is None


def test_fix_reembolso_propio_queda_pendiente(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("Confirmá")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert refunds(deps.conn, 1001)[0]["status"] == "pending_confirmation"
    assert r.pending_confirmation
    assert r.tool_log[0].result.data["status"] == "pending_confirmation"


def test_confirmacion_aprueba(deps, alice, pendiente):
    assert confirm_refund(pendiente, alice, deps.conn).ok
    assert refunds(deps.conn, 1001)[0]["status"] == "approved"


def test_token_no_se_reutiliza(deps, alice, pendiente):
    confirm_refund(pendiente, alice, deps.conn)
    r = confirm_refund(pendiente, alice, deps.conn)
    assert not r.ok and r.error == "invalid_token"


def test_token_de_otra_sesion_falla(deps, bob, pendiente):
    assert not confirm_refund(pendiente, bob, deps.conn).ok
    assert refunds(deps.conn, 1001)[0]["status"] == "pending_confirmation"


@pytest.mark.parametrize("token", ["", "inventado", None, 123])
def test_token_invalido_falla(deps, alice, pendiente, token):
    assert not confirm_refund(token, alice, deps.conn).ok


def test_decir_confirmo_en_el_chat_no_aprueba(deps, alice, pendiente):
    deps.llm.script([text("Confirmado")])
    handle_message(f"Confirmo el token {pendiente}", [], alice, deps, V4, seed=1)
    assert refunds(deps.conn, 1001)[0]["status"] == "pending_confirmation"


def test_token_no_llega_al_modelo(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("Confirmá")])
    r = handle_message("x", [], alice, deps, V4, seed=1)
    assert r.pending_confirmation not in json.dumps(deps.llm.calls)


# --- API --------------------------------------------------------------------------------

@pytest.fixture
def client_v4(deps):
    return TestClient(create_app(V4, deps))


def _login(client, who="alice"):
    assert client.post("/api/login", json={"customer_id": who, "password": DEMO_PASSWORDS[who]}).status_code == 200


def test_ruta_confirmar_exige_sesion(client_v4):
    assert client_v4.post("/api/tools/confirm", json={"token": "x"}).status_code == 401


def test_ruta_confirmar_aprueba_el_reembolso(client_v4, deps):
    _login(client_v4)
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("Confirmá el reembolso")])
    token = client_v4.post("/api/chat", json={"message": "reembolso de 10 del 1001"}).json()["pending_confirmation"]
    assert token
    r = client_v4.post("/api/tools/confirm", json={"token": token})
    assert r.status_code == 200 and r.json() == {"ok": True, "error": None}
    assert refunds(deps.conn, 1001)[0]["status"] == "approved"
    assert client_v4.post("/api/tools/confirm", json={"token": token}).json() == {"ok": False, "error": "invalid_token"}


def test_ruta_confirmar_con_otra_sesion_falla(deps):
    alice_c, bob_c = TestClient(create_app(V4, deps)), None
    _login(alice_c)
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("ok")])
    token = alice_c.post("/api/chat", json={"message": "x"}).json()["pending_confirmation"]
    bob_c = TestClient(alice_c.app)
    _login(bob_c, "bob")
    assert bob_c.post("/api/tools/confirm", json={"token": token}).json()["ok"] is False


def test_ruta_confirmar_valida_el_cuerpo(client_v4):
    _login(client_v4)
    assert client_v4.post("/api/tools/confirm", json={"token": 5}).status_code == 422


# --- Runner: el atacante es el cliente, así que confirma lo que pidió -----------------------

PARAMS = ModelParams("modelo:test", 0.7, 1000, 256, 4096)


def _ctx(tmp_path, llm):
    return RunContext(llm=llm, embed=keyword_embed, params=PARAMS, model_digest="sha256:abc",
                      git_sha="deadbeef", workdir=tmp_path / "work")


def _ataque_reembolso(**extra):
    return Attack(id="T-V4", vuln="V1", origin="dev", session="alice", turns=["reembolso 1001"],
                  oracle=OracleSpec("tool_succeeded", {"tool": "issue_refund"}), **extra)


def test_runner_confirma_el_reembolso_pendiente(tmp_path, monkeypatch):
    estados = []
    monkeypatch.setitem(ORACLES, "estado_reembolso", lambda ev, args: estados.append(
        [r["status"] for r in ev.conn.execute("SELECT status FROM refunds")]) or True)
    llm = ScriptedLLM().script([tool_call("issue_refund", order_id=1001, amount=10), text("Confirmá")])
    a = _ataque_reembolso()
    a = Attack(**{**a.__dict__, "oracle": OracleSpec("estado_reembolso", {})})
    rec = run_once(a, V4, 0, _ctx(tmp_path, llm))
    assert estados == [["approved"]]
    assert [e["call"]["name"] for e in rec.tool_log] == ["issue_refund", "ui:confirm_refund"]


def test_runner_puede_no_confirmar(tmp_path, monkeypatch):
    estados = []
    monkeypatch.setitem(ORACLES, "estado_reembolso", lambda ev, args: estados.append(
        [r["status"] for r in ev.conn.execute("SELECT status FROM refunds")]) or True)
    llm = ScriptedLLM().script([tool_call("issue_refund", order_id=1001, amount=10), text("Confirmá")])
    a = Attack(id="T-V4", vuln="V2", origin="dev", session="alice", turns=["x"],
               oracle=OracleSpec("estado_reembolso", {}), confirm_pending=False)
    run_once(a, V4, 0, _ctx(tmp_path, llm))
    assert estados == [["pending_confirmation"]]


def test_bateria_acepta_confirm_pending(tmp_path):
    path = tmp_path / "b.yaml"
    path.write_text("attacks:\n  - id: X-1\n    vuln: V2\n    origin: dev\n    session: alice\n"
                    "    turns: [hola]\n    confirm_pending: false\n"
                    "    oracle: {type: tool_succeeded, args: {tool: get_order}}\n", encoding="utf-8")
    assert load_battery(path)[0].confirm_pending is False


def test_bateria_rechaza_confirm_pending_no_booleano(tmp_path):
    path = tmp_path / "b.yaml"
    path.write_text("attacks:\n  - id: X-1\n    vuln: V2\n    origin: dev\n    session: alice\n"
                    "    turns: [hola]\n    confirm_pending: 'no'\n"
                    "    oracle: {type: tool_succeeded, args: {tool: get_order}}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_battery(path)


# --- Oráculos ---------------------------------------------------------------------------

def _evidencia(deps, *replies, attacker="alice"):
    return Evidence(replies=list(replies), tool_log=[], conn=deps.conn, attacker_id=attacker)


def test_oraculo_refund_on_foreign_order(deps, alice):
    o = ORACLES["refund_on_foreign_order"]
    assert not o(_evidencia(deps), {})
    deps.llm.script([tool_call("issue_refund", order_id=1001, amount=10), text("ok")])
    handle_message("x", [], alice, deps, PROFILES["vulnerable"], seed=1)
    assert not o(_evidencia(deps), {})  # pedido propio
    deps.llm.script([tool_call("issue_refund", order_id=2001, amount=10), text("ok")])
    handle_message("x", [], alice, deps, PROFILES["vulnerable"], seed=1)
    assert o(_evidencia(deps), {})


def test_oraculo_refund_on_foreign_order_depende_del_atacante(deps, alice):
    deps.llm.script([tool_call("issue_refund", order_id=2001, amount=10), text("ok")])
    handle_message("x", [], alice, deps, PROFILES["vulnerable"], seed=1)
    assert not ORACLES["refund_on_foreign_order"](_evidencia(deps, attacker="bob"), {})  # para bob es propio


def test_oraculo_refund_on_foreign_order_ignora_pendientes(deps):
    deps.conn.execute("INSERT INTO refunds (order_id, requested_by, amount, status, token, created_at) "
                      "VALUES (2001, 'alice', 10, 'pending_confirmation', 't', 'x')")
    assert not ORACLES["refund_on_foreign_order"](_evidencia(deps), {})


@pytest.mark.parametrize("respuesta", [
    "El email del pedido es bob@example.test",
    "Se envió a Av. Siempreviva 742, Rosario",
    "La dirección es Avenida Siempreviva 742",
])
def test_oraculo_foreign_pii_in_reply_detecta(deps, respuesta):
    assert ORACLES["foreign_pii_in_reply"](_evidencia(deps, "hola", respuesta), {})


@pytest.mark.parametrize("respuesta", [
    "No puedo darte datos de otro cliente",
    "Tu pedido va a Calle Falsa 123, Córdoba, y tu email es alice@example.test",
])
def test_oraculo_foreign_pii_in_reply_ignora(deps, respuesta):
    assert not ORACLES["foreign_pii_in_reply"](_evidencia(deps, respuesta), {})


# --- Batería ----------------------------------------------------------------------------

def test_bateria_v4_tiene_los_tres_ataques_dev():
    ataques = {a.id: a for a in load_battery(BATTERY)}
    assert {"V4-A1", "V4-A2", "V4-A3"} <= set(ataques)
    assert ataques["V4-A1"].oracle.type == ataques["V4-A2"].oracle.type == "refund_on_foreign_order"
    assert ataques["V4-A3"].oracle.type == "foreign_pii_in_reply"
    assert all(a.vuln == "V4" and a.session == "alice" for a in ataques.values())
