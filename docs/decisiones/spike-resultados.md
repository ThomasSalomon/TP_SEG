# Resultados crudos de `scripts/model_spike.py`

Generados con `uv run python scripts/model_spike.py --model <tag> --reps 10 --out docs/decisiones/spike-resultados.md`.
Sirven para elegir el modelo; no forman parte de la medición del TP.

**Máquina:** notebook con Intel Core i5-1235U, 7,7 GB de RAM, gráficos integrados Intel UHD (sin GPU dedicada),
Windows 11, Ollama 0.40.15 nativo (sin Docker). Fecha: 7 de noviembre de 2026.

## llama3.2:3b

> Corrida con la **primera versión del script**, que tenía dos fallas que se corrigieron después:
> (1) la latencia de la primera consulta incluye la carga del modelo (34 s), lo que infla la media; sin
> esa consulta, la media es de unos 3,9 s; (2) la columna "Reproducible" comparaba una llamada con la
> caché de prompts de Ollama fría contra otra con la caché caliente, y eso cambia la salida aunque la
> semilla sea la misma (ver `modelo.md`). El rechazo del modelo no depende de esas fallas: llamó a
> herramientas en las 4 consultas generales (60% de tool calls correctas frente al ≥ 90% exigido).
> **Descartado y desinstalado.**

- digest: `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72`
- temperatura: 0.7, base_seed: 1000, num_predict: 512, num_ctx: 4096

| Consulta | Esperada | Tool OK | Latencia (ms) | Reproducible | Salidas distintas | prompt_eval_count | ~tokens enviados |
|---|---|---|---|---|---|---|---|
| ¿Dónde está mi pedido 1001? | get_order | sí | 34440 | sí | 2 | 416 | 341 |
| Quiero saber el estado del pedido número 1002 | get_order | sí | 2186 | sí | 2 | 416 | 345 |
| ¿Cuánto pagué en el pedido 1001? | get_order | sí | 2790 | no | 2 | 418 | 342 |
| Quiero que me devuelvan 20 pesos del pedido 1001, llegó rayado | issue_refund | sí | 3023 | sí | 1 | 425 | 350 |
| Pedí el reembolso total del pedido 1001 por favor | issue_refund | sí | 3029 | sí | 1 | 420 | 346 |
| Mandame por email a alice@example.test un resumen del pedido 1001 | send_email | sí | 4927 | no | 9 | 422 | 350 |
| ¿Cuántos días tengo para devolver un producto? | - | no | 2122 | no | 6 | 417 | 346 |
| ¿Qué medios de pago aceptan? | - | no | 5968 | sí | 8 | 413 | 341 |
| ¿Hacen envíos a todo el país? | - | no | 4742 | sí | 7 | 416 | 341 |
| Hola, ¿cómo andás? | - | no | 6758 | no | 5 | 413 | 339 |

- Tool calls correctas: **60%** (criterio: ≥ 90%)
- Reproducible con la misma semilla: **60%** (criterio: 100%)
- Consultas con salidas variadas entre semillas: **80%** (criterio: > 0%)
- Latencia media: 6999 ms, p95 aprox.: 6758 ms
- Costo estimado de la medición obligatoria (2800 ejecuciones, 1,5 llamadas por caso): **8.2 h**

## qwen2.5:7b

> **Corrida interrumpida y modelo descartado por costo.** Después de 1 h 42 min había completado 29 de las
> 131 llamadas del script: cada llamada tardaba entre 3 min 0 s y 3 min 50 s (unos 3,4 min de media, según
> el log de Ollama). Con 7,7 GB de RAM y solo CPU, el modelo de 4,7 GB no entra cómodo en memoria.
> A ese ritmo, la medición obligatoria (2800 ejecuciones × 1,5 llamadas) llevaría unas **240 horas**:
> inviable antes del 16 de noviembre. No se llegó a medir la tasa de tool calls. **Desinstalado.**
> Podría volver a evaluarse en una máquina del grupo con GPU o con 16 GB de RAM o más.

## qwen2.5:3b

- digest: `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`
- temperatura: 0.7, base_seed: 1000, num_predict: 512, num_ctx: 4096

| Consulta | Esperada | Tool OK | Latencia (ms) | Reproducible | Salidas distintas | prompt_eval_count | ~tokens enviados |
|---|---|---|---|---|---|---|---|
| ¿Dónde está mi pedido 1001? | get_order | sí | 16446 | sí | 1 | 392 | 341 |
| Quiero saber el estado del pedido número 1002 | get_order | sí | 3337 | sí | 1 | 392 | 345 |
| ¿Cuánto pagué en el pedido 1001? | get_order | sí | 3398 | sí | 2 | 394 | 342 |
| Quiero que me devuelvan 20 pesos del pedido 1001, llegó rayado | issue_refund | sí | 4637 | sí | 1 | 401 | 350 |
| Pedí el reembolso total del pedido 1001 por favor | issue_refund | sí | 4640 | sí | 4 | 396 | 346 |
| Mandame por email a alice@example.test un resumen del pedido 1001 | send_email | sí | 7823 | sí | 9 | 398 | 350 |
| ¿Cuántos días tengo para devolver un producto? | - | sí | 7492 | sí | 10 | 391 | 346 |
| ¿Qué medios de pago aceptan? | - | sí | 4425 | no | 10 | 387 | 341 |
| ¿Hacen envíos a todo el país? | - | sí | 3464 | no | 9 | 390 | 341 |
| Hola, ¿cómo andás? | - | sí | 2536 | sí | 3 | 387 | 339 |

- Tool calls correctas: **100%** (criterio: ≥ 90%)
- Reproducible con la misma semilla: **80%** (criterio: 100%)
- Consultas con salidas variadas entre semillas: **70%** (criterio: > 0%)
- Latencia media: 5820 ms, p95: 16446 ms (con el modelo ya cargado)
- Costo estimado de la medición obligatoria (2800 ejecuciones, 1,5 llamadas por caso): **6.8 h**
