"""Registros de ejecución (JSONL) compartidos por el runner y el resumen estadístico.

Están en un módulo aparte para que el resumen pueda leerlos sin importar Chroma ni la app.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Literal

Status = Literal["success", "blocked", "error"]


@dataclass(frozen=True)
class RunRecord:
    attack_id: str
    vuln: str
    origin: str
    profile: str
    rep: int
    seed: int
    model: str
    model_digest: str
    temperature: float
    git_sha: str
    status: Status
    error: str | None
    latency_ms: int
    replies: list[str]
    tool_log: list[dict]

    def key(self) -> tuple[str, str, int]:
        return (self.attack_id, self.profile, self.rep)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


_FIELDS = {f.name for f in fields(RunRecord)}


def read_raw(path: Path) -> list[RunRecord]:
    """Todos los registros del archivo, en orden. Ignora una última línea cortada por un corte de luz."""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break  # escritura interrumpida: esa repetición se vuelve a ejecutar
            raise ValueError(f"{path}: línea {i + 1} no es JSON válido") from None
        records.append(RunRecord(**{k: v for k, v in data.items() if k in _FIELDS}))
    return records


def latest(records: Iterable[RunRecord]) -> list[RunRecord]:
    """Un registro por (ataque, perfil, repetición): un resultado válido gana a un error y,
    entre iguales, el más reciente. Así un reintento de un error reemplaza al error."""
    best: dict[tuple, RunRecord] = {}
    for r in records:
        prev = best.get(r.key())
        if prev is None or not (prev.status != "error" and r.status == "error"):
            best[r.key()] = r
    return list(best.values())


def read_records(path: Path) -> list[RunRecord]:
    return latest(read_raw(path))
