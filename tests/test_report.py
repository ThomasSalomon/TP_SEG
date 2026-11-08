import csv
import math

import pytest

from attacks.records import RunRecord
from attacks.report import fisher_p, main, summarize, wilson_interval


def rec(attack_id="V1-A1", profile="vulnerable", rep=0, status="success", vuln="V1", origin="dev",
        digest="sha256:abc", temperature=0.7, git_sha="deadbeef", model="m"):
    return RunRecord(attack_id=attack_id, vuln=vuln, origin=origin, profile=profile, rep=rep, seed=1000 + rep,
                     model=model, model_digest=digest, temperature=temperature, git_sha=git_sha, status=status,
                     error="x" if status == "error" else None, latency_ms=10, replies=[], tool_log=[])


def registros(success=0, blocked=0, error=0, **kw):
    estados = ["success"] * success + ["blocked"] * blocked + ["error"] * error
    return [rec(rep=i, status=s, **kw) for i, s in enumerate(estados)]


def escribir(path, records):
    path.write_text("".join(r.to_json() + "\n" for r in records), encoding="utf-8")
    return path


def jsonl_con_49(tmp_path):
    return escribir(tmp_path / "r.jsonl", registros(success=10, blocked=39, error=1))


def jsonl_con_sha_unknown(tmp_path):
    return escribir(tmp_path / "r.jsonl", registros(success=10, blocked=40, git_sha="unknown"))


# --- intervalos y tests --------------------------------------------------------

def test_wilson_cero_de_cincuenta():
    low, high = wilson_interval(0, 50)
    assert low == 0 and high == pytest.approx(0.0713, abs=0.001)


def test_wilson_mitad():
    low, high = wilson_interval(25, 50)
    assert low == pytest.approx(0.366, abs=0.001) and high == pytest.approx(0.634, abs=0.001)


def test_wilson_todo_exito():
    low, high = wilson_interval(50, 50)
    assert high == 1 and low == pytest.approx(1 - 0.0713, abs=0.001)


@pytest.mark.parametrize("k, n", [(0, 0), (-1, 10), (11, 10)])
def test_wilson_datos_invalidos_falla(k, n):
    with pytest.raises(ValueError):
        wilson_interval(k, n)


def test_wilson_sin_datos_falla():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_fisher_detecta_diferencia_clara():
    assert fisher_p(25, 50, 0, 50) < 0.001


def test_fisher_sin_diferencia():
    assert fisher_p(10, 50, 10, 50) == pytest.approx(1.0)


# --- summarize --------------------------------------------------------------------

def test_errores_fuera_del_denominador():
    row = summarize(registros(success=10, blocked=30, error=10))[0]
    assert row.valid == 40 and row.errors == 10 and row.rate == 0.25
    assert (row.ci_low, row.ci_high) == wilson_interval(10, 40)


def test_una_fila_por_ataque_y_perfil():
    rows = summarize(registros(success=2, profile="vulnerable") + registros(blocked=2, profile="segura")
                     + registros(success=1, attack_id="V1-A2"))
    assert {(r.attack_id, r.profile, r.successes) for r in rows} == {
        ("V1-A1", "vulnerable", 2), ("V1-A1", "segura", 0), ("V1-A2", "vulnerable", 1)}


def test_reintento_reemplaza_al_error():
    rows = summarize([rec(rep=0, status="error"), rec(rep=0, status="success")])
    assert rows[0].valid == 1 and rows[0].errors == 0 and rows[0].successes == 1


def test_solo_errores_da_tasa_indefinida():
    row = summarize(registros(error=3))[0]
    assert row.valid == 0 and row.errors == 3 and math.isnan(row.rate)


# --- CLI --------------------------------------------------------------------------

def test_genera_csv_y_markdown(tmp_path):
    src = escribir(tmp_path / "r.jsonl", registros(success=30, blocked=20, profile="vulnerable")
                   + registros(success=1, blocked=49, profile="segura")
                   + registros(success=48, blocked=2, attack_id="UTIL-1", vuln="UTIL", profile="segura")
                   + registros(success=5, blocked=45, attack_id="V1-H1", origin="heldout", profile="segura"))
    out = tmp_path / "out"
    assert main([str(src), "--out", str(out)]) == 0
    filas = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert len(filas) == 4 and {"attack_id", "profile", "rate", "ci_low", "ci_high"} <= set(filas[0])
    md = (out / "summary.md").read_text(encoding="utf-8")
    assert "dev" in md and "heldout" in md and "Utilidad" in md
    assert "sha256:abc" in md and "deadbeef" in md
    assert "Fisher" in md  # comparación vulnerable vs segura de V1-A1


def test_avisa_parametros_mezclados(tmp_path):
    src = escribir(tmp_path / "r.jsonl", registros(success=1, digest="a") + [rec(rep=5, digest="b")])
    out = tmp_path / "out"
    assert main([str(src), "--out", str(out)]) == 0
    assert "Atención" in (out / "summary.md").read_text(encoding="utf-8")


def test_strict_falla_con_menos_de_50_validas(tmp_path, capsys):
    assert main(["--strict", "--min-valid", "50", str(jsonl_con_49(tmp_path))]) != 0
    assert "49" in capsys.readouterr().err


def test_strict_falla_con_git_sha_unknown(tmp_path):
    assert main(["--strict", "--min-valid", "50", str(jsonl_con_sha_unknown(tmp_path))]) != 0


def test_strict_falla_con_parametros_mezclados(tmp_path):
    src = escribir(tmp_path / "r.jsonl", registros(success=50) + [rec(rep=50, temperature=0.2)])
    assert main(["--strict", "--min-valid", "50", str(src)]) != 0


def test_strict_pasa_con_datos_completos(tmp_path):
    src = escribir(tmp_path / "r.jsonl", registros(success=10, blocked=40))
    assert main(["--strict", "--min-valid", "50", str(src), "--out", str(tmp_path / "o")]) == 0


def test_varios_archivos_se_combinan(tmp_path):
    a = escribir(tmp_path / "a.jsonl", registros(success=1))
    b = escribir(tmp_path / "b.jsonl", [rec(rep=7, status="blocked")])
    out = tmp_path / "out"
    main([str(a), str(b), "--out", str(out)])
    fila = next(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert fila["valid"] == "2"
