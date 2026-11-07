"""Cliente del modelo de lenguaje.

Se habla con Ollama por HTTP con `httpx`, sin su SDK, para controlar exactamente qué
opciones se envían (semilla, temperatura, tope de tokens y contexto). Todo fallo de
red, timeout, 5xx o respuesta malformada se traduce a `LLMUnavailable`: el arnés lo
cuenta como error y no como ataque bloqueado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import ModelParams


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Métricas que informa Ollama; las usa el script de elección del modelo.
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class LLMUnavailable(Exception):
    """El modelo no respondió o respondió algo inutilizable."""


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict], seed: int) -> LLMReply: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_tool_calls(raw: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in raw or []:
        fn = item.get("function", {}) if isinstance(item, dict) else {}
        name = fn.get("name")
        if isinstance(name, str) and name:
            calls.append(ToolCall(name, _parse_arguments(fn.get("arguments"))))
    return calls


class OllamaClient:
    def __init__(self, base_url: str, params: ModelParams, embed_model: str, timeout_s: float):
        self.base_url = base_url.rstrip("/")
        self.params = params
        self.embed_model = embed_model
        self.timeout_s = timeout_s

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            with httpx.Client(timeout=self.timeout_s) as http:
                resp = http.request(method, f"{self.base_url}{path}", json=payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMUnavailable(f"Ollama respondió {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMUnavailable("Ollama devolvió una respuesta que no es JSON") from exc
        if not isinstance(data, dict):
            raise LLMUnavailable("Ollama devolvió una respuesta inesperada")
        return data

    def chat(self, messages: list[dict], tools: list[dict], seed: int) -> LLMReply:
        payload: dict[str, Any] = {
            "model": self.params.model,
            "messages": messages,
            "stream": False,
            "options": {
                "seed": seed,
                "temperature": self.params.temperature,
                "num_predict": self.params.num_predict,
                "num_ctx": self.params.num_ctx,
            },
        }
        if tools:
            payload["tools"] = tools
        data = self._request("POST", "/api/chat", payload)
        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMUnavailable("La respuesta de Ollama no trae 'message'")
        return LLMReply(
            content=message.get("content") or "",
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            prompt_eval_count=data.get("prompt_eval_count"),
            eval_count=data.get("eval_count"),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        data = self._request("POST", "/api/embed", {"model": self.embed_model, "input": texts})
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise LLMUnavailable("La respuesta de embeddings de Ollama no coincide con lo pedido")
        return embeddings

    def model_digest(self) -> str:
        """Digest del modelo de chat instalado, para registrar exactamente qué versión se midió."""
        data = self._request("GET", "/api/tags")
        wanted = {self.params.model}
        if ":" not in self.params.model:
            wanted.add(f"{self.params.model}:latest")
        for m in data.get("models", []):
            if m.get("name") in wanted or m.get("model") in wanted:
                return m["digest"]
        raise LookupError(f"El modelo {self.params.model!r} no está instalado en Ollama")
