"""Variante para máquinas con poca RAM: Ollama nativo en el host y solo las apps y el arnés en Docker.

Se valida la configuración ya combinada por `docker compose config`, que es lo que Docker usa de verdad.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOST_URL = "http://host.docker.internal:11434"

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="requiere la CLI de Docker")


@pytest.fixture(scope="module")
def merged():
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.host-ollama.yml",
         "--profile", "tools", "config", "--format", "json"],  # el perfil incluye al harness
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def default_services():
    """Servicios que levanta `docker compose ... up -d` sin perfiles."""
    out = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.host-ollama.yml",
         "config", "--services"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return set(out.stdout.split())


def test_ollama_en_docker_no_se_levanta(default_services):
    assert "ollama" not in default_services
    assert {"app-vulnerable", "app-segura"} <= default_services


def test_nada_depende_del_ollama_en_docker(merged):
    for name in ("app-vulnerable", "app-segura", "harness"):
        assert "ollama" not in merged["services"][name].get("depends_on", {}), name


def test_apps_y_arnes_usan_el_ollama_del_host(merged):
    for name in ("app-vulnerable", "app-segura", "harness"):
        svc = merged["services"][name]
        assert svc["environment"]["OLLAMA_BASE_URL"] == HOST_URL, name
        assert "host.docker.internal=host-gateway" in svc.get("extra_hosts", []) or \
            "host.docker.internal:host-gateway" in svc.get("extra_hosts", []), name


def test_no_quedan_en_una_red_interna(merged):
    # Una red interna no tiene ruta al host, y el Ollama nativo corre ahí.
    for name in ("app-vulnerable", "app-segura", "harness"):
        for net in merged["services"][name]["networks"]:
            assert merged["networks"][net].get("internal") is not True, (name, net)


def test_se_conservan_puertos_perfiles_y_parametros(merged):
    v, s = merged["services"]["app-vulnerable"], merged["services"]["app-segura"]
    assert [p["host_ip"] for p in v["ports"] + s["ports"]] == ["127.0.0.1", "127.0.0.1"]
    assert v["environment"]["SECURITY_PROFILE"] == "vulnerable"
    assert s["environment"]["SECURITY_PROFILE"] == "segura"
    assert v["volumes"] != s["volumes"]
    for svc in (v, s, merged["services"]["harness"]):
        assert svc["environment"]["LLM_MODEL"] == "qwen2.5:3b"
        assert svc["environment"]["LLM_BASE_SEED"] == "1000"
