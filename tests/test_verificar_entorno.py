from app.config import EXPECTED_OLLAMA_VERSION, MODEL_DIGESTS
from scripts.verificar_entorno import FAIL, OK, WARN, check_models, check_ollama_version, check_python, exit_code

QWEN = "qwen2.5:3b"
NOMIC = "nomic-embed-text"


def tags(**digests):
    return {"models": [{"name": n, "model": n, "digest": d} for n, d in digests.items()]}


def test_valores_esperados_documentados():
    assert set(MODEL_DIGESTS) == {QWEN, NOMIC}
    assert all(len(d) == 64 for d in MODEL_DIGESTS.values())
    assert EXPECTED_OLLAMA_VERSION.count(".") == 2


def test_python_312_ok():
    assert check_python((3, 12, 16)).status == OK


def test_otro_python_falla():
    assert check_python((3, 13, 5)).status == FAIL


def test_misma_version_de_ollama():
    assert check_ollama_version(EXPECTED_OLLAMA_VERSION).status == OK


def test_otra_version_de_ollama_advierte():
    assert check_ollama_version("0.1.0").status == WARN


def test_modelos_con_digest_correcto():
    checks = check_models(tags(**{QWEN: MODEL_DIGESTS[QWEN], f"{NOMIC}:latest": MODEL_DIGESTS[NOMIC]}))
    assert [c.status for c in checks] == [OK, OK]


def test_modelo_faltante_falla():
    checks = check_models(tags(**{QWEN: MODEL_DIGESTS[QWEN]}))
    assert {c.name: c.status for c in checks}[f"modelo {NOMIC}"] == FAIL


def test_digest_distinto_falla():
    checks = check_models(tags(**{QWEN: "0" * 64, NOMIC: MODEL_DIGESTS[NOMIC]}))
    falla = {c.name: c for c in checks}[f"modelo {QWEN}"]
    assert falla.status == FAIL and "ollama pull" in falla.detail


def test_codigo_de_salida():
    from scripts.verificar_entorno import Check

    assert exit_code([Check("a", OK, ""), Check("b", WARN, "")]) == 0
    assert exit_code([Check("a", OK, ""), Check("b", FAIL, "")]) == 1
