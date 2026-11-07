"""Dobles de prueba del modelo.

`ScriptedLLM` permite simular que el modelo "ya fue engañado": se le dicta qué responder
y se verifica qué hace el backend con eso. Así los controles de seguridad se prueban de
forma determinista, sin depender de un modelo real.
"""

from __future__ import annotations

import copy
import math
import re
import unicodedata

from app.llm import LLMReply, ToolCall


class ScriptedLLM:
    def __init__(self, embed=None):
        self._replies: list[LLMReply] = []
        self._error: Exception | None = None
        self.calls: list[dict] = []
        self._embed = embed or keyword_embed

    def script(self, replies: list[LLMReply]) -> "ScriptedLLM":
        self._replies = list(replies)
        self._error = None
        return self

    def fail_with(self, exc: Exception) -> "ScriptedLLM":
        self._error = exc
        return self

    def chat(self, messages: list[dict], tools: list[dict], seed: int) -> LLMReply:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools), "seed": seed})
        if self._error is not None:
            raise self._error
        if not self._replies:
            return text("(sin guion)")
        return self._replies.pop(0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)


def tool_call(name: str, **args) -> LLMReply:
    return LLMReply(content="", tool_calls=[ToolCall(name, args)])


def text(content: str) -> LLMReply:
    return LLMReply(content=content, tool_calls=[])


# Embedding falso y determinista: un eje por palabra clave. Dos textos quedan cerca si
# comparten palabras clave, que es lo que necesitan los tests de recuperación.
KEYWORDS = [
    "devolucion", "devoluciones", "reembolso", "envio", "envios", "pago", "pagos", "tarjeta",
    "garantia", "garantias", "producto", "pedido", "plazo", "dias", "resena", "opinion",
]


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def keyword_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        words = re.findall(r"\w+", _normalize(t))
        v = [float(words.count(k)) for k in KEYWORDS] + [0.01]  # sesgo: nunca vector nulo
        norm = math.sqrt(sum(x * x for x in v))
        out.append([x / norm for x in v])
    return out
