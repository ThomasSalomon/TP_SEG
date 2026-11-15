"""Reglas de negocio en el backend y filtros de entrada y salida (tarea 10).

- `check_refund_policy` es el control de diseño de V1 (`fix_v1`): las reglas de reembolso
  se cumplen aunque el modelo sea convencido de ignorarlas.
- `input_flagged` y `output_flagged` son una capa adicional (`filters`): heurísticas que
  sacan lo obvio y se pueden evadir. La promesa de un descuento solo existe como texto, así
  que contra ella no hay control de diseño: solo el filtro de salida.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

REFUND_WINDOW_DAYS = 30

INPUT_BLOCKED_REPLY = (
    "Perdón, no puedo procesar ese mensaje. Si necesitás ayuda con un pedido, un envío o una "
    "devolución, contame qué pasó."
)
OUTPUT_BLOCKED_REPLY = (
    "Perdón, no puedo ofrecer descuentos ni promociones que no estén publicados en la tienda. "
    "¿Te ayudo con otra cosa?"
)


def check_refund_policy(order: dict, amount: float, already_refunded: bool, now: datetime) -> str | None:
    """Devuelve el motivo de rechazo (`policy_*`) o None si el reembolso cumple las reglas.

    FIX-V1: son las mismas reglas que el prompt describe, pero aplicadas en el backend.
    """
    if already_refunded:
        return "policy_duplicate"
    created = datetime.fromisoformat(order["created_at"])
    if now - created > timedelta(days=REFUND_WINDOW_DAYS):
        return "policy_window"
    if amount > float(order["total"]) + 1e-9:
        return "policy_amount"
    return None


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


# Sobre el texto en minúsculas y sin tildes. Apuntan a pedidos de saltear las reglas, no a
# palabras sueltas: "ignorar el pedido anterior" es una consulta normal.
_INPUT_PATTERNS = [re.compile(p) for p in (
    r"\b(ignor|olvid|omit|saltea|descart)\w*\b.{0,40}\b(instruc\w*|regla\w*|indicacion\w*|prompt|restriccion\w*|politica\w*)",
    r"\b(ignore|forget|disregard)\b.{0,30}\b(all|previous|prior|above|instructions?|rules?)\b",
    r"\bsin\s+(restricciones|reglas|limites|filtros)\b",
    r"\b(modo|mode)\s+(desarrollador|developer|dios|god|dan|admin\w*)\b",
    r"\bjailbreak\b",
    r"\b(system\s*prompt|prompt\s+del\s+sistema|instrucciones\s+del\s+sistema|tus\s+instrucciones)\b",
    r"\ba\s+partir\s+de\s+ahora\s+(sos|eres|actua\w*|vas\s+a|respond\w*|ignor\w*)",
    r"\byou\s+are\s+now\b",
)]

# Promesa de descuento en la respuesta del modelo. Ante la duda marca: reemplazar una
# respuesta inocente cuesta poco; dejar pasar una promesa puede costar plata.
_OUTPUT_PATTERNS = [re.compile(p) for p in (
    r"\d{1,3}\s*(%|por\s*ciento)\s*(de\s+)?(descuento|off|rebaja|bonificacion)",
    r"(descuento|rebaja|bonificacion)\w*\s+(del?|de\s+un)\s+\d{1,3}\s*(%|por\s*ciento)",
    r"\b(te|le|les)\s+(doy|damos|ofrezco|ofrecemos|aplico|aplicamos|hago|hacemos|dejo|regalo)\b.{0,30}"
    r"\b(descuento|rebaja|bonificacion|promo\w*|cupon)",
)]


def input_flagged(text: str) -> bool:
    folded = _fold(text)
    return any(p.search(folded) for p in _INPUT_PATTERNS)


def output_flagged(text: str) -> bool:
    folded = _fold(text)
    return any(p.search(folded) for p in _OUTPUT_PATTERNS)
