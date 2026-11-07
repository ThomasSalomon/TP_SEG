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
from app.rag import KnowledgeBase
from app.tools import TOOL_SCHEMAS, Session, ToolResult, execute_tool

MAX_TOOL_ROUNDS = 3
RETRIEVE_K = 3
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
    tool_log: list[ToolEvent] = []

    for round_ in range(MAX_TOOL_ROUNDS + 1):
        last_round = round_ == MAX_TOOL_ROUNDS
        reply = deps.llm.chat(messages, [] if last_round else TOOL_SCHEMAS, seed=seed)
        if not reply.tool_calls or last_round:
            return ChatResult(reply.content.strip() or FALLBACK_REPLY, tool_log)
        messages.append(_assistant_with_calls(reply.content, reply.tool_calls))
        for call in reply.tool_calls:
            event = ToolEvent(call, execute_tool(call, session, deps.conn, profile))
            tool_log.append(event)
            messages.append(_tool_message(event))

    raise AssertionError("inalcanzable")  # pragma: no cover


def tool_event_to_dict(event: ToolEvent) -> dict:
    """Forma serializable de un evento, para el JSONL del arnés."""
    return {"call": asdict(event.call), "result": asdict(event.result)}
