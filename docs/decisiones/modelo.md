# Decisión: modelo de lenguaje y parámetros

> **Estado: decidido en la máquina de desarrollo (8 de noviembre de 2026).** Modelo elegido:
> **`qwen2.5:3b`**. Falta repetir `scripts/model_spike.py` en la **máquina que se use para la medición
> final** y confirmar ahí el costo; si es otra máquina, sus valores reemplazan a los de esta tabla.

Resultados crudos: [`spike-resultados.md`](spike-resultados.md).

## Criterios de aceptación (definidos antes de mirar los resultados)

El modelo se elige **sin mirar qué tan fácil es de atacar**. Solo cuentan estos criterios:

| Criterio | Umbral |
|---|---|
| Tool calls correctas en consultas benignas | ≥ 90% |
| Misma respuesta con misma semilla y misma máquina | 100% de las consultas (ver la revisión de este criterio más abajo) |
| Respuestas variadas con semillas distintas | Al menos algunas consultas con más de una salida distinta |
| Contexto no truncado | `prompt_eval_count` coherente con los tokens enviados y menor que `num_ctx` |
| Costo de la medición obligatoria | Viable antes del 16 de noviembre (si no, se recortan perfiles adicionales, **nunca** las 50 repeticiones) |

## Candidatos evaluados

Máquina: notebook con Intel Core i5-1235U, 7,7 GB de RAM, gráficos integrados (sin GPU dedicada),
Windows 11, Ollama 0.40.15 nativo.

| Modelo | Tool calls OK | Reproducible | Varía entre semillas | Latencia media | Costo estimado | ¿Cumple? |
|---|---|---|---|---|---|---|
| `llama3.2:3b` | **60%** | 60%¹ | 80% | ~3,9 s² | 8,2 h | **No**: usa herramientas en consultas generales. Desinstalado |
| `qwen2.5:7b` | sin medir | sin medir | sin medir | **~205 s** | **~240 h** | **No**: inviable en esta máquina (no entra cómodo en 7,7 GB). Desinstalado |
| `qwen2.5:3b` | **100%** | 80% | 70% | 5,8 s | **6,8 h** | **Sí**, con el criterio de reproducibilidad revisado |

¹ Medido con la primera versión del script, que comparaba caché fría contra caché caliente.
² Sin contar la primera consulta, que incluía la carga del modelo.

## Revisión del criterio de reproducibilidad

El plan (sección 2, ajuste 1) supone que, con el mismo modelo, prompt, opciones, semilla y hardware, Ollama
repite la misma salida. **En esta máquina no se cumple de forma exacta**, y no depende del modelo:

1. La salida cambia según el estado de la **caché de prompts** de Ollama: repetir la misma consulta
   inmediatamente da otra salida que después de una consulta distinta.
2. Aun forzando el mismo estado de caché antes de cada llamada, la misma consulta con la misma semilla
   dio 2 salidas distintas en 3 intentos (prueba hecha con `qwen2.5:3b`). Es no determinismo numérico del
   cálculo en CPU, propio de Ollama.
3. Las diferencias aparecen en respuestas de texto largo. Las tool calls de las consultas probadas fueron
   estables.

**Decisión:** la reproducibilidad exacta deja de ser un criterio para elegir el modelo, porque ningún
modelo la cumple en este entorno. Se reemplaza por reproducibilidad **estadística**: lo que se reporta y
se compara son tasas sobre 50 repeticiones con intervalo de confianza, y eso sigue siendo válido. La semilla
fija (`base_seed + rep`, igual en todos los perfiles) se mantiene, porque reduce la variación y deja la
comparación pareada.

**Consecuencias para el resto del plan:**

- **Informe (tarea 16):** declararlo como limitación. Las tasas se reproducen dentro de su intervalo de
  confianza, no salida por salida.
- **Demo en vivo (tarea 17):** `find_demo_seed` supone que una semilla con éxito vuelve a dar éxito. No está
  garantizado. Conviene demostrar ataques con tasa alta, ensayar la semilla elegida varias veces en la
  máquina de la presentación y tener el video de respaldo.

## Valores elegidos

| Parámetro | Valor | Estado |
|---|---|---|
| Modelo de chat | `qwen2.5:3b` | elegido |
| Digest | `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b` | registrado |
| Modelo de embeddings | `nomic-embed-text` | elegido |
| Temperatura | 0,7 | elegido |
| `base_seed` | 1000 | elegido |
| `num_predict` | 512 | elegido |
| `num_ctx` | 4096 | elegido (los prompts del script usan unos 400 tokens) |
| Máquina de medición (CPU, RAM, GPU) | _a definir_ | pendiente |

## Costo de medir

Medición obligatoria: 28 casos (15 ataques `dev`, 5 `heldout`, 8 de utilidad) × 50 repeticiones ×
2 perfiles = **2800 ejecuciones**. El script estima las horas con 1,5 llamadas al modelo por caso.

| Máquina | Modelo | Latencia media | Horas estimadas |
|---|---|---|---|
| i5-1235U, 7,7 GB, sin GPU | `qwen2.5:3b` | 5,8 s | 6,8 h |

**Confirmación con el runner real** (8 de noviembre, batería de humo, 2 perfiles × 3 repeticiones, con el
prompt real del asistente y el RAG): 12 de 12 ejecuciones exitosas y sin errores. Con el modelo cargado,
una consulta de FAQ tarda unos 3,3 s y una consulta de pedido (dos llamadas al modelo y una herramienta)
unos 12 s. Con un promedio de 7,5 s por caso, la medición obligatoria lleva **unas 6 h**. Los ataques de
varios turnos van a subir ese número, así que conviene presupuestar **8 a 10 h** y correrla de noche.

## Alternativas si `qwen2.5:3b` deja de servir

En orden de preferencia, todas locales y con soporte de herramientas en Ollama. Cada una debe pasar por
`scripts/model_spike.py` antes de adoptarse:

1. **Correr `qwen2.5:7b` en otra máquina del grupo** con GPU o 16 GB de RAM o más. Es la opción que más
   mejora la calidad sin salir del diseño aprobado.
2. **`qwen3:4b`** o **`phi4-mini`** (3,8B): modelos chicos más recientes con soporte de herramientas. En
   `qwen3` hay que desactivar el modo de razonamiento, que agrega tokens y latencia.
3. **`qwen2.5:1.5b`**: más rápido, pero es probable que baje la tasa de tool calls correctas.

Una API externa (por ejemplo, Groq) o exponer Ollama con un túnel (ngrok) **contradice la propuesta
aprobada**, que establece ejecución local, sin APIs externas y sin pruebas sobre servicios de terceros.
Solo se debería considerar con el acuerdo del profesor.
