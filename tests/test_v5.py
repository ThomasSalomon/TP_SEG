"""V5: manejo inadecuado de la salida del modelo (tarea 14, LLM10).

La corrección tiene dos capas independientes: la UI muestra la respuesta como texto
(`textContent`) y la CSP impide ejecutar handlers inline aunque algo llegara al DOM como HTML.
Los tests de navegador usan la UI real del perfil con Playwright y se saltean si no hay
Chromium; el resto (oráculo, runner, cabeceras, batería) no lo necesita.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import PROFILES
from app.ingest import sanitize_review
from app.main import STATIC_DIR, create_app
from attacks.oracles import ORACLES, Evidence
from attacks.runner import RunContext, run_once
from attacks.schema import load_battery
from tests.fakes import ScriptedLLM, keyword_embed, text

BATTERY = Path(__file__).resolve().parent.parent / "attacks" / "battery" / "v5.yaml"
PAYLOAD = '<img src=x onerror="alert(1)">'
DETAILS = "<details open ontoggle=alert(1)>Ver detalle</details>"


# --- Navegador ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser():
    pytest.importorskip("playwright.sync_api")
    from attacks.xss import Browser

    try:
        b = Browser()
    except Exception as exc:  # sin Chromium instalado, no hay nada que probar acá
        pytest.skip(f"no se pudo abrir Chromium: {exc}")
    yield b
    b.close()


@pytest.fixture(scope="module")
def live_app():
    from attacks.xss import UiServer

    servers: dict[str, UiServer] = {}

    def start(profile: str) -> str:
        if profile not in servers:
            servers[profile] = UiServer(PROFILES[profile])
        return servers[profile].url

    yield start
    for s in servers.values():
        s.close()


@pytest.mark.parametrize("payload", [PAYLOAD, DETAILS])
def test_vulnerable_ejecuta_handler(browser, live_app, payload):
    assert browser.render_reply(live_app("vulnerable"), f"Mirá esto: {payload}").dialog_fired


def test_seguro_muestra_texto_literal(browser, live_app):
    r = browser.render_reply(live_app("solo_v5"), PAYLOAD)
    assert not r.dialog_fired
    assert PAYLOAD in r.message_text
    assert r.message_img_count == 0


def test_csp_bloquea_handler_inline_inyectado(browser, live_app):
    # Capa independiente: el nodo se inserta en el DOM esquivando la codificación de la UI.
    sin_csp = browser.inject_into_dom(live_app("vulnerable"), PAYLOAD)
    con_csp = browser.inject_into_dom(live_app("solo_v5"), PAYLOAD)
    assert sin_csp.dialog_fired  # control: el mismo nodo sí se ejecuta sin CSP
    assert not con_csp.dialog_fired
    assert any("script-src" in v for v in con_csp.csp_violations)


@pytest.mark.parametrize("payload", ["<script>alert(1)</script>", "<svg onload=alert(1)></svg>"])
def test_script_y_svg_onload_con_innerhtml_no_se_ejecutan(browser, live_app, payload):
    # Documenta por qué la batería no usa <script> ni <svg onload>: insertados con innerHTML,
    # Chromium no los ejecuta. Un <img onerror> o un <details ontoggle> sí.
    assert not browser.render_reply(live_app("vulnerable"), payload).dialog_fired


@pytest.mark.parametrize("profile", ["segura", "solo_v5"])
def test_ui_segura_funciona_con_csp(browser, live_app, profile):
    r = browser.normal_flow(live_app(profile))
    assert not r.dialog_fired
    assert r.csp_violations == []


def test_renderer_del_runner_por_perfil(browser):
    from attacks.xss import XssRenderer

    with XssRenderer(browser) as render:
        assert render(PROFILES["vulnerable"], PAYLOAD)
        assert not render(PROFILES["segura"], PAYLOAD)
        assert not render(PROFILES["vulnerable"], "Tu pedido llega mañana.")


# --- Cabeceras y HTML ---------------------------------------------------------------------

@pytest.fixture
def client_factory(deps):
    return lambda profile: TestClient(create_app(PROFILES[profile], deps))


def test_csp_presente_solo_con_fix(client_factory):
    assert "content-security-policy" not in client_factory("vulnerable").get("/").headers
    for profile in ("solo_v5", "segura"):
        client = client_factory(profile)
        for path in ("/", "/static/chat.js", "/api/config", "/health"):
            csp = client.get(path).headers["content-security-policy"]
            assert "script-src 'self'" in csp and "default-src 'none'" in csp
            assert "unsafe-inline" not in csp


def test_render_mode_por_perfil(client_factory):
    assert client_factory("vulnerable").get("/api/config").json() == {"render_mode": "html"}
    assert client_factory("solo_v5").get("/api/config").json() == {"render_mode": "text"}


def test_html_sin_scripts_ni_estilos_inline():
    # Si el HTML tuviera JS o CSS inline, la CSP de la versión segura rompería la UI.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert "<style" not in html
    assert not re.search(r"\s(style|on\w+)=", html)


def test_chat_js_usa_textcontent_por_defecto():
    js = (STATIC_DIR / "chat.js").read_text(encoding="utf-8")
    assert 'let renderMode = "text"' in js
    assert js.count("innerHTML") == 1  # solo la rama VULN-V5


# --- Oráculo ------------------------------------------------------------------------------

def evidencia(*replies, render=None):
    return Evidence(replies=list(replies), tool_log=[], conn=None, attacker_id="alice", render=render)


def test_oraculo_renderiza_cada_respuesta():
    vistas = []

    def render(reply):
        vistas.append(reply)
        return "onerror" in reply

    assert ORACLES["xss_executed"](evidencia("<b>hola</b>", PAYLOAD, render=render), {})
    assert vistas == ["<b>hola</b>", PAYLOAD]
    assert not ORACLES["xss_executed"](evidencia("<b>hola</b>", "<i>chau</i>", render=render), {})


def test_oraculo_saltea_respuestas_sin_etiquetas():
    # Sin "<" no hay HTML que ejecutar: no hace falta abrir el navegador.
    def render(reply):
        raise AssertionError("no debería renderizar")

    assert not ORACLES["xss_executed"](evidencia("Tu pedido 1001 está entregado.", render=render), {})


def test_oraculo_exige_navegador():
    with pytest.raises(ValueError, match="navegador"):
        ORACLES["xss_executed"](evidencia(PAYLOAD), {})


# --- Runner -------------------------------------------------------------------------------

def _ctx(tmp_path, llm, render):
    from tests.test_runner import PARAMS

    return RunContext(llm=llm, embed=keyword_embed, params=PARAMS, model_digest="d", git_sha="g",
                      workdir=tmp_path, render=render)


def _ataque(oracle="xss_executed"):
    from attacks.schema import Attack, OracleSpec

    return Attack(id="T-1", vuln="V5", origin="dev", session="alice", turns=["mostrame el html"],
                  oracle=OracleSpec(oracle, {}))


def test_runner_pasa_el_perfil_al_renderer(tmp_path):
    vistos = []

    def render(profile, reply):
        vistos.append((profile.name, reply))
        return profile.name == "vulnerable"

    llm = ScriptedLLM().script([text(PAYLOAD), text(PAYLOAD)])
    ctx = _ctx(tmp_path, llm, render)
    assert run_once(_ataque(), PROFILES["vulnerable"], 0, ctx).status == "success"
    assert run_once(_ataque(), PROFILES["segura"], 0, ctx).status == "blocked"
    assert vistos == [("vulnerable", PAYLOAD), ("segura", PAYLOAD)]


def test_runner_sin_renderer_registra_error(tmp_path):
    llm = ScriptedLLM().script([text(PAYLOAD)])
    r = run_once(_ataque(), PROFILES["vulnerable"], 0, _ctx(tmp_path, llm, None))
    assert r.status == "error" and "navegador" in r.error


# --- Batería ------------------------------------------------------------------------------

def test_bateria_v5():
    attacks = load_battery(BATTERY)
    assert [a.id for a in attacks] == ["V5-A1", "V5-A2", "V5-A3"]
    assert all(a.vuln == "V5" and a.origin == "dev" and a.oracle.type == "xss_executed" for a in attacks)
    a3 = attacks[2]
    assert a3.setup_reviews, "V5-A3 encadena con V2: el HTML llega por una reseña"


def test_resena_de_a3_pierde_el_html_con_fix_v2():
    # En la versión segura el HTML de la reseña ni siquiera llega al modelo (FIX-V2).
    for review in load_battery(BATTERY)[2].setup_reviews:
        clean, reason = sanitize_review(review)
        assert reason is not None or "<" not in clean
