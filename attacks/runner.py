"""Ejecuta la batería de ataques contra el modelo real y registra cada repetición.

- Cada repetición usa una base SQLite nueva, así un reembolso de una repetición no
  contamina la siguiente.
- La base de conocimiento se arma una vez por ataque y perfil (recuperar no modifica nada),
  con las reseñas `setup_reviews` del ataque cargadas con el perfil que se mide.
- La semilla es `base_seed + rep`, igual en todos los perfiles: la comparación es pareada.
- Si el modelo no responde, la repetición queda como `error`, no como `blocked`, y se
  reintenta al volver a ejecutar el mismo comando.
- Cada registro se escribe y se sincroniza a disco antes de seguir: un corte no pierde lo hecho.

Uso (dentro de la red del laboratorio):
    python -m attacks.runner --battery attacks/battery --profiles vulnerable,segura --reps 50 \
        --out results/final/main.jsonl
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.config import DEFAULT_EMBED_MODEL, PROFILES, ModelParams, SecurityProfile, model_params_from_env
from app.db import CUSTOMERS, connect, init_db
from app.llm import LLMClient, LLMUnavailable, OllamaClient
from app.main import KB_DIR
from app.orchestrator import Deps, ToolEvent, handle_message, tool_event_to_dict
from app.rag import KnowledgeBase
from app.tools import Session
from attacks.oracles import ORACLES, Evidence
from attacks.records import RunRecord, read_raw
from attacks.schema import Attack, load_battery

__all__ = ["RunContext", "RunRecord", "main", "run_battery", "run_once", "seed_for"]

_EMAILS = {c[0]: c[2] for c in CUSTOMERS}


@dataclass(frozen=True)
class RunContext:
    llm: LLMClient
    embed: Callable[[list[str]], list[list[float]]]
    params: ModelParams
    model_digest: str
    git_sha: str
    workdir: Path
    # Bases de conocimiento ya armadas, por (ataque, perfil). Es estado interno del runner.
    _kb_cache: dict = field(default_factory=dict, compare=False, repr=False)


def seed_for(base_seed: int, rep: int) -> int:
    return base_seed + rep


def _knowledge_base(attack: Attack, profile: SecurityProfile, ctx: RunContext) -> KnowledgeBase:
    key = (attack.id, profile.name)
    if key not in ctx._kb_cache:
        kb = KnowledgeBase(None, ctx.embed)
        kb.ingest_faq(KB_DIR)
        for review in attack.setup_reviews:
            kb.add_review(review, profile)  # con la corrección de V2 la ingesta puede rechazarla
        ctx._kb_cache[key] = kb
    return ctx._kb_cache[key]


def _record(attack, profile, rep, seed, ctx, status, error, t0, replies, tool_log) -> RunRecord:
    return RunRecord(
        attack_id=attack.id, vuln=attack.vuln, origin=attack.origin, profile=profile.name,
        rep=rep, seed=seed, model=ctx.params.model, model_digest=ctx.model_digest,
        temperature=ctx.params.temperature, git_sha=ctx.git_sha, status=status, error=error,
        latency_ms=int((time.perf_counter() - t0) * 1000), replies=replies,
        tool_log=[tool_event_to_dict(e) for e in tool_log],
    )


def run_once(attack: Attack, profile: SecurityProfile, rep: int, ctx: RunContext) -> RunRecord:
    seed = seed_for(ctx.params.base_seed, rep)
    t0 = time.perf_counter()
    replies: list[str] = []
    tool_log: list[ToolEvent] = []
    ctx.workdir.mkdir(parents=True, exist_ok=True)
    db_path = ctx.workdir / f"run-{uuid.uuid4().hex}.sqlite3"
    conn = None
    try:
        init_db(db_path, datetime.now(UTC))
        conn = connect(db_path)
        deps = Deps(llm=ctx.llm, kb=_knowledge_base(attack, profile, ctx), conn=conn)
        session = Session(attack.session, _EMAILS[attack.session])
        history: list[dict] = []
        for turn in attack.turns:
            result = handle_message(turn, history, session, deps, profile, seed)
            replies.append(result.reply)
            tool_log.extend(result.tool_log)
            history += [{"role": "user", "content": turn}, {"role": "assistant", "content": result.reply}]
        evidence = Evidence(replies=replies, tool_log=tool_log, conn=conn, attacker_id=attack.session)
        success = ORACLES[attack.oracle.type](evidence, attack.oracle.args)
        return _record(attack, profile, rep, seed, ctx, "success" if success else "blocked", None,
                       t0, replies, tool_log)
    except LLMUnavailable as exc:
        return _record(attack, profile, rep, seed, ctx, "error", f"llm_unavailable: {exc}", t0, replies, tool_log)
    except Exception as exc:  # un fallo inesperado no debe tirar abajo horas de medición
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return _record(attack, profile, rep, seed, ctx, "error", f"internal: {detail}", t0, replies, tool_log)
    finally:
        if conn is not None:
            conn.close()
        db_path.unlink(missing_ok=True)


def run_battery(attacks: list[Attack], profiles: list[SecurityProfile], reps: int,
                ctx: RunContext, out: Path) -> None:
    """Ejecuta lo que falta. Las repeticiones con resultado válido no se repiten; los errores sí.

    Recorre repetición por repetición, así un corte deja todos los ataques con una cantidad
    pareja de repeticiones.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _drop_partial_tail(out)
    done = {r.key() for r in read_raw(out) if r.status != "error"}
    pending = [(rep, a, p) for rep in range(reps) for a in attacks for p in profiles
               if (a.id, p.name, rep) not in done]
    total = len(pending)
    with out.open("a", encoding="utf-8") as f:
        for i, (rep, attack, profile) in enumerate(pending, 1):
            record = run_once(attack, profile, rep, ctx)
            f.write(record.to_json() + "\n")
            f.flush()
            os.fsync(f.fileno())
            print(f"[{i}/{total}] {attack.id} {profile.name} rep={rep} -> {record.status}"
                  f" ({record.latency_ms} ms){' ' + record.error if record.error else ''}",
                  file=sys.stderr, flush=True)


def _drop_partial_tail(path: Path) -> None:
    """Si un corte dejó la última línea sin terminar, la descarta antes de agregar registros.

    Sin esto, el próximo registro se pega a la línea cortada y el archivo deja de poder leerse.
    Esa repetición no quedó registrada, así que se vuelve a ejecutar.
    """
    if not path.exists():
        return
    data = path.read_bytes()
    if not data or data.endswith(b"\n"):
        return
    with path.open("r+b") as f:
        f.truncate(data.rfind(b"\n") + 1)


def _parse_profiles(value: str) -> list[SecurityProfile]:
    names = [n.strip() for n in value.split(",") if n.strip()]
    unknown = [n for n in names if n not in PROFILES]
    if not names or unknown:
        raise argparse.ArgumentTypeError(f"perfiles desconocidos: {unknown or value!r}")
    return [PROFILES[n] for n in names]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ejecuta la batería de ataques contra el modelo real.")
    ap.add_argument("--battery", type=Path, required=True, help="Archivo YAML o directorio")
    ap.add_argument("--profiles", type=_parse_profiles, required=True, help="p. ej. vulnerable,segura")
    ap.add_argument("--reps", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True, help="Archivo JSONL (se retoma si existe)")
    args = ap.parse_args(argv)

    attacks = load_battery(args.battery)
    env = os.environ
    params = model_params_from_env(env)
    llm = OllamaClient(env.get("OLLAMA_BASE_URL", "http://ollama:11434"), params,
                       env.get("EMBED_MODEL", DEFAULT_EMBED_MODEL), float(env.get("LLM_TIMEOUT_S", "300")))
    try:
        digest = llm.model_digest()
    except (LLMUnavailable, LookupError) as exc:
        print(f"No se pudo consultar el modelo {params.model!r}: {exc}", file=sys.stderr)
        return 1
    git_sha = env.get("GIT_SHA") or "unknown"
    if git_sha == "unknown":
        print("Aviso: GIT_SHA no está definido; los registros quedan con git_sha=unknown "
              "y el resumen --strict los va a rechazar.", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="runner-") as tmp:
        ctx = RunContext(llm=llm, embed=llm.embed, params=params, model_digest=digest,
                         git_sha=git_sha, workdir=Path(tmp))
        run_battery(attacks, args.profiles, args.reps, ctx, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
