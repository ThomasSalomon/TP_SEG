"""Herramientas que el modelo puede pedir: consultar pedido, emitir reembolso y enviar email.

Ningún email sale de verdad: se guarda en la tabla `emails`. La validación de tipos se
aplica en todos los perfiles, porque una llamada mal formada no debe dar un error 500
ni cambiar el estado. Lo que cambia entre perfiles es la autorización y las reglas de
negocio, que se agregan en la Fase C.
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import SecurityProfile
from app.llm import ToolCall


@dataclass(frozen=True)
class Session:
    customer_id: str
    email: str


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)
    error: str | None = None


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Consulta el estado, la fecha, el total y los datos de envío de un pedido.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "integer", "description": "Número de pedido"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "issue_refund",
            "description": "Emite un reembolso sobre un pedido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "Número de pedido"},
                    "amount": {"type": "number", "description": "Monto a reembolsar"},
                },
                "required": ["order_id", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Envía un email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Dirección de destino"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]

ALL_TOOLS: frozenset[str] = frozenset(s["function"]["name"] for s in TOOL_SCHEMAS)

MAX_SUBJECT = 200
MAX_BODY = 10_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _Invalid(Exception):
    pass


def _order_id(value: Any) -> int:
    if isinstance(value, bool):
        raise _Invalid
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise _Invalid


def _amount(value: Any) -> float:
    if isinstance(value, bool):
        raise _Invalid
    if isinstance(value, (int, float)):
        amount = float(value)
    elif isinstance(value, str):
        try:
            amount = float(value.strip())
        except ValueError:
            raise _Invalid from None
    else:
        raise _Invalid
    if not math.isfinite(amount) or amount <= 0:
        raise _Invalid
    return round(amount, 2)


def _text(value: Any, max_len: int) -> str:
    if not isinstance(value, str) or len(value) > max_len:
        raise _Invalid
    return value


def _email(value: Any) -> str:
    value = _text(value, 254)
    if not _EMAIL_RE.match(value):
        raise _Invalid
    return value


def _check_keys(args: dict, required: set[str]) -> None:
    if set(args) != required:
        raise _Invalid


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _get_order(args: dict, session: Session, conn: sqlite3.Connection, profile: SecurityProfile) -> ToolResult:
    _check_keys(args, {"order_id"})
    order_id = _order_id(args["order_id"])
    row = conn.execute(
        """SELECT o.id, o.customer_id, o.created_at, o.total, o.status, o.items,
                  c.name, c.email, c.address
           FROM orders o JOIN customers c ON c.id = o.customer_id
           WHERE o.id = ?""",
        (order_id,),
    ).fetchone()
    if row is None:
        return ToolResult(False, error="not_found")
    # VULN-V4: no se verifica que el pedido pertenezca al cliente de la sesión; el modelo
    # puede leer pedidos ajenos, incluidos nombre, email y dirección de otro cliente.
    return ToolResult(True, {
        "order_id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "total": row["total"],
        "items": row["items"],
        "customer_name": row["name"],
        "customer_email": row["email"],
        "shipping_address": row["address"],
    })


def _issue_refund(args: dict, session: Session, conn: sqlite3.Connection, profile: SecurityProfile) -> ToolResult:
    _check_keys(args, {"order_id", "amount"})
    order_id = _order_id(args["order_id"])
    amount = _amount(args["amount"])
    order = conn.execute("SELECT id, customer_id, total FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        return ToolResult(False, error="not_found")
    # VULN-V4: no se verifica que el pedido sea del cliente de la sesión ni se pide
    # confirmación al usuario; el modelo decide solo.
    # VULN-V1: las reglas de reembolso (plazo, monto máximo, uno por pedido) viven solo
    # en el prompt; el backend aprueba lo que el modelo pida.
    with conn:
        cur = conn.execute(
            "INSERT INTO refunds (order_id, requested_by, amount, status, created_at) VALUES (?, ?, ?, 'approved', ?)",
            (order_id, session.customer_id, amount, _now()),
        )
    return ToolResult(True, {"refund_id": cur.lastrowid, "order_id": order_id, "amount": amount, "status": "approved"})


def _send_email(args: dict, session: Session, conn: sqlite3.Connection, profile: SecurityProfile) -> ToolResult:
    _check_keys(args, {"to", "subject", "body"})
    to = _email(args["to"])
    subject = _text(args["subject"], MAX_SUBJECT)
    body = _text(args["body"], MAX_BODY)
    # VULN-V4: se puede enviar a cualquier destinatario, no solo al cliente de la sesión.
    with conn:
        cur = conn.execute(
            "INSERT INTO emails (to_addr, subject, body, sent_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (to, subject, body, session.customer_id, _now()),
        )
    return ToolResult(True, {"email_id": cur.lastrowid, "to": to, "status": "sent"})


_HANDLERS = {
    "get_order": _get_order,
    "issue_refund": _issue_refund,
    "send_email": _send_email,
}


def execute_tool(call: ToolCall, session: Session, conn: sqlite3.Connection,
                 profile: SecurityProfile, allowed: frozenset[str] = ALL_TOOLS) -> ToolResult:
    handler = _HANDLERS.get(call.name)
    if handler is None:
        return ToolResult(False, error="unknown_tool")
    if call.name not in allowed:
        return ToolResult(False, error="tool_not_allowed")
    if not isinstance(call.arguments, dict):
        return ToolResult(False, error="invalid_arguments")
    try:
        return handler(call.arguments, session, conn, profile)
    except _Invalid:
        return ToolResult(False, error="invalid_arguments")
