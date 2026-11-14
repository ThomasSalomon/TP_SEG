"""Limpieza y filtro de reseñas de clientes (tarea 11, FIX-V2).

Es una capa **adicional**: el control principal de V2 es `allowed_tools`, en el
orquestador, que no depende de adivinar si un texto trae instrucciones. Este filtro es
heurístico y se puede evadir; sirve para sacar lo obvio y, sobre todo, para que el
contenido oculto (comentarios HTML, caracteres invisibles) no llegue nunca al modelo.
"""

from __future__ import annotations

import re
import unicodedata

MAX_REVIEW_CHARS = 2000

# Caracteres de ancho cero, marcas de dirección y guion suave: invisibles para quien lee la
# reseña en pantalla, pero el modelo los recibe.
_INVISIBLE = re.compile("[­᠎​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|$)", re.DOTALL)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^<>]{0,500}>")
_SPACES = re.compile(r"[ \t]+")

_LINK = re.compile(r"\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:test|com|net|org|ar|io|xyz|ly)/\S*", re.IGNORECASE)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# Se buscan sobre el texto en minúsculas y sin tildes. Apuntan a texto dirigido al asistente,
# no a palabras sueltas: "ignoraron mi reclamo" o "el asistente del local" son reseñas normales.
_INSTRUCTIONS = [re.compile(p) for p in (
    r"\bignor\w*\b.{0,40}\b(instruc\w*|regla\w*|indicacion\w*|anterior\w*|previ\w*|prompt)",
    r"\bignore\b.{0,30}\b(all|previous|prior|above|instructions?)\b",
    r"\b(olvida\w*|forget|disregard)\b.{0,40}\b(instruc\w*|regla\w*|anterior\w*|previous|rules?)",
    r"\b(nuevas?|new)\s+(instruc\w*|reglas?|rules?)\b",
    r"\b(system\s*prompt|prompt\s+del\s+sistema|instrucciones\s+del\s+sistema)\b",
    r"\ba\s+partir\s+de\s+ahora\b",
    r"\b(nota|mensaje|aviso|importante|instruc\w*)\b.{0,20}\b(para|to)\s+(el|la|the)?\s*"
    r"(asistente|ia|ai|modelo|bot|chatbot|lumi|assistant)\b",
    r"\b(asistente|ia|ai|modelo|bot|chatbot|lumi|assistant)\s*[:,]",
    r"\bsi\s+(sos|eres)\s+(un|una|el|la)\s+(asistente|ia|modelo|bot|chatbot)",
    r"\b(get_order|issue_refund|send_email)\b",
    r"\b(envia|enviale|enviar|manda|mandale|mandar|send)\s+(un|el|a|an)?\s*(e-?mail|correo|mail)\b",
    r"\b(decile|deciles|deci\s+al?|respondele|respondeles|contestale|contestales)\b",
    r"\b(responde|contesta)\s+(solo|unicamente|unicamente\s+con|con\s+(el|este)\s+(enlace|link|codigo))\b",
    r"\byou\s+are\s+(now|a|an|the)\b",
)]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def clean_review(text: str) -> str:
    """Quita lo que no se ve en pantalla: comentarios y etiquetas HTML y caracteres invisibles."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = _HTML_COMMENT.sub("", text)
    text = _HTML_TAG.sub("", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def sanitize_review(text: str) -> tuple[str, str | None]:
    """Devuelve (texto limpio, motivo de rechazo). Si el motivo es None, la reseña se acepta."""
    clean = clean_review(text)
    if not clean:
        return clean, "empty"
    if len(clean) > MAX_REVIEW_CHARS:
        return clean, "too_long"
    if _LINK.search(clean):
        return clean, "link"
    if _EMAIL.search(clean):
        return clean, "email"
    folded = _fold(clean)
    if any(p.search(folded) for p in _INSTRUCTIONS):
        return clean, "instructions"
    return clean, None
