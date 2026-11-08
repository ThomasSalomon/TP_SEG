import pytest

from app.config import PROFILES, ModelParams, load_profile, model_params_from_env


def test_segura_activa_todo():
    p = PROFILES["segura"]
    assert all([p.fix_v1, p.fix_v2, p.fix_v3, p.fix_v4, p.fix_v5, p.filters])


def test_vulnerable_no_activa_nada():
    p = PROFILES["vulnerable"]
    assert not any([p.fix_v1, p.fix_v2, p.fix_v3, p.fix_v4, p.fix_v5, p.filters])


def test_solo_v4_activa_solo_v4():
    p = PROFILES["solo_v4"]
    assert p.fix_v4 and not any([p.fix_v1, p.fix_v2, p.fix_v3, p.fix_v5, p.filters])


def test_solo_filtros_activa_solo_filtros():
    p = PROFILES["solo_filtros"]
    assert p.filters and not any([p.fix_v1, p.fix_v2, p.fix_v3, p.fix_v4, p.fix_v5])


def test_existen_todos_los_perfiles():
    esperados = {"vulnerable", "segura", "solo_filtros"} | {f"solo_v{i}" for i in range(1, 6)}
    assert set(PROFILES) == esperados
    assert all(p.name == n for n, p in PROFILES.items())


@pytest.mark.parametrize("name", [None, "", "seguro"])
def test_perfil_invalido_falla(name):
    with pytest.raises(ValueError):
        load_profile(name)


def test_load_profile_devuelve_el_perfil():
    assert load_profile("segura") is PROFILES["segura"]


def test_model_params_desde_entorno():
    p = model_params_from_env({
        "LLM_MODEL": "llama3.2:3b",
        "LLM_TEMPERATURE": "0.5",
        "LLM_BASE_SEED": "7",
        "LLM_NUM_PREDICT": "256",
        "LLM_NUM_CTX": "2048",
    })
    assert p == ModelParams(model="llama3.2:3b", temperature=0.5, base_seed=7, num_predict=256, num_ctx=2048)


def test_model_params_usa_valores_por_defecto():
    # valores de docs/decisiones/modelo.md
    assert model_params_from_env({}) == ModelParams(
        model="qwen2.5:3b", temperature=0.7, base_seed=1000, num_predict=512, num_ctx=4096
    )
