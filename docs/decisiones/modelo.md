# Decisión: modelo de lenguaje y parámetros

> **Estado: PENDIENTE.** El script `scripts/model_spike.py` está listo, pero todavía no se ejecutó
> contra un Ollama real. Los valores de abajo son **provisorios** (son los que usa hoy
> `app/config.py` por defecto) y se reemplazan cuando se complete la tarea 2.

## Cómo completar esta decisión

1. Instalar Ollama (o usar el contenedor de Compose) y descargar los candidatos:

   ```bash
   ollama pull llama3.2:3b
   ```

   ```bash
   ollama pull qwen2.5:7b
   ```

   ```bash
   ollama pull nomic-embed-text
   ```

2. Ejecutar el script en la **máquina más débil del grupo** y en la **elegida para medir**, una vez por modelo:

   ```bash
   uv run python scripts/model_spike.py --model llama3.2:3b --reps 10 --out docs/decisiones/spike-resultados.md
   ```

   ```bash
   uv run python scripts/model_spike.py --model qwen2.5:7b --reps 10 --out docs/decisiones/spike-resultados.md
   ```

3. Aplicar los criterios de aceptación y completar las tablas de abajo.

## Criterios de aceptación (definidos antes de mirar los resultados)

El modelo se elige **sin mirar qué tan fácil es de atacar**. Solo cuentan estos criterios:

| Criterio | Umbral |
|---|---|
| Tool calls correctas en consultas benignas | ≥ 90% |
| Misma respuesta con misma semilla y misma máquina | 100% de las consultas |
| Respuestas variadas con semillas distintas | Al menos algunas consultas con más de una salida distinta |
| Contexto no truncado | `prompt_eval_count` coherente con los tokens enviados y menor que `num_ctx` |
| Costo de la medición obligatoria | Viable antes del 16 de noviembre (si no, se recortan perfiles adicionales, **nunca** las 50 repeticiones) |

## Candidatos

| Modelo | Digest | Tool calls OK | Reproducible | Varía entre semillas | Latencia media | Costo estimado | ¿Cumple? |
|---|---|---|---|---|---|---|---|
| `llama3.2:3b` | _pendiente_ | | | | | | |
| `qwen2.5:7b` | _pendiente_ | | | | | | |

## Valores elegidos

| Parámetro | Valor | Estado |
|---|---|---|
| Modelo de chat | `qwen2.5:7b` | provisorio |
| Digest | _pendiente_ | |
| Modelo de embeddings | `nomic-embed-text` | provisorio |
| Temperatura | 0,7 | provisorio |
| `base_seed` | 1000 | provisorio |
| `num_predict` | 512 | provisorio |
| `num_ctx` | 4096 | provisorio |
| Máquina de medición (CPU, RAM, GPU) | _pendiente_ | |

## Costo de medir

Medición obligatoria: 28 casos (15 ataques `dev`, 5 `heldout`, 8 de utilidad) × 50 repeticiones ×
2 perfiles = **2800 ejecuciones**. El script estima las horas con 1,5 llamadas al modelo por caso,
para cubrir ataques de varios turnos y rondas de herramientas.

| Máquina | Latencia media | Horas estimadas |
|---|---|---|
| _pendiente_ | | |
