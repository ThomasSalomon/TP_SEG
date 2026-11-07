# Asistente LLM vulnerable — TPI Seguridad en el Desarrollo de Software

> ⚠️ **Esta aplicación es vulnerable a propósito.** Es un laboratorio académico (UTN, 4K2) para
> demostrar y medir vulnerabilidades de aplicaciones con LLM. No la expongas en una red: los
> puertos se publican solo en `127.0.0.1` y el modelo no tiene salida a Internet. La empresa,
> los clientes y los pedidos son ficticios.

Asistente de atención al cliente de una tienda ficticia (TiendaFicticia) con un LLM local
(Ollama), RAG (Chroma), base de pedidos (SQLite) y tres herramientas: consultar pedido,
emitir reembolso y enviar email simulado. Una sola base de código se comporta como versión
**vulnerable** o **segura** según la variable `SECURITY_PROFILE`.

- Propuesta: [`docs/Propuesta TPI Seguridad en asistentes con LLM.pdf`](docs/Propuesta%20TPI%20Seguridad%20en%20asistentes%20con%20LLM.pdf)
- Plan de implementación: [`docs/superpowers/plans/2026-11-04-asistente-llm-vulnerable.md`](docs/superpowers/plans/2026-11-04-asistente-llm-vulnerable.md)
- Avances: [`avances.md`](avances.md)

## Requisitos

- Docker Desktop (o Docker Engine con Compose v2).
- Unos 8 GB de RAM libres para un modelo de 7B en CPU (menos con `llama3.2:3b`).
- Para desarrollo sin Docker: Python 3.12 y [uv](https://docs.astral.sh/uv/) (`pip install uv`).

## Levantar el laboratorio con Docker

1. Descargar los modelos (única etapa con Internet, guarda los modelos en un volumen):

   ```bash
   docker compose --profile setup run --rm ollama-init
   ```

2. Levantar Ollama y las dos versiones:

   ```bash
   docker compose up -d --build
   ```

   - Versión vulnerable: <http://127.0.0.1:8001>
   - Versión segura: <http://127.0.0.1:8002>

3. Prueba de humo con el modelo real (desde la red interna):

   ```bash
   docker compose run --rm harness pytest -m llm tests/test_e2e_smoke.py -v
   ```

### Con GPU NVIDIA

Requiere NVIDIA Container Toolkit. Se suma el override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

### Variables

Se pueden cambiar con un archivo `.env` (ver [`.env.example`](.env.example)):

| Variable | Por defecto | Uso |
|---|---|---|
| `SECURITY_PROFILE` | (obligatoria) | `vulnerable`, `segura`, `solo_filtros`, `solo_v1` … `solo_v5`. Sin ella la app no arranca |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Servidor de Ollama |
| `LLM_MODEL` | `qwen2.5:7b` | Modelo de chat (provisorio hasta cerrar la tarea 2) |
| `EMBED_MODEL` | `nomic-embed-text` | Modelo de embeddings |
| `LLM_TEMPERATURE`, `LLM_BASE_SEED`, `LLM_NUM_PREDICT`, `LLM_NUM_CTX` | 0.7, 1000, 512, 4096 | Parámetros fijados y documentados en [`docs/decisiones/modelo.md`](docs/decisiones/modelo.md) |
| `DATA_DIR` | `/data` | Base SQLite y colección de Chroma del servicio |
| `OLLAMA_IMAGE` | `ollama/ollama:0.12.6` | Versión fija de Ollama |

## Desarrollo local sin Docker

```bash
python -m pip install uv
```

```bash
uv sync
```

```bash
uv run pytest
```

Para correr la app contra un Ollama instalado en la máquina (PowerShell):

```powershell
$env:SECURITY_PROFILE = "vulnerable"; $env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"; $env:DATA_DIR = "var/vulnerable"
uv run uvicorn --factory app.main:app_from_env --host 127.0.0.1 --port 8001
```

## Usuarios de demostración

Credenciales ficticias, solo para el laboratorio:

| Cliente | Contraseña | Pedidos |
|---|---|---|
| `alice` | `alice-demo` | 1001 (5 días, $100), 1002 (90 días, $80) |
| `bob` | `bob-demo` | 2001 (5 días, $150) |

## Tests

- `uv run pytest`: tests deterministas, con un modelo falso (`tests/fakes.py`). No necesitan Ollama.
- `pytest -m llm`: tests con el modelo real. Se ejecutan dentro del contenedor `harness`.

## Estructura

```text
app/          backend FastAPI, prompts, RAG, herramientas e interfaz (static/)
data/kb/      FAQ de la tienda que se cargan en el RAG
scripts/      model_spike.py (elección del modelo)
tests/        un archivo de tests por módulo
docs/         propuesta, plan, decisiones e informe
attacks/      batería de ataques y arnés (Fase B)
results/      resultados de las mediciones
```

Cada vulnerabilidad está marcada en el código con `# VULN-Vn` (o `// VULN-V5` en JS) y cada
corrección con `# FIX-Vn`.

| Vulnerabilidad | OWASP LLM 2026 | Dónde vive |
|---|---|---|
| V1 Inyección directa | LLM01 | `app/prompts.py` (reglas solo en el prompt), `app/tools.py` |
| V2 Inyección indirecta | LLM01 / LLM09 | `app/rag.py` (ingesta sin validar), `app/prompts.py` (contexto sin delimitar) |
| V3 Exposición del contexto oculto | LLM08 / LLM02 | `app/prompts.py` (código y regla interna en el system prompt) |
| V4 Agencia excesiva | LLM03 | `app/tools.py` (sin autorización por sesión ni confirmación) |
| V5 Salida sin codificar | LLM10 | `app/static/chat.js` (`innerHTML`), `app/main.py` |

## Limitaciones conocidas del entorno

- Las apps están en la red `front` para poder publicar sus puertos, así que conservan salida a la
  red. Ollama y el arnés están solo en la red interna `lab`.
- Los resultados de la medición son válidos solo para el modelo, la versión (digest) y el hardware
  usados. La medición final se hace en una sola máquina.
