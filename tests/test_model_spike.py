from app.config import DEFAULT_MODEL_PARAMS
from scripts.model_spike import QUERIES, estimate_hours, render, run_spike
from tests.fakes import ScriptedLLM, text, tool_call


def _respuestas_correctas(reps, calentamiento=False):
    replies = [text("calentamiento")] if calentamiento else []
    for _, expected in QUERIES:
        reply = tool_call(expected, order_id=1001) if expected else text("Hola")
        # primera, consulta neutra (iguala la caché de prompts), repetición con la misma
        # semilla y reps-1 semillas distintas
        replies += [reply, text("neutra"), reply] + [text(f"variante {i}") for i in range(reps - 1)]
    return replies


def test_spike_mide_tool_calls_y_reproducibilidad():
    llm = ScriptedLLM().script(_respuestas_correctas(3, calentamiento=True))
    results = run_spike(llm, base_seed=1000, reps=3)
    assert len(results) == len(QUERIES) == 10
    assert all(r.tool_ok and r.reproducible for r in results)
    assert all(r.distinct_outputs == 3 for r in results)
    assert [c["seed"] for c in llm.calls[1:6]] == [1000, 1000, 1000, 1001, 1002]
    # la repetición se compara en igualdad de condiciones: la precede otra consulta
    assert llm.calls[2]["messages"][-1]["content"] != llm.calls[1]["messages"][-1]["content"]
    assert llm.calls[3]["messages"] == llm.calls[1]["messages"]


def test_spike_detecta_herramienta_equivocada():
    llm = ScriptedLLM().script([text("no uso herramientas")] * 100)
    results = run_spike(llm, base_seed=1, reps=2)
    assert not results[0].tool_ok  # esperaba get_order
    assert results[-1].tool_ok      # saludo: no debe usar herramientas


def test_p95_por_rango_mas_cercano():
    from scripts.model_spike import p95

    assert p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 100]) == 100
    assert p95([5]) == 5


def test_calienta_el_modelo_antes_de_medir():
    llm = ScriptedLLM().script(_respuestas_correctas(2, calentamiento=True))
    results = run_spike(llm, base_seed=1000, reps=2)
    assert len(llm.calls) == 1 + 10 * 4
    assert all(r.tool_ok for r in results)


def test_estimacion_de_costo():
    # 2800 ejecuciones × 1,5 llamadas × 2 s = 2,33 h
    assert round(estimate_hours(2000), 2) == 2.33


def test_render_incluye_criterios():
    llm = ScriptedLLM().script(_respuestas_correctas(2, calentamiento=True))
    md = render(run_spike(llm, 1000, 2), "modelo:x", "sha", DEFAULT_MODEL_PARAMS)
    assert "Tool calls correctas: **100%**" in md and "sha" in md
