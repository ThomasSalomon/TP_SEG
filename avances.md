# Avances de implementación

**Fecha:** 7 de noviembre de 2026
**Fase trabajada:** Fase A, sistema base (tareas 1 a 7 del [plan](docs/superpowers/plans/2026-11-04-asistente-llm-vulnerable.md))
**Estado general:** el código de la Fase A está completo y probado con un modelo falso. Faltan los
pasos que necesitan el modelo real (Ollama) o Docker en ejecución, y todavía no se hizo ningún commit.

## Resumen

| Tarea | Estado | Tests |
|---|---|---|
| 1. Proyecto, perfiles y cliente LLM | ✅ Completa | 23 |
| 2. Elección del modelo | 🟡 Script listo; falta ejecutarlo con Ollama | 4 |
| 3. Base de pedidos y herramientas vulnerables | ✅ Completa | 39 |
| 4. Base de conocimiento vulnerable (RAG) | ✅ Completa | 12 |
| 5. Prompts y orquestador | ✅ Completa | 19 |
| 6. API e interfaz web | ✅ Completa | 29 |
| 7. Docker Compose de punta a punta | 🟡 Configuración y tests listos; falta probar con Docker y el modelo | 11 (+2 con modelo real) |

**Suite completa:** `uv run pytest` → **137 passed** en unos 20 s, sin Ollama ni Internet.
Los 2 tests marcados `llm` (`tests/test_e2e_smoke.py`) fallan con `LLMUnavailable` porque en esta máquina
no hay Ollama corriendo, que es lo esperado.

Cada tarea se hizo con TDD: primero se escribieron los tests, se verificó que fallaran y después se
implementó hasta que pasaran.

## Qué se implementó

### Tarea 1: proyecto, perfiles y cliente LLM

- `pyproject.toml` (Python 3.12, FastAPI, httpx, Chroma, PyYAML; pytest y pytest-httpx en dev), `uv.lock`,
  `.gitignore`, `.env.example`.
- [`app/config.py`](app/config.py): `SecurityProfile` con un flag por corrección (`fix_v1` … `fix_v5`, `filters`).
  `PROFILES` tiene `vulnerable`, `segura`, `solo_filtros` y `solo_v1` … `solo_v5`. `load_profile` falla si
  el perfil falta o no existe, así la app no arranca sin `SECURITY_PROFILE`. `ModelParams` y
  `model_params_from_env`.
- [`app/llm.py`](app/llm.py): `ToolCall`, `LLMReply`, `LLMUnavailable`, el protocolo `LLMClient` y
  `OllamaClient`, que usa `httpx` sin el SDK de Ollama. Envía `seed`, `temperature`, `num_predict` y `num_ctx`
  con `stream=false`; parsea tool calls (argumentos como objeto o como texto JSON); traduce timeouts, errores
  de red, respuestas 5xx y respuestas malformadas a `LLMUnavailable`; `model_digest()` lee `/api/tags`.
- [`tests/fakes.py`](tests/fakes.py): `ScriptedLLM` (`.script`, `.fail_with`, `.calls`), los helpers
  `tool_call` y `text`, y `keyword_embed`, un embedding falso y determinista por palabras clave.

### Tarea 2: elección del modelo (parcial)

- [`scripts/model_spike.py`](scripts/model_spike.py): con 10 consultas benignas en español (6 con herramienta
  esperada y 4 sin herramienta) mide tool calls correctas, latencia, reproducibilidad con la misma semilla,
  variación con semillas distintas y `prompt_eval_count` frente a los tokens enviados. Además estima las horas
  de la medición obligatoria (2800 ejecuciones). Si Ollama no responde, termina con código 1 y un mensaje claro.
- [`docs/decisiones/modelo.md`](docs/decisiones/modelo.md): plantilla con los criterios de aceptación
  definidos **antes** de ver resultados, las tablas a completar y los comandos para ejecutar el script.
  Los valores actuales están marcados como **provisorios**: no se inventó ninguna medición.

### Tarea 3: base de pedidos y herramientas vulnerables

- [`app/db.py`](app/db.py): tablas `customers`, `orders`, `refunds` (con `status` y `token` para la
  confirmación de la tarea 13) y `emails`. Datos ficticios con fechas relativas a `now`: 1001 (alice, 5 días,
  $100), 1002 (alice, 90 días, $80) y 2001 (bob, 5 días, $150). Las contraseñas de demo se guardan con
  PBKDF2-SHA256. Todas las consultas son parametrizadas.
- [`app/tools.py`](app/tools.py): `Session`, `ToolResult`, `TOOL_SCHEMAS` (`get_order`, `issue_refund` y
  `send_email`), `ALL_TOOLS` y `execute_tool`. La validación de tipos se aplica en **todos** los perfiles:
  montos negativos, cero, NaN o booleanos, ids como `"1 OR 1=1"`, claves faltantes o extra, emails inválidos
  o cuerpos enormes devuelven `invalid_arguments` sin tocar la base. Una herramienta inexistente devuelve
  `unknown_tool` y una no ofrecida devuelve `tool_not_allowed` (esto lo va a usar la corrección de V2).
- Vulnerabilidades marcadas:
  - `# VULN-V4`: `get_order` devuelve pedidos ajenos con nombre, email y dirección; `issue_refund` reembolsa
    pedidos ajenos sin confirmación; `send_email` envía a cualquier destinatario.
  - `# VULN-V1`: `issue_refund` aprueba sin aplicar plazo, monto máximo ni límite de un reembolso por pedido.

### Tarea 4: base de conocimiento vulnerable

- [`app/rag.py`](app/rag.py): `Chunk` (con `source` igual a `faq` o `review`), `IngestResult` y
  `KnowledgeBase` sobre Chroma embebido, en memoria (`path=None`, una colección propia por instancia) o
  persistente. Los embeddings los calcula quien construye la base, así Chroma nunca descarga su modelo por
  defecto. La telemetría de Chroma está desactivada. Cada FAQ se divide en fragmentos por sección `##` y una
  reingesta no duplica fragmentos.
- `# VULN-V2`: `add_review` guarda cualquier reseña tal cual, incluso con comentarios HTML o caracteres
  invisibles. Solo se rechaza una reseña vacía, en todos los perfiles.
- [`data/kb/`](data/kb/): FAQ de envíos, devoluciones (30 días, monto máximo y un reembolso por pedido),
  pagos y garantías.

### Tarea 5: prompts y orquestador

- [`app/prompts.py`](app/prompts.py): `INTERNAL_CODE_CANARY = "STAFF-CANARY-50"`,
  `INTERNAL_RULE_CANARY = "R-7741"` y `build_messages`. El prompt está escrito "como un equipo apurado",
  sin invitar al abuso:
  - `# VULN-V1`: las reglas de reembolso y descuento viven solo en el texto.
  - `# VULN-V3`: el código de descuento para empleados y la regla interna R-7741 están en el system prompt.
  - `# VULN-V2`: los fragmentos recuperados, incluidas las reseñas, se pegan en el system prompt sin
    delimitar ni marcar su origen.
- [`app/orchestrator.py`](app/orchestrator.py): `handle_message`, `Deps`, `ChatResult`, `ToolEvent` y
  `MAX_TOOL_ROUNDS = 3`. Recupera 3 fragmentos, arma el contexto, ejecuta las herramientas que pide el modelo
  y le devuelve el resultado como JSON (`role: tool`). La última ronda se hace sin ofrecer herramientas, así
  el ciclo siempre termina con texto. `LLMUnavailable` se propaga, para que el arnés lo cuente como error y no
  como ataque bloqueado. No modifica el historial recibido.

### Tarea 6: API e interfaz web

- [`app/main.py`](app/main.py): `create_app(profile, deps)` con `POST /api/login` (cookie `HttpOnly`,
  `SameSite=Lax`, token aleatorio guardado en el servidor), `POST /api/chat`, `POST /api/reviews`,
  `GET /api/config` (`html` sin `fix_v5`, `text` con `fix_v5`; marcado `# VULN-V5`), `GET /health` y
  `POST /api/logout`.
  - El historial vive en el servidor, por sesión, y la identidad sale solo de la cookie (un `customer_id`
    en el cuerpo se ignora).
  - Si el modelo no está disponible, la API responde 503 y ese turno no queda en el historial.
  - Un mensaje vacío, en blanco o que no es texto responde 422.
  - La semilla es aleatoria por pedido; la tarea 17 agrega `DEMO_SEED`.
  - `app_from_env()` arma la app real con Ollama, SQLite y Chroma persistentes, a partir de las variables
    de entorno.
- [`app/static/`](app/static/): `index.html` sin JS inline (solo `<script src>`), `chat.js` y `style.css`.
  Tiene login, chat y formulario de reseñas, y muestra un aviso de laboratorio vulnerable. `// VULN-V5`: con
  `render_mode: "html"` la respuesta del modelo se inserta con `innerHTML`; los mensajes del usuario siempre
  usan `textContent`.
- **Verificado en navegador** con un modelo falso: login, chat, consulta de pedido con herramienta y
  publicación de reseña funcionan. En el perfil vulnerable, un `<img onerror=...>` en la respuesta del
  modelo **se ejecutó** (cambió el título de la página), así que V5 queda demostrable.

### Tarea 7: Docker Compose (parcial)

- [`docker-compose.yml`](docker-compose.yml):
  - `ollama` solo en la red interna `lab`, sin puertos publicados y con `OLLAMA_NUM_PARALLEL=1`.
  - `ollama-init` (perfil `setup`) es el único servicio en la red `egress` y descarga los modelos al
    volumen compartido.
  - `app-vulnerable` (`127.0.0.1:8001`) y `app-segura` (`127.0.0.1:8002`) usan volúmenes de datos separados.
  - `harness` (perfil `tools`) está solo en `lab`, monta `./attacks` y `./results` y recibe `GIT_SHA`.
- [`docker-compose.gpu.yml`](docker-compose.gpu.yml): override opcional para GPU NVIDIA.
- [`Dockerfile`](Dockerfile) (usuario sin privilegios, `uv sync --frozen`) y `.dockerignore`.
- [`README.md`](README.md): aviso de aplicación vulnerable, requisitos, uso con y sin GPU, variables
  (incluida `OLLAMA_BASE_URL`), desarrollo sin Docker, usuarios de demo y tabla de vulnerabilidades.
- [`tests/test_compose.py`](tests/test_compose.py): puertos solo en localhost, Ollama sin puertos, perfiles
  y volúmenes separados, red `lab` interna, Ollama y arnés solo en `lab`, solo `ollama-init` con salida a
  Internet, y otras verificaciones. `docker compose config` valida los dos archivos.
- [`tests/test_e2e_smoke.py`](tests/test_e2e_smoke.py) (marcado `llm`): con el modelo real, responde una FAQ
  y consulta el pedido 1001.

## Pendiente para cerrar la Fase A

1. **Tarea 2, pasos 2 a 5:** instalar Ollama (o usar `ollama-init`), ejecutar `scripts/model_spike.py` con
   `llama3.2:3b` y `qwen2.5:7b` en la máquina más débil y en la de medición, y completar
   `docs/decisiones/modelo.md`. Es el **punto de control del viernes 6 de noviembre**, que ya está atrasado.
2. **Tarea 7, paso 4:** con Docker Desktop iniciado, ejecutar:
   - `docker compose --profile setup run --rm ollama-init`
   - `docker compose up -d --build`
   - `docker compose run --rm harness pytest -m llm tests/test_e2e_smoke.py -v`

   Después, comprobar en `http://127.0.0.1:8001` que el asistente responde una FAQ y consulta un pedido.
   Todavía **no se construyó la imagen**, porque el daemon de Docker no estaba corriendo.
3. **Confirmar que existe la imagen `ollama/ollama:0.12.6`** (se puede cambiar con `OLLAMA_IMAGE`) y fijar la
   imagen base de Python a una versión exacta o un digest.
4. **Commits:** el plan pide un commit por tarea, pero no se hizo ninguno (ver decisiones). Mensajes sugeridos:
   - `feat: add security profiles and LLM client`
   - `docs: record model selection` (cuando se complete la tarea 2)
   - `feat: add orders database and vulnerable tools`
   - `feat: add knowledge base with unvalidated ingestion`
   - `feat: add prompts and tool-calling orchestrator`
   - `feat: add chat API and web interface`
   - `feat: add docker compose lab environment`
5. **Decisión D1:** asignar los `[Integrante N]` de la sección 3 del plan.

## Decisiones tomadas durante la implementación

Son puntos en los que el plan no decía nada o en los que me aparté de él. Cada uno incluye qué cuesta si
la decisión resulta incorrecta.

1. **No se hicieron commits.** El pedido fue implementar y documentar, no commitear, y la rama actual es
   `main`. Si se prefiere un commit por tarea, se pueden separar a mano. *Si es incorrecta:* un commit grande
   o separar los archivos manualmente.
2. **La tarea 3 se hizo antes que la 2**, porque el script de la tarea 2 necesita `TOOL_SCHEMAS` para medir
   tool calls. *Si es incorrecta:* nada.
3. **Python 3.12 lo instala uv**: la máquina tiene Python 3.13 y uv descargó 3.12.16 dentro de `.venv`.
   Como `.venv` queda dentro de OneDrive, conviene excluirlo de la sincronización.
4. **`LLMReply` tiene dos campos opcionales extra**, `prompt_eval_count` y `eval_count`, que necesita el
   script de la tarea 2 para detectar contexto truncado. Son compatibles con la firma del plan.
5. **Códigos de error de herramientas:** `unknown_tool`, `tool_not_allowed`, `invalid_arguments` y
   `not_found`. Las tareas 10 y 13 agregan `policy_*` y `forbidden`.
6. **Las herramientas aceptan ids y montos numéricos escritos como texto** (`"1001"`, `"10"`), porque los
   modelos chicos los mandan así; cualquier otro texto se rechaza. También se rechazan las claves extra, para
   que el modelo no pueda pasar, por ejemplo, `customer_id`. *Si es incorrecta:* menos tool calls válidas
   del modelo real.
7. **Las contraseñas se guardan con hash (PBKDF2)**, aunque el plan no lo pedía, para no sumar una
   vulnerabilidad clásica que no forma parte del laboratorio.
8. **Se agregó `POST /api/logout`**, que el plan no menciona. Solo borra la sesión propia y no es una ruta
   de "reset".
9. **`POST /api/reviews` exige sesión iniciada**, como una tienda real.
10. **La última ronda del ciclo de herramientas no ofrece herramientas** y, si el modelo no devuelve texto,
    se usa una respuesta de respaldo. Así siempre hay respuesta, con como máximo `MAX_TOOL_ROUNDS + 1`
    llamadas al modelo.
11. **El historial que se envía al modelo se limita a los últimos 20 mensajes**, para no superar `num_ctx`.
12. **Hasta la Fase C, el perfil `segura` se comporta igual que `vulnerable`**, salvo que `/api/config`
    devuelve `render_mode: "text"`. Las correcciones (`FIX-Vn`) se implementan en las tareas 10 a 14.
    **No hay que medir nada con `segura` antes de eso.**
13. **La imagen del arnés incluye las dependencias de desarrollo** (pytest), para usar la misma imagen en
    las apps y el arnés.
14. **El script de la tarea 2 se escribió antes que su test.** El plan no pedía test para ese script; se
    agregó uno después, con el modelo falso.

## Cómo verificar lo hecho

```bash
python -m pip install uv
```

```bash
python -m uv sync
```

```bash
python -m uv run pytest
```

Resultado esperado: `137 passed, 2 deselected`.

## Archivos creados

```text
.dockerignore  .env.example  .gitignore  Dockerfile  README.md  avances.md
docker-compose.yml  docker-compose.gpu.yml  pyproject.toml  uv.lock
app/__init__.py  config.py  llm.py  db.py  tools.py  rag.py  prompts.py  orchestrator.py  main.py
app/static/index.html  chat.js  style.css
data/kb/devoluciones.md  envios.md  pagos.md  garantias.md
docs/decisiones/modelo.md
scripts/__init__.py  model_spike.py
tests/__init__.py  conftest.py  fakes.py  test_config.py  test_llm.py  test_db.py  test_tools.py
tests/test_rag.py  test_orchestrator.py  test_api.py  test_compose.py  test_e2e_smoke.py  test_model_spike.py
attacks/.gitkeep  results/final/.gitkeep
```
