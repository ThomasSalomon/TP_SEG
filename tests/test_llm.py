import json

import httpx
import pytest

from app.config import ModelParams
from app.llm import LLMReply, LLMUnavailable, OllamaClient, ToolCall

BASE = "http://ollama.test:11434"
PARAMS = ModelParams(model="qwen2.5:7b", temperature=0.7, base_seed=1000, num_predict=256, num_ctx=4096)


@pytest.fixture
def client():
    return OllamaClient(BASE, PARAMS, embed_model="nomic-embed-text", timeout_s=5)


def _chat_response(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"model": PARAMS.model, "message": msg, "done": True, "prompt_eval_count": 42, "eval_count": 7}


def test_ollama_envia_opciones(httpx_mock, client):
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/chat", json=_chat_response("hola"))
    tools = [{"type": "function", "function": {"name": "get_order", "parameters": {}}}]
    reply = client.chat([{"role": "user", "content": "hola"}], tools, seed=1007)

    body = json.loads(httpx_mock.get_request().content)
    assert body["model"] == "qwen2.5:7b"
    assert body["stream"] is False
    assert body["tools"] == tools
    assert body["options"] == {"seed": 1007, "temperature": 0.7, "num_predict": 256, "num_ctx": 4096}
    assert reply == LLMReply(content="hola", tool_calls=[], prompt_eval_count=42, eval_count=7)


def test_ollama_no_envia_tools_vacias(httpx_mock, client):
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/chat", json=_chat_response("ok"))
    client.chat([{"role": "user", "content": "x"}], [], seed=1)
    assert "tools" not in json.loads(httpx_mock.get_request().content)


def test_ollama_parsea_tool_calls(httpx_mock, client):
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/chat", json=_chat_response("", [
        {"function": {"name": "get_order", "arguments": {"order_id": 1001}}},
        {"function": {"name": "send_email", "arguments": json.dumps({"to": "a@b.test"})}},
    ]))
    reply = client.chat([{"role": "user", "content": "x"}], [], seed=1)
    assert reply.tool_calls == [
        ToolCall("get_order", {"order_id": 1001}),
        ToolCall("send_email", {"to": "a@b.test"}),
    ]


def test_tool_call_con_argumentos_invalidos_no_rompe(httpx_mock, client):
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/chat", json=_chat_response("", [
        {"function": {"name": "get_order", "arguments": "{no es json"}},
    ]))
    reply = client.chat([{"role": "user", "content": "x"}], [], seed=1)
    assert reply.tool_calls == [ToolCall("get_order", {})]


def test_timeout_lanza_llm_unavailable(httpx_mock, client):
    httpx_mock.add_exception(httpx.ReadTimeout("lento"))
    with pytest.raises(LLMUnavailable):
        client.chat([{"role": "user", "content": "x"}], [], seed=1)


def test_error_de_conexion_lanza_llm_unavailable(httpx_mock, client):
    httpx_mock.add_exception(httpx.ConnectError("caído"))
    with pytest.raises(LLMUnavailable):
        client.chat([{"role": "user", "content": "x"}], [], seed=1)


def test_respuesta_5xx_lanza_llm_unavailable(httpx_mock, client):
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/chat", status_code=500, text="boom")
    with pytest.raises(LLMUnavailable):
        client.chat([{"role": "user", "content": "x"}], [], seed=1)


def test_respuesta_malformada_lanza_llm_unavailable(httpx_mock, client):
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/chat", json={"inesperado": True})
    with pytest.raises(LLMUnavailable):
        client.chat([{"role": "user", "content": "x"}], [], seed=1)


def test_embed_usa_el_modelo_de_embeddings(httpx_mock, client):
    httpx_mock.add_response(method="POST", url=f"{BASE}/api/embed", json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
    assert client.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    body = json.loads(httpx_mock.get_request().content)
    assert body == {"model": "nomic-embed-text", "input": ["a", "b"]}


def test_model_digest_lee_api_tags(httpx_mock, client):
    httpx_mock.add_response(method="GET", url=f"{BASE}/api/tags", json={"models": [
        {"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest", "digest": "e1"},
        {"name": "qwen2.5:7b", "model": "qwen2.5:7b", "digest": "abc123"},
    ]})
    assert client.model_digest() == "abc123"


def test_model_digest_falla_si_el_modelo_no_esta(httpx_mock, client):
    httpx_mock.add_response(method="GET", url=f"{BASE}/api/tags", json={"models": []})
    with pytest.raises(LookupError):
        client.model_digest()


def test_scripted_llm_cumple_el_protocolo():
    from tests.fakes import ScriptedLLM, text, tool_call

    llm = ScriptedLLM()
    llm.script([tool_call("get_order", order_id=1), text("listo")])
    assert llm.chat([{"role": "user", "content": "a"}], [], seed=3).tool_calls == [ToolCall("get_order", {"order_id": 1})]
    assert llm.chat([], [], seed=4).content == "listo"
    assert [c["seed"] for c in llm.calls] == [3, 4]
    llm.fail_with(LLMUnavailable("x"))
    with pytest.raises(LLMUnavailable):
        llm.chat([], [], seed=5)
