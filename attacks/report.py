"""Resumen estadístico de los registros del runner.

- La tasa de éxito se calcula sobre las repeticiones **válidas**: los errores (modelo caído,
  timeout) quedan fuera del denominador y se informan aparte.
- Cada tasa lleva su intervalo de confianza de Wilson al 95%: "0 de 50" no es riesgo cero,
  su intervalo llega hasta 7,1%.
- La diferencia entre `vulnerable` y cada otro perfil se prueba con el test exacto de Fisher.
- Los ataques `dev` y `heldout` se informan por separado, y la batería de utilidad aparte.

Uso:
    python -m attacks.report results/final/main.jsonl --strict --min-valid 50 --out results/final/
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from scipy.stats import fisher_exact

from attacks.records import RunRecord, latest, read_raw

BASELINE = "vulnerable"


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0 or k < 0 or k > n:
        raise ValueError(f"Datos inválidos para Wilson: k={k}, n={n}")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    low = 0.0 if k == 0 else max(0.0, center - half)
    high = 1.0 if k == n else min(1.0, center + half)
    return low, high


def fisher_p(k1: int, n1: int, k2: int, n2: int) -> float:
    """p-valor bilateral del test exacto de Fisher para k1/n1 contra k2/n2."""
    return float(fisher_exact([[k1, n1 - k1], [k2, n2 - k2]], alternative="two-sided").pvalue)


@dataclass(frozen=True)
class SummaryRow:
    attack_id: str
    vuln: str
    origin: str
    profile: str
    successes: int
    valid: int
    errors: int
    rate: float
    ci_low: float
    ci_high: float


def summarize(records: Iterable[RunRecord]) -> list[SummaryRow]:
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for r in latest(records):
        groups[(r.attack_id, r.profile)].append(r)
    rows = []
    for (attack_id, profile), recs in sorted(groups.items()):
        successes = sum(r.status == "success" for r in recs)
        valid = sum(r.status != "error" for r in recs)
        errors = len(recs) - valid
        if valid:
            rate = successes / valid
            ci_low, ci_high = wilson_interval(successes, valid)
        else:
            rate = ci_low = ci_high = math.nan
        rows.append(SummaryRow(attack_id, recs[0].vuln, recs[0].origin, profile,
                               successes, valid, errors, rate, ci_low, ci_high))
    return rows


# --- problemas de calidad de los datos ------------------------------------------

def parameter_sets(records: list[RunRecord]) -> dict[str, list[str]]:
    keys = ("model", "model_digest", "temperature", "git_sha")
    return {k: sorted({str(getattr(r, k)) for r in records}) for k in keys}


def data_problems(records: list[RunRecord], rows: list[SummaryRow], min_valid: int) -> list[str]:
    problems = []
    for name, values in parameter_sets(records).items():
        if len(values) > 1:
            problems.append(f"Parámetros mezclados: {name} tiene {len(values)} valores ({', '.join(values)})")
    if any(r.git_sha == "unknown" for r in records):
        problems.append("Hay registros con git_sha=unknown: no se puede saber qué código se midió")
    for row in rows:
        if row.valid < min_valid:
            problems.append(f"{row.attack_id} / {row.profile}: {row.valid} repeticiones válidas (mínimo {min_valid})")
    return problems


# --- salida ---------------------------------------------------------------------

def _pct(x: float) -> str:
    return "—" if math.isnan(x) else f"{x * 100:.1f}%".replace(".", ",")


def _p(x: float) -> str:
    return "< 0,001" if x < 0.001 else f"{x:.3f}".replace(".", ",")


def _table(rows: list[SummaryRow], label: str) -> list[str]:
    lines = [f"| Caso | Vuln | Perfil | {label} / válidas | Tasa | IC 95% (Wilson) | Errores |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r.attack_id} | {r.vuln} | {r.profile} | {r.successes} / {r.valid} | {_pct(r.rate)} | "
                     f"[{_pct(r.ci_low)}; {_pct(r.ci_high)}] | {r.errors} |")
    return lines


def _comparisons(rows: list[SummaryRow]) -> list[str]:
    by_attack: dict[str, dict[str, SummaryRow]] = defaultdict(dict)
    for r in rows:
        by_attack[r.attack_id][r.profile] = r
    lines = []
    for attack_id, profiles in sorted(by_attack.items()):
        base = profiles.get(BASELINE)
        if base is None or not base.valid:
            continue
        for name, other in sorted(profiles.items()):
            if name == BASELINE or not other.valid:
                continue
            p = fisher_p(base.successes, base.valid, other.successes, other.valid)
            lines.append(f"| {attack_id} | {name} | {_pct(base.rate)} | {_pct(other.rate)} | {_p(p)} |")
    if not lines:
        return []
    return ["## Comparación contra `vulnerable` (test exacto de Fisher, bilateral)", "",
            "| Caso | Perfil | Tasa en vulnerable | Tasa en el perfil | p |", "|---|---|---|---|---|",
            *lines, ""]


def render_markdown(records: list[RunRecord], rows: list[SummaryRow]) -> str:
    out = ["# Resumen de resultados", "", "## Parámetros encontrados", ""]
    for name, values in parameter_sets(records).items():
        out.append(f"- `{name}`: {', '.join(f'`{v}`' for v in values)}")
    mixed = [n for n, v in parameter_sets(records).items() if len(v) > 1]
    if mixed:
        out += ["", f"> **Atención:** hay registros con distintos valores de {', '.join(mixed)}. "
                    "Las tasas mezclan configuraciones distintas y no son comparables."]
    out.append("")
    attacks = [r for r in rows if r.vuln != "UTIL"]
    for origin in ("dev", "heldout"):
        subset = [r for r in attacks if r.origin == origin]
        if subset:
            out += [f"## Ataques (origen `{origin}`)", "", *_table(subset, "Éxitos"), ""]
    utility = [r for r in rows if r.vuln == "UTIL"]
    if utility:
        out += ["## Utilidad (tareas legítimas)", "",
                "Acá un éxito significa que la tarea legítima se completó: se busca una tasa **alta** en ambos perfiles.",
                "", *_table(utility, "Completadas"), ""]
    out += _comparisons(rows)
    return "\n".join(out) + "\n"


def write_csv(rows: list[SummaryRow], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[fl.name for fl in fields(SummaryRow)])
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resume los registros JSONL del runner.")
    ap.add_argument("inputs", nargs="+", type=Path, help="Uno o más archivos JSONL")
    ap.add_argument("--out", type=Path, help="Directorio para summary.csv y summary.md")
    ap.add_argument("--strict", action="store_true",
                    help="Falla si faltan repeticiones válidas, si hay git_sha=unknown o parámetros mezclados")
    ap.add_argument("--min-valid", type=int, default=50)
    args = ap.parse_args(argv)

    raw = [r for path in args.inputs for r in read_raw(path)]
    records = latest(raw)
    if not records:
        print("No hay registros para resumir.", file=sys.stderr)
        return 1
    rows = summarize(records)
    markdown = render_markdown(records, rows)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        write_csv(rows, args.out / "summary.csv")
        (args.out / "summary.md").write_text(markdown, encoding="utf-8")
        print(f"Resumen escrito en {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(markdown)

    problems = data_problems(records, rows, args.min_valid)
    for p in problems:
        print(f"{'ERROR' if args.strict else 'Aviso'}: {p}", file=sys.stderr)
    return 1 if args.strict and problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
