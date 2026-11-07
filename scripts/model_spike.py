"""Prueba rápida para elegir el modelo (tarea 2 del plan).

Con 10 consultas benignas en español mide, para un modelo servido por Ollama:
latencia, tool calls correctas, reproducibilidad con la misma semilla, variación con
semillas distintas y si el contexto llega entero (`prompt_eval_count`).

Estos datos sirven para elegir el modelo; no forman parte de la medición del TP.

Uso:
    uv run python scripts/model_spike.py --model qwen2.5:7b --reps 10
    uv run python scripts/model_spike.py --model llama3.2:3b --reps 10 --base-url http://127.0.0.1:11434
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DEFAULT_EMBED_MODEL, DEFAULT_MODEL_PARAMS, ModelParams  # noqa: E402
from app.llm import LLMClient, LLMReply, LLMUnavailable, OllamaClient  # noqa: E402
from app.tools import TOOL_SCHEMAS  # noqa: E402

SYSTEM = (
    "Sos el asistente de atención al cliente de TiendaFicticia. Respondé en español, en pocas "
    "oraciones. Si el cliente pregunta por un pedido concreto, usá get_order. Si pide un "
    "reembolso de un pedido, usá issue_refund. Si pide que le manden algo por email, usá "
    "send_email. Si es una consulta general, respondé sin herramientas. "
    "El cliente de esta sesión es alice (alice@example.test)."
)

# (consulta, herramienta esperada o None si no debe usar ninguna)
QUERIES: list[tuple[str, str | None]] = [
    ("¿Dónde está mi pedido 1001?", "get_order"),
    ("Quiero saber el estado del pedido número 1002", "get_order"),
    ("¿Cuánto pagué en el pedido 1001?", "get_order"),
    ("Quiero que me devuelvan 20 pesos del pedido 1001, llegó rayado", "issue_refund"),
    ("Pedí el reembolso total del pedido 1001 por favor", "issue_refund"),
    ("Mandame por email a alice@example.test un resumen del pedido 1001", "send_email"),
    ("¿Cuántos días tengo para devolver un producto?", None),
    ("¿Qué medios de pago aceptan?", None),
    ("¿Hacen envíos a todo el país?", None),
    ("Hola, ¿cómo andás?", None),
]


@dataclass
class QueryResult:
    query: str
    expected: str | None
    tool_ok: bool
    latency_ms: float
    reproducible: bool
    distinct_outputs: int
    prompt_eval_count: int | None
    approx_prompt_tokens: int
    error: str | None = None


def _signature(reply: LLMReply) -> str:
    calls = [(c.name, json.dumps(c.arguments, sort_keys=True)) for c in reply.tool_calls]
    return json.dumps([reply.content, calls], ensure_ascii=False)


def _tool_ok(reply: LLMReply, expected: str | None) -> bool:
    names = [c.name for c in reply.tool_calls]
    return names == [] if expected is None else expected in names


def run_spike(llm: LLMClient, base_seed: int, reps: int) -> list[QueryResult]:
    results = []
    for query, expected in QUERIES:
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": query}]
        approx = (len(SYSTEM) + len(query) + len(json.dumps(TOOL_SCHEMAS))) // 4
        try:
            t0 = time.perf_counter()
            first = llm.chat(messages, TOOL_SCHEMAS, seed=base_seed)
            latency = (time.perf_counter() - t0) * 1000
            again = llm.chat(messages, TOOL_SCHEMAS, seed=base_seed)
            varied = [llm.chat(messages, TOOL_SCHEMAS, seed=base_seed + r) for r in range(1, reps)]
        except LLMUnavailable as exc:
            results.append(QueryResult(query, expected, False, 0, False, 0, None, approx, error=str(exc)))
            continue
        outputs = [first] + varied
        results.append(QueryResult(
            query=query,
            expected=expected,
            tool_ok=_tool_ok(first, expected),
            latency_ms=latency,
            reproducible=_signature(first) == _signature(again),
            distinct_outputs=len({_signature(o) for o in outputs}),
            prompt_eval_count=first.prompt_eval_count,
            approx_prompt_tokens=approx,
        ))
    return results


# Medición obligatoria de la tarea 15: 28 casos × 50 repeticiones × 2 perfiles.
MANDATORY_RUNS = 28 * 50 * 2


def estimate_hours(mean_latency_ms: float, turns_per_case: float = 1.5, runs: int = MANDATORY_RUNS) -> float:
    """Horas de medición estimadas. `turns_per_case` cubre ataques de varios turnos y rondas de herramientas."""
    return runs * turns_per_case * mean_latency_ms / 1000 / 3600


def render(results: list[QueryResult], model: str, digest: str, params: ModelParams) -> str:
    ok = [r for r in results if r.error is None]
    lines = [
        f"## {model}",
        "",
        f"- digest: `{digest}`",
        f"- temperatura: {params.temperature}, base_seed: {params.base_seed}, "
        f"num_predict: {params.num_predict}, num_ctx: {params.num_ctx}",
        "",
        "| Consulta | Esperada | Tool OK | Latencia (ms) | Reproducible | Salidas distintas | prompt_eval_count | ~tokens enviados |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.error:
            lines.append(f"| {r.query} | {r.expected or '-'} | ERROR: {r.error} | | | | | |")
        else:
            lines.append(
                f"| {r.query} | {r.expected or '-'} | {'sí' if r.tool_ok else 'no'} | {r.latency_ms:.0f} | "
                f"{'sí' if r.reproducible else 'no'} | {r.distinct_outputs} | {r.prompt_eval_count} | {r.approx_prompt_tokens} |"
            )
    if ok:
        tool_rate = sum(r.tool_ok for r in ok) / len(ok)
        repro = sum(r.reproducible for r in ok) / len(ok)
        varied = sum(r.distinct_outputs > 1 for r in ok) / len(ok)
        mean_lat = statistics.mean(r.latency_ms for r in ok)
        p95 = sorted(r.latency_ms for r in ok)[max(0, int(len(ok) * 0.95) - 1)]
        lines += [
            "",
            f"- Tool calls correctas: **{tool_rate:.0%}** (criterio: ≥ 90%)",
            f"- Reproducible con la misma semilla: **{repro:.0%}** (criterio: 100%)",
            f"- Consultas con salidas variadas entre semillas: **{varied:.0%}** (criterio: > 0%)",
            f"- Latencia media: {mean_lat:.0f} ms, p95 aprox.: {p95:.0f} ms",
            f"- Costo estimado de la medición obligatoria ({MANDATORY_RUNS} ejecuciones, 1,5 llamadas por caso): "
            f"**{estimate_hours(mean_lat):.1f} h**",
        ]
    if len(ok) < len(results):
        lines.append(f"- Consultas con error: {len(results) - len(ok)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--base-url", default="http://127.0.0.1:11434")
    ap.add_argument("--temperature", type=float, default=DEFAULT_MODEL_PARAMS.temperature)
    ap.add_argument("--base-seed", type=int, default=DEFAULT_MODEL_PARAMS.base_seed)
    ap.add_argument("--num-predict", type=int, default=DEFAULT_MODEL_PARAMS.num_predict)
    ap.add_argument("--num-ctx", type=int, default=DEFAULT_MODEL_PARAMS.num_ctx)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--out", type=Path, help="Archivo Markdown donde agregar la tabla")
    args = ap.parse_args(argv)

    params = ModelParams(args.model, args.temperature, args.base_seed, args.num_predict, args.num_ctx)
    llm = OllamaClient(args.base_url, params, DEFAULT_EMBED_MODEL, args.timeout)
    try:
        digest = llm.model_digest()
    except (LLMUnavailable, LookupError) as exc:
        print(f"No se pudo consultar el modelo: {exc}", file=sys.stderr)
        return 1
    table = render(run_spike(llm, args.base_seed, args.reps), args.model, digest, params)
    print(table)
    if args.out:
        with args.out.open("a", encoding="utf-8") as f:
            f.write("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
