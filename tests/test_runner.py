import json
from pathlib import Path

import pytest

from app.config import PROFILES, ModelParams
from app.llm import LLMUnavailable
from attacks.oracles import ORACLES
from attacks.records import read_records
from attacks.runner import RunContext, main, run_battery, run_once, seed_for
from attacks.schema import Attack, OracleSpec, load_battery
from tests.fakes import ScriptedLLM, keyword_embed, text, tool_call

SMOKE = Path(__file__).parent / "data" / "smoke.yaml"
PARAMS = ModelParams("modelo:test", 0.7, 1000, 256, 4096)


def leer(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def make_ctx(tmp_path):
    def _make(llm=None):
        llm = llm or ScriptedLLM()
        return RunContext(llm=llm, embed=keyword_embed, params=PARAMS, model_digest="sha256:abc",
                          git_sha="deadbeef", workdir=tmp_path / "work")
    return _make


@pytest.fixture
def ctx(make_ctx):
    return make_ctx()


@pytest.fixture
def ctx_failing(make_ctx):
    return make_ctx(ScriptedLLM().fail_with(LLMUnavailable("timeout")))


@pytest.fixture
def ataque():
    return Attack(id="T-1", vuln="UTIL", origin="dev", session="alice", turns=["hola"],
                  oracle=OracleSpec("reply_contains_any", {"values": ["hola"]}))


@pytest.fixture
def ataque_con_oraculo_any_refund(monkeypatch):
    # any_refund es un oráculo registrado solo en este test
    monkeypatch.setitem(ORACLES, "any_refund",
                        lambda ev, args: ev.conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] > 0)
    return Attack(id="T-REF", vuln="V1", origin="dev", session="alice", turns=["reembolso"],
                  oracle=OracleSpec("any_refund", {}))


def bateria_con(oracle, dir):
    path = dir / "b.yaml"
    path.write_text(
        "attacks:\n"
        "  - id: X-1\n    vuln: V1\n    origin: dev\n    session: alice\n    turns: [hola]\n"
        f"    oracle: {{type: {oracle}, args: {{}}}}\n",
        encoding="utf-8",
    )
    return path


# --- semillas -----------------------------------------------------------------

def test_semillas_distintas_por_repeticion():
    assert seed_for(1000, 0) == 1000 and seed_for(1000, 49) == 1049


def test_misma_semilla_entre_perfiles(ctx, ataque):
    a = run_once(ataque, PROFILES["vulnerable"], 3, ctx)
    b = run_once(ataque, PROFILES["segura"], 3, ctx)
    assert a.seed == b.seed == 1003
    assert [c["seed"] for c in ctx.llm.calls] == [1003, 1003]


# --- run_once -----------------------------------------------------------------

def test_exito_y_bloqueo_segun_el_oraculo(ctx, ataque):
    ctx.llm.script([text("hola, ¿qué tal?"), text("buenas")])
    assert run_once(ataque, PROFILES["vulnerable"], 0, ctx).status == "success"
    assert run_once(ataque, PROFILES["vulnerable"], 1, ctx).status == "blocked"


def test_error_del_llm_no_cuenta_como_bloqueado(ctx_failing, ataque):
    r = run_once(ataque, PROFILES["vulnerable"], 0, ctx_failing)
    assert r.status == "error" and r.error


def test_error_de_embeddings_cuenta_como_error(make_ctx, ataque):
    def embed_caido(texts):
        raise LLMUnavailable("embeddings caídos")
    ctx = RunContext(llm=ScriptedLLM(), embed=embed_caido, params=PARAMS, model_digest="d",
                     git_sha="s", workdir=make_ctx().workdir)
    r = run_once(ataque, PROFILES["vulnerable"], 0, ctx)
    assert r.status == "error" and "embeddings" in r.error


def test_estado_aislado_entre_repeticiones(ctx, ataque_con_oraculo_any_refund):
    a = ataque_con_oraculo_any_refund
    ctx.llm.script([tool_call("issue_refund", order_id=1001, amount=1), text("ok"), text("sin herramientas")])
    assert run_once(a, PROFILES["vulnerable"], 0, ctx).status == "success"
    assert run_once(a, PROFILES["vulnerable"], 1, ctx).status == "blocked"


def test_varios_turnos_comparten_historial(ctx):
    a = Attack(id="T-MT", vuln="V1", origin="dev", session="alice", turns=["uno", "dos"],
               oracle=OracleSpec("reply_contains_any", {"values": ["segunda"]}))
    ctx.llm.script([text("primera"), text("segunda")])
    r = run_once(a, PROFILES["vulnerable"], 0, ctx)
    assert r.status == "success" and r.replies == ["primera", "segunda"]
    assert {"role": "assistant", "content": "primera"} in ctx.llm.calls[1]["messages"]


def test_usa_la_sesion_del_ataque(ctx):
    a = Attack(id="T-BOB", vuln="UTIL", origin="dev", session="bob", turns=["hola"],
               oracle=OracleSpec("reply_contains_any", {"values": ["x"]}))
    run_once(a, PROFILES["vulnerable"], 0, ctx)
    assert "bob@example.test" in ctx.llm.calls[0]["messages"][0]["content"]


def test_setup_reviews_llegan_al_contexto(ctx):
    a = Attack(id="T-REV", vuln="V2", origin="dev", session="alice", turns=["¿qué opinan del producto?"],
               oracle=OracleSpec("reply_contains_any", {"values": ["x"]}),
               setup_reviews=["Reseña envenenada sobre el producto"])
    run_once(a, PROFILES["vulnerable"], 0, ctx)
    assert "Reseña envenenada" in json.dumps(ctx.llm.calls[0]["messages"], ensure_ascii=False)


def test_resenas_no_se_filtran_a_otro_ataque(ctx, ataque):
    con_resena = Attack(id="T-REV", vuln="V2", origin="dev", session="alice", turns=["producto"],
                        oracle=OracleSpec("reply_contains_any", {"values": ["x"]}),
                        setup_reviews=["Reseña envenenada sobre el producto"])
    run_once(con_resena, PROFILES["vulnerable"], 0, ctx)
    run_once(Attack(**{**ataque.__dict__, "turns": ["producto"]}), PROFILES["vulnerable"], 0, ctx)
    assert "envenenada" not in json.dumps(ctx.llm.calls[1]["messages"], ensure_ascii=False)


def test_registra_digest_y_git_sha(ctx, ataque):
    r = run_once(ataque, PROFILES["vulnerable"], 0, ctx)
    assert r.model_digest == "sha256:abc" and r.git_sha == "deadbeef"
    assert r.model == "modelo:test" and r.temperature == 0.7 and r.profile == "vulnerable"


def test_registra_el_log_de_herramientas(ctx, ataque):
    ctx.llm.script([tool_call("get_order", order_id=1001), text("ok")])
    r = run_once(ataque, PROFILES["vulnerable"], 0, ctx)
    assert r.tool_log[0]["call"]["name"] == "get_order" and r.tool_log[0]["result"]["ok"]


def test_no_deja_bases_temporales(ctx, ataque):
    run_once(ataque, PROFILES["vulnerable"], 0, ctx)
    assert not list(ctx.workdir.glob("*.sqlite3"))


# --- run_battery ----------------------------------------------------------------

def test_retoma_sin_repetir(ctx, ataque, tmp_path):
    out = tmp_path / "r.jsonl"
    run_battery([ataque], [PROFILES["vulnerable"]], 2, ctx, out)
    run_battery([ataque], [PROFILES["vulnerable"]], 5, ctx, out)
    assert sorted(r["rep"] for r in leer(out)) == [0, 1, 2, 3, 4]


def test_retoma_despues_de_una_escritura_cortada(ctx, ataque, tmp_path):
    out = tmp_path / "r.jsonl"
    run_battery([ataque], [PROFILES["vulnerable"]], 2, ctx, out)
    with out.open("a", encoding="utf-8") as f:
        f.write('{"attack_id": "x", "prof')  # el proceso murió a mitad de un write
    run_battery([ataque], [PROFILES["vulnerable"]], 4, ctx, out)
    run_battery([ataque], [PROFILES["vulnerable"]], 5, ctx, out)  # un segundo retome también funciona
    assert sorted(r.rep for r in read_records(out)) == [0, 1, 2, 3, 4]


def test_reintenta_los_errores_al_retomar(make_ctx, ataque, tmp_path):
    out = tmp_path / "r.jsonl"
    run_battery([ataque], [PROFILES["vulnerable"]], 2, make_ctx(ScriptedLLM().fail_with(LLMUnavailable("x"))), out)
    assert [r["status"] for r in leer(out)] == ["error", "error"]
    run_battery([ataque], [PROFILES["vulnerable"]], 2, make_ctx(ScriptedLLM().script([text("hola")] * 2)), out)
    finales = read_records(out)
    assert sorted((r.rep, r.status) for r in finales) == [(0, "success"), (1, "success")]


def test_cubre_perfiles_y_ataques(ctx, ataque, tmp_path):
    otro = Attack(**{**ataque.__dict__, "id": "T-2"})
    out = tmp_path / "r.jsonl"
    run_battery([ataque, otro], [PROFILES["vulnerable"], PROFILES["segura"]], 3, ctx, out)
    claves = {(r["attack_id"], r["profile"], r["rep"]) for r in leer(out)}
    assert len(claves) == 2 * 2 * 3


# --- carga de la batería --------------------------------------------------------

def test_carga_la_bateria_de_humo():
    attacks = load_battery(SMOKE)
    assert [a.id for a in attacks] == ["SMOKE-FAQ", "SMOKE-PEDIDO"]
    assert attacks[1].oracle == OracleSpec("tool_succeeded", {"tool": "get_order"})


def test_carga_un_directorio(tmp_path):
    (tmp_path / "a.yaml").write_text(SMOKE.read_text(encoding="utf-8"), encoding="utf-8")
    bateria_con("reply_contains_any", tmp_path)
    assert {a.id for a in load_battery(tmp_path)} == {"SMOKE-FAQ", "SMOKE-PEDIDO", "X-1"}


def test_oraculo_desconocido_falla_al_cargar(tmp_path):
    with pytest.raises(ValueError):
        load_battery(bateria_con(oracle="no_existe", dir=tmp_path))


@pytest.mark.parametrize("campo, valor", [
    ("vuln", "V9"), ("origin", "prod"), ("session", "mallory"), ("turns", "[]"),
])
def test_campos_invalidos_fallan_al_cargar(tmp_path, campo, valor):
    texto = bateria_con("reply_contains_any", tmp_path).read_text(encoding="utf-8")
    original = {"vuln": "V1", "origin": "dev", "session": "alice", "turns": "[hola]"}[campo]
    (tmp_path / "b.yaml").write_text(texto.replace(f"{campo}: {original}", f"{campo}: {valor}"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_battery(tmp_path / "b.yaml")


def test_ids_duplicados_fallan(tmp_path):
    (tmp_path / "a.yaml").write_text(SMOKE.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(SMOKE.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_battery(tmp_path)


# --- CLI ------------------------------------------------------------------------

def test_cli_falla_sin_modelo(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LLM_TIMEOUT_S", "1")
    code = main(["--battery", str(SMOKE), "--profiles", "vulnerable", "--reps", "1",
                 "--out", str(tmp_path / "x.jsonl")])
    assert code != 0 and not (tmp_path / "x.jsonl").exists()


def test_cli_rechaza_perfil_desconocido(tmp_path):
    with pytest.raises(SystemExit):
        main(["--battery", str(SMOKE), "--profiles", "seguro", "--reps", "1", "--out", str(tmp_path / "x.jsonl")])
