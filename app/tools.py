"""Herramientas que el modelo puede pedir: consultar pedido, emitir reembolso y enviar email.

Ningún email sale de verdad: se guarda en la tabla `emails`. La validación de tipos se
aplica en todos los perfiles, porque una llamada mal formada no debe dar un error 500
ni cambiar el estado. Lo que cambia entre perfiles es la autorización y las reglas de
negocio, que se agregan en la Fase C.
"""

from __future__ import annotations

import math
import re
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import SecurityProfile
from app.guards import check_refund_policy
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
    # FIX-V4: token de confirmación de un reembolso pendiente. Va a la UI, nunca al modelo:
    # el orquestador solo le manda `ok`, `data` y `error`.
    confirmation_token: str | None = field(default=None, repr=False)


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



def _get_order(args: dict, session: Session, conn: sqlite3.Connection, profile: SecurityProfile,
               now: datetime) -> ToolResult:
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
    if profile.fix_v4 and row["customer_id"] != session.customer_id:
        # FIX-V4: solo pedidos del cliente de la sesión. La identidad sale de `Session`,
        # nunca de lo que diga el modelo o el cliente en el chat.
        return ToolResult(False, error="forbidden")
    # VULN-V4: sin la corrección, no se verifica que el pedido pertenezca al cliente de la
    # sesión; el modelo puede leer pedidos ajenos, incluidos nombre, email y dirección.
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


def _issue_refund(args: dict, session: Session, conn: sqlite3.Connection, profile: SecurityProfile,
                  now: datetime) -> ToolResult:
    _check_keys(args, {"order_id", "amount"})
    order_id = _order_id(args["order_id"])
    amount = _amount(args["amount"])
    order = conn.execute("SELECT id, customer_id, total, created_at FROM orders WHERE id = ?",
                         (order_id,)).fetchone()
    if order is None:
        return ToolResult(False, error="not_found")
    if profile.fix_v4 and order["customer_id"] != session.customer_id:
        # FIX-V4: solo pedidos propios.
        return ToolResult(False, error="forbidden")
    if profile.fix_v1:
        # FIX-V1: plazo, monto máximo y un reembolso por pedido, aplicados en el backend. Un
        # reembolso pendiente de confirmación ya cuenta como el reembolso del pedido.
        already = conn.execute(
            "SELECT 1 FROM refunds WHERE order_id = ? AND status IN ('approved', 'pending_confirmation') LIMIT 1",
            (order_id,),
        ).fetchone() is not None
        reason = check_refund_policy(dict(order), amount, already, now)
        if reason is not None:
            return ToolResult(False, error=reason)
    if profile.fix_v4:
        # FIX-V4: el reembolso queda pendiente hasta que el cliente lo confirme con un botón
        # de la UI (`confirm_refund`). El modelo no ve el token.
        token = secrets.token_urlsafe(24)
        with conn:
            cur = conn.execute(
                "INSERT INTO refunds (order_id, requested_by, amount, status, token, created_at) "
                "VALUES (?, ?, ?, 'pending_confirmation', ?, ?)",
                (order_id, session.customer_id, amount, token, now.isoformat()),
            )
        return ToolResult(True, {"refund_id": cur.lastrowid, "order_id": order_id, "amount": amount,
                                 "status": "pending_confirmation",
                                 "next_step": "El cliente tiene que confirmarlo con el botón de la pantalla."},
                          confirmation_token=token)
    # VULN-V4: sin la corrección, no se verifica que el pedido sea del cliente de la sesión
    # ni se pide confirmación al usuario; el modelo decide solo.
    # VULN-V1: sin la corrección, las reglas de reembolso (plazo, monto máximo, uno por pedido) viven solo
    # en el prompt; el backend aprueba lo que el modelo pida.
    with conn:
        cur = conn.execute(
            "INSERT INTO refunds (order_id, requested_by, amount, status, created_at) VALUES (?, ?, ?, 'approved', ?)",
            (order_id, session.customer_id, amount, now.isoformat()),
        )
    return ToolResult(True, {"refund_id": cur.lastrowid, "order_id": order_id, "amount": amount, "status": "approved"})


def _send_email(args: dict, session: Session, conn: sqlite3.Connection, profile: SecurityProfile,
                now: datetime) -> ToolResult:
    _check_keys(args, {"to", "subject", "body"})
    to = _email(args["to"])
    subject = _text(args["subject"], MAX_SUBJECT)
    body = _text(args["body"], MAX_BODY)
    if profile.fix_v4 and to.casefold() != session.email.casefold():
        # FIX-V4: el asistente solo le escribe al cliente de la sesión.
        return ToolResult(False, error="forbidden")
    # VULN-V4: sin la corrección, se puede enviar a cualquier destinatario.
    with conn:
        cur = conn.execute(
            "INSERT INTO emails (to_addr, subject, body, sent_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (to, subject, body, session.customer_id, now.isoformat()),
        )
    return ToolResult(True, {"email_id": cur.lastrowid, "to": to, "status": "sent"})


_HANDLERS = {
    "get_order": _get_order,
    "issue_refund": _issue_refund,
    "send_email": _send_email,
}


def execute_tool(call: ToolCall, session: Session, conn: sqlite3.Connection,
                 profile: SecurityProfile, allowed: frozenset[str] = ALL_TOOLS,
                 now: datetime | None = None) -> ToolResult:
    handler = _HANDLERS.get(call.name)
    if handler is None:
        return ToolResult(False, error="unknown_tool")
    if call.name not in allowed:
        return ToolResult(False, error="tool_not_allowed")
    if not isinstance(call.arguments, dict):
        return ToolResult(False, error="invalid_arguments")
    try:
        return handler(call.arguments, session, conn, profile, now or datetime.now(UTC))
    except _Invalid:
        return ToolResult(False, error="invalid_arguments")


def confirm_refund(token: object, session: Session, conn: sqlite3.Connection) -> ToolResult:
    """Aprueba un reembolso pendiente. Lo llama la UI (`POST /api/tools/confirm`), nunca el modelo.

    FIX-V4: el token es de un solo uso y solo sirve en la sesión del cliente que pidió el
    reembolso y es dueño del pedido.
    """
    if not isinstance(token, str) or not token:
        return ToolResult(False, error="invalid_token")
    row = conn.execute(
        """SELECT r.id, r.order_id, r.amount FROM refunds r JOIN orders o ON o.id = r.order_id
           WHERE r.token = ? AND r.status = 'pending_confirmation'
             AND r.requested_by = ? AND o.customer_id = ?""",
        (token, session.customer_id, session.customer_id),
    ).fetchone()
    if row is None:
        return ToolResult(False, error="invalid_token")
    with conn:
        cur = conn.execute(
            "UPDATE refunds SET status = 'approved', token = NULL WHERE id = ? AND status = 'pending_confirmation'",
            (row["id"],),
        )
    if cur.rowcount != 1:  # otro pedido lo confirmó en el medio
        return ToolResult(False, error="invalid_token")
    return ToolResult(True, {"refund_id": row["id"], "order_id": row["order_id"], "amount": row["amount"],
                             "status": "approved"})
