"""Perfiles de seguridad y parámetros del modelo.

Una sola base de código se comporta como versión vulnerable o segura según el
`SecurityProfile` activo. Cada corrección se activa con su propio flag, para poder
medir el efecto de cada una por separado (perfiles `solo_vN` y `solo_filtros`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityProfile:
    name: str
    fix_v1: bool = False  # reglas de negocio en el backend (inyección directa)
    fix_v2: bool = False  # contenido recuperado tratado como no confiable (inyección indirecta)
    fix_v3: bool = False  # sin secretos en el contexto del modelo
    fix_v4: bool = False  # autorización por sesión y confirmación del usuario
    fix_v5: bool = False  # salida codificada y CSP
    filters: bool = False  # filtros de entrada y salida (capa adicional, no control de diseño)


def _profiles() -> dict[str, SecurityProfile]:
    profiles = {
        "vulnerable": SecurityProfile("vulnerable"),
        "segura": SecurityProfile(
            "segura", fix_v1=True, fix_v2=True, fix_v3=True, fix_v4=True, fix_v5=True, filters=True
        ),
        "solo_filtros": SecurityProfile("solo_filtros", filters=True),
    }
    for i in range(1, 6):
        name = f"solo_v{i}"
        profiles[name] = SecurityProfile(name, **{f"fix_v{i}": True})
    return profiles


PROFILES: dict[str, SecurityProfile] = _profiles()


def load_profile(name: str | None) -> SecurityProfile:
    """Devuelve el perfil pedido. Falla si falta o no existe: no hay perfil por defecto."""
    if not name:
        raise ValueError("SECURITY_PROFILE es obligatorio (vulnerable, segura, solo_filtros, solo_v1 … solo_v5)")
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"Perfil desconocido: {name!r}. Opciones: {', '.join(sorted(PROFILES))}") from None


@dataclass(frozen=True)
class ModelParams:
    model: str
    temperature: float
    base_seed: int
    num_predict: int
    num_ctx: int


# Valores provisorios hasta cerrar la tarea 2 (docs/decisiones/modelo.md).
DEFAULT_MODEL_PARAMS = ModelParams(
    model="qwen2.5:7b", temperature=0.7, base_seed=1000, num_predict=512, num_ctx=4096
)
DEFAULT_EMBED_MODEL = "nomic-embed-text"


def model_params_from_env(env: Mapping[str, str]) -> ModelParams:
    d = DEFAULT_MODEL_PARAMS
    return ModelParams(
        model=env.get("LLM_MODEL", d.model),
        temperature=float(env.get("LLM_TEMPERATURE", d.temperature)),
        base_seed=int(env.get("LLM_BASE_SEED", d.base_seed)),
        num_predict=int(env.get("LLM_NUM_PREDICT", d.num_predict)),
        num_ctx=int(env.get("LLM_NUM_CTX", d.num_ctx)),
    )
