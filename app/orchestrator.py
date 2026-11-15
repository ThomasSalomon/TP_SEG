"""Ciclo pedido → herramienta → respuesta.

`MAX_TOOL_ROUNDS` no convierte al asistente en un agente multipaso: solo acota cuántas
veces seguidas el modelo puede pedir herramientas en un mismo turno, para que un modelo
que entra en un ciclo no consuma recursos sin fin.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field

from app.config import SecurityProfile
from app.llm import LLMClient, ToolCall
from app.prompts import build_messages
from app.rag import Chunk, KnowledgeBase
from app.tools import ALL_TOOLS, TOOL_SCHEMAS, Session, ToolResult, execute_tool

MAX_TOOL_ROUNDS = 3
RETRIEVE_K = 3
# Con contenido no confiable en el contexto, solo se ofrecen herramientas de lectura.
READ_ONLY_TOOLS: frozenset[str] = frozenset({"get_order"})
FALLBACK_REPLY = "Perdón, no pude completar tu consulta. ¿Podés reformularla?"


@dataclass(frozen=True)
class ToolEvent:
    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class ChatResult:
    reply: str
    tool_log: list[ToolEvent] = field(default_factory=list)
    pending_confirmation: str | None = None


@dataclass(frozen=True)
class Deps:
    llm: LLMClient
    kb: KnowledgeBase
    conn: sqlite3.Connection


def allowed_tools(chunks: list[Chunk], profile: SecurityProfile) -> frozenset[str]:
    """Herramientas que se pueden usar en este turno, según la confianza del contexto.

    FIX-V2 (control principal): si el contexto tiene una reseña, que escribió cualquiera,
    el modelo no puede emitir reembolsos ni enviar emails en ese turno. No depende de que el
    modelo resista la inyección ni de que el filtro de reseñas la detecte.
    """
    if profile.fix_v2 and any(c.source == "review" for c in chunks):
        return READ_ONLY_TOOLS
    # VULN-V2: sin la corrección, una reseña recuperada convive con todas las herramientas.
    return ALL_TOOLS


def _tool_message(event: ToolEvent) -> dict:
    payload = {"ok": event.result.ok, "data": event.result.data, "error": event.result.error}
    return {"role": "tool", "tool_name": event.call.name, "content": json.dumps(payload, ensure_ascii=False)}


def _assistant_with_calls(content: str, calls: list[ToolCall]) -> dict:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in calls],
    }


def handle_message(message: str, history: list[dict], session: Session,
                   deps: Deps, profile: SecurityProfile, seed: int) -> ChatResult:
    """Procesa un mensaje del cliente. `LLMUnavailable` se propaga: no es un ataque bloqueado."""
    chunks = deps.kb.retrieve(message, k=RETRIEVE_K)
    messages = build_messages(history, message, chunks, session, profile)
    allowed = allowed_tools(chunks, profile)
    schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in allowed]
    tool_log: list[ToolEvent] = []

    for round_ in range(MAX_TOOL_ROUNDS + 1):
        last_round = round_ == MAX_TOOL_ROUNDS
        reply = deps.llm.chat(messages, [] if last_round else schemas, seed=seed)
        if not reply.tool_calls or last_round:
            return ChatResult(reply.content.strip() or FALLBACK_REPLY, tool_log, _pending_token(tool_log))
        messages.append(_assistant_with_calls(reply.content, reply.tool_calls))
        for call in reply.tool_calls:
            event = ToolEvent(call, execute_tool(call, session, deps.conn, profile, allowed))
            tool_log.append(event)
            messages.append(_tool_message(event))

    raise AssertionError("inalcanzable")  # pragma: no cover


def _pending_token(tool_log: list[ToolEvent]) -> str | None:
    """FIX-V4: el token del último reembolso pendiente del turno, para el botón de la UI.

    Si en un turno quedan varios pendientes, la UI ofrece confirmar solo el último; los demás
    no se aprueban nunca.
    """
    tokens = [e.result.confirmation_token for e in tool_log if e.result.confirmation_token]
    return tokens[-1] if tokens else None


def tool_event_to_dict(event: ToolEvent) -> dict:
    """Forma serializable de un evento, para el JSONL del arnés (sin el token de confirmación)."""
    result = asdict(event.result)
    result.pop("confirmation_token", None)
    return {"call": asdict(event.call), "result": result}
