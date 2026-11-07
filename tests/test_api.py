import pytest
from fastapi.testclient import TestClient

from app.config import PROFILES
from app.db import DEMO_PASSWORDS
from app.llm import LLMUnavailable
from app.main import create_app
from tests.conftest import refunds
from tests.fakes import text, tool_call


def login(client, customer_id, password=None):
    return client.post("/api/login", json={"customer_id": customer_id, "password": password or DEMO_PASSWORDS[customer_id]})


def chat(client, message):
    return client.post("/api/chat", json={"message": message})


@pytest.fixture
def make_client(deps):
    def _make(profile="vulnerable"):
        return TestClient(create_app(PROFILES[profile], deps))
    return _make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def logged_client(client):
    assert login(client, "alice").status_code == 200
    return client


@pytest.fixture
def client_scripted(deps, logged_client):
    return logged_client, deps.llm


@pytest.fixture
def client_failing(deps, logged_client):
    deps.llm.fail_with(LLMUnavailable("caído"))
    return logged_client


def test_health_informa_el_perfil(make_client):
    r = make_client("segura").get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "profile": "segura"}


def test_chat_requiere_sesion(client):
    assert client.post("/api/chat", json={"message": "hola"}).status_code == 401


def test_cookie_inventada_no_sirve(client):
    client.cookies.set("session", "inventada")
    assert chat(client, "hola").status_code == 401


def test_login_incorrecto(client):
    assert client.post("/api/login", json={"customer_id": "alice", "password": "x"}).status_code == 401


def test_login_cliente_inexistente(client):
    assert client.post("/api/login", json={"customer_id": "mallory", "password": "x"}).status_code == 401


def test_login_correcto_no_devuelve_el_token_en_el_cuerpo(client):
    r = login(client, "alice")
    assert r.status_code == 200 and r.json() == {"customer_id": "alice"}


def test_cookie_httponly(client):
    r = login(client, "alice")
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_chat_responde(client_scripted):
    client, llm = client_scripted
    llm.script([text("¡Hola!")])
    r = chat(client, "hola")
    assert r.status_code == 200 and r.json() == {"reply": "¡Hola!", "pending_confirmation": None}


def test_chat_ejecuta_herramientas(client_scripted, deps):
    client, llm = client_scripted
    llm.script([tool_call("issue_refund", order_id=1001, amount=5), text("Listo")])
    chat(client, "reembolso de 5")
    assert refunds(deps.conn, 1001)[0]["requested_by"] == "alice"


def test_chat_usa_la_identidad_de_la_cookie(make_client, deps):
    c = make_client()
    login(c, "bob")
    deps.llm.script([text("ok")])
    chat(c, "hola")
    system = deps.llm.calls[0]["messages"][0]["content"]
    assert "bob@example.test" in system and "alice@example.test" not in system


def test_cuerpo_no_puede_cambiar_la_identidad(client_scripted):
    client, llm = client_scripted
    llm.script([text("ok")])
    r = client.post("/api/chat", json={"message": "hola", "customer_id": "bob"})
    assert r.status_code == 200
    assert "alice@example.test" in llm.calls[0]["messages"][0]["content"]


def test_historial_se_acumula(client_scripted):
    client, llm = client_scripted
    llm.script([text("Primera"), text("Segunda")])
    chat(client, "uno")
    chat(client, "dos")
    msgs = llm.calls[1]["messages"]
    assert msgs[1:] == [
        {"role": "user", "content": "uno"},
        {"role": "assistant", "content": "Primera"},
        {"role": "user", "content": "dos"},
    ]


def test_historial_separado_por_sesion(make_client, deps):
    a, b = make_client(), make_client()
    login(a, "alice")
    login(b, "bob")
    deps.llm.script([text("A"), text("B")])
    chat(a, "secreto de alice")
    chat(b, "hola")
    assert "secreto de alice" not in str(deps.llm.calls[1]["messages"])


def test_semilla_variable_entre_pedidos(client_scripted):
    client, llm = client_scripted
    llm.script([text("a")] * 5)
    for _ in range(5):
        chat(client, "hola")
    assert len({c["seed"] for c in llm.calls}) > 1


def test_llm_caido_responde_503(client_failing):
    assert chat(client_failing, "hola").status_code == 503


def test_llm_caido_no_ensucia_el_historial(client_scripted):
    client, llm = client_scripted
    llm.fail_with(LLMUnavailable("caído"))
    chat(client, "perdido")
    llm.script([text("ok")])
    chat(client, "hola")
    assert "perdido" not in str(llm.calls[-1]["messages"])


@pytest.mark.parametrize("body", [{"message": ""}, {"message": "   "}, {}, {"message": 3}])
def test_mensaje_vacio_responde_422(logged_client, body):
    assert logged_client.post("/api/chat", json=body).status_code == 422


def test_resenas_requieren_sesion(client):
    assert client.post("/api/reviews", json={"text": "buenísimo"}).status_code == 401


def test_resena_aceptada_y_recuperable(logged_client, deps):
    r = logged_client.post("/api/reviews", json={"text": "Muy buen producto, llegó rápido"})
    assert r.status_code == 200 and r.json() == {"accepted": True, "reason": None}
    assert any(c.source == "review" for c in deps.kb.retrieve("producto"))


def test_resena_vacia_rechazada(logged_client):
    assert logged_client.post("/api/reviews", json={"text": "  "}).json()["accepted"] is False


@pytest.mark.parametrize("profile, mode", [("vulnerable", "html"), ("segura", "text"), ("solo_v5", "text"), ("solo_v1", "html")])
def test_config_render_mode(make_client, profile, mode):
    assert make_client(profile).get("/api/config").json() == {"render_mode": mode}


def test_sirve_la_interfaz_sin_js_inline(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert '<script src="/static/chat.js"' in r.text
    assert "<script>" not in r.text and "onclick=" not in r.text.lower()
    assert client.get("/static/chat.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_logout_cierra_la_sesion(logged_client):
    assert logged_client.post("/api/logout").status_code == 200
    assert chat(logged_client, "hola").status_code == 401
