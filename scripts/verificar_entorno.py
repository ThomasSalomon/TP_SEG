"""Verifica que esta máquina tenga el entorno de referencia del TP (ver INSTALACION.md).

Controla la versión de Python, que Ollama responda, su versión y que los modelos
instalados tengan exactamente el digest elegido en docs/decisiones/modelo.md. También
informa Docker y el commit actual.

Uso:
    uv run python scripts/verificar_entorno.py
    uv run python scripts/verificar_entorno.py --base-url http://127.0.0.1:11434

Termina con código 1 si algo obligatorio falla. Una ADVERTENCIA no impide trabajar, pero
la máquina de la medición final tiene que dar todo OK.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import EXPECTED_OLLAMA_VERSION, MODEL_DIGESTS  # noqa: E402

OK, WARN, FAIL = "OK", "ADVERTENCIA", "FALLA"
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def check_python(version: tuple[int, ...]) -> Check:
    v = ".".join(map(str, version[:3]))
    if tuple(version[:2]) == (3, 12):
        return Check("Python", OK, v)
    return Check("Python", FAIL, f"{v}; se necesita 3.12 (ejecutá con `uv run`, que usa el Python del proyecto)")


def check_ollama_version(version: str) -> Check:
    if version == EXPECTED_OLLAMA_VERSION:
        return Check("Versión de Ollama", OK, version)
    return Check("Versión de Ollama", WARN,
                 f"{version}; la de referencia es {EXPECTED_OLLAMA_VERSION}. Sirve para desarrollar, "
                 "pero la medición final tiene que hacerse con la versión de referencia")


def check_models(tags: dict) -> list[Check]:
    installed = {}
    for m in tags.get("models", []):
        for key in (m.get("name"), m.get("model")):
            if key:
                installed[key] = m.get("digest")
                if key.endswith(":latest"):
                    installed[key.removesuffix(":latest")] = m.get("digest")
    checks = []
    for name, expected in MODEL_DIGESTS.items():
        got = installed.get(name)
        if got is None:
            checks.append(Check(f"modelo {name}", FAIL, f"no está instalado: ejecutá `ollama pull {name}`"))
        elif got != expected:
            checks.append(Check(f"modelo {name}", FAIL,
                                f"digest {got[:12]} distinto del de referencia {expected[:12]}. "
                                f"Avisá al grupo antes de seguir: si el tag cambió en el registro, "
                                f"`ollama pull {name}` no alcanza para volver al modelo medido"))
        else:
            checks.append(Check(f"modelo {name}", OK, f"digest {got[:12]}"))
    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == FAIL for c in checks) else 0


def _run(cmd: list[str]) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def check_docker() -> Check:
    version = _run(["docker", "--version"])
    if version is None:
        return Check("Docker", WARN, "no está instalado; solo hace falta para el laboratorio con Compose")
    if _run(["docker", "info", "--format", "{{.ServerVersion}}"]) is None:
        return Check("Docker", WARN, f"{version}, pero el daemon no responde (¿Docker Desktop está iniciado?)")
    return Check("Docker", OK, version)


def check_git() -> Check:
    sha = _run(["git", "rev-parse", "--short", "HEAD"])
    if sha is None:
        return Check("Commit", WARN, "no se pudo leer el commit actual")
    dirty = _run(["git", "status", "--porcelain"])
    if dirty:
        return Check("Commit", WARN, f"{sha} con cambios sin commitear")
    return Check("Commit", OK, sha)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verifica el entorno de referencia del TP.")
    ap.add_argument("--base-url", default="http://127.0.0.1:11434", help="Servidor de Ollama")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = [check_python(sys.version_info)]
    try:
        with httpx.Client(timeout=10) as http:
            version = http.get(f"{args.base_url}/api/version").json()["version"]
            tags = http.get(f"{args.base_url}/api/tags").json()
        checks.append(Check("Ollama", OK, f"responde en {args.base_url}"))
        checks.append(check_ollama_version(version))
        checks += check_models(tags)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        checks.append(Check("Ollama", FAIL, f"no responde en {args.base_url} ({type(exc).__name__}). "
                                            "¿Está instalado y abierto?"))
    checks += [check_docker(), check_git()]

    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"[{c.status:^11}] {c.name:<{width}}  {c.detail}")
    code = exit_code(checks)
    print("\nEntorno OK." if code == 0 else "\nHay fallas: revisá INSTALACION.md antes de seguir.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
