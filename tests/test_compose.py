from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_puertos_solo_en_localhost(compose):
    for name, svc in compose["services"].items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), name


def test_ollama_no_publica_puertos(compose):
    assert "ports" not in compose["services"]["ollama"]


def test_perfiles_y_volumenes_separados(compose):
    v, s = compose["services"]["app-vulnerable"], compose["services"]["app-segura"]
    assert v["environment"]["SECURITY_PROFILE"] == "vulnerable"
    assert s["environment"]["SECURITY_PROFILE"] == "segura"
    assert v["volumes"] != s["volumes"]


def test_puertos_de_cada_version(compose):
    assert compose["services"]["app-vulnerable"]["ports"] == ["127.0.0.1:8001:8000"]
    assert compose["services"]["app-segura"]["ports"] == ["127.0.0.1:8002:8000"]


def test_red_del_laboratorio_es_interna(compose):
    assert compose["networks"]["lab"]["internal"] is True


def test_ollama_y_harness_solo_en_lab(compose):
    assert compose["services"]["ollama"]["networks"] == ["lab"]
    assert compose["services"]["harness"]["networks"] == ["lab"]


def test_solo_ollama_init_tiene_salida_a_internet(compose):
    init = compose["services"]["ollama-init"]
    assert init["networks"] == ["egress"] and init["profiles"] == ["setup"]
    assert compose["networks"]["egress"].get("internal") is not True


def test_apps_en_lab_y_front(compose):
    for name in ("app-vulnerable", "app-segura"):
        assert sorted(compose["services"][name]["networks"]) == ["front", "lab"]


def test_harness_monta_ataques_y_resultados_y_recibe_git_sha(compose):
    h = compose["services"]["harness"]
    assert h["profiles"] == ["tools"]
    destinos = {v.split(":")[1] for v in h["volumes"]}
    assert {"/app/attacks", "/app/results"} <= destinos
    assert "GIT_SHA" in h["environment"]


def test_ollama_procesa_un_pedido_a_la_vez(compose):
    assert str(compose["services"]["ollama"]["environment"]["OLLAMA_NUM_PARALLEL"]) == "1"


def test_ollama_comparte_volumen_de_modelos_con_init(compose):
    vol = lambda s: {v.split(":")[0] for v in compose["services"][s]["volumes"]}  # noqa: E731
    assert vol("ollama") & vol("ollama-init")
