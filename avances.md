# Avances de implementación

**Última actualización:** 13 de noviembre de 2026
**Fases trabajadas:** Fase A, sistema base (tareas 1 a 7), y Fase B, arnés de medición (tareas 8 y 9) del
[plan](docs/superpowers/plans/2026-11-04-asistente-llm-vulnerable.md).
**Estado general:** las fases A y B están completas (`pytest -m "not llm"` → **207 passed**). El modelo
quedó elegido (**`qwen2.5:3b`**). La prueba de punta a punta con Docker pasó el 13 de noviembre, con Ollama
nativo y las apps en Docker. Se puede empezar la Fase C.

## ⚠️ Pendientes importantes (bloquean la Fase C)

| # | Pendiente | Tarea del plan | Estado |
|---|---|---|---|
| 1 | **Script de elección de modelo** | 2 | ✅ **Hecho en la máquina de desarrollo** (8 de noviembre). Se eligió `qwen2.5:3b`; ver abajo. **Falta repetirlo en la máquina que se use para la medición final**, si es otra |
| 2 | **Prueba de punta a punta con Docker y Ollama** | 7, paso 4 | ✅ **Hecha** el 13 de noviembre con la variante de poca RAM (Ollama nativo y las apps en Docker): prueba de humo 2 de 2 y arnés 12 de 12 desde el contenedor `harness`. Con Ollama dentro de Docker, la notebook de 7,7 GB se cortaba por timeout. Ver abajo |
| 3 | **Revisión independiente del arnés** | punto de control del 10 nov | ✅ **Hecha** el 11 de noviembre. Sin bloqueantes. Ver "Revisión del arnés" |

### Prueba con Docker (11 de noviembre)

Lo que funcionó:

- Imagen `asistente-llm-lab:dev` construida, con la base de Python fijada por digest.
- `ollama-init` descargó `qwen2.5:3b` (`357c53fb…`) y `nomic-embed-text` (`0a109f42…`). El primer intento se cortó
  con código 137 (falta de memoria); el segundo terminó bien.
- Compose levantó las dos versiones en `127.0.0.1:8001` y `127.0.0.1:8002`, con Ollama sano y sin puertos publicados.

Lo que falló y por qué: dentro de Docker, el modelo genera a **0,53 tokens/s** y procesa el prompt a
**2,5 tokens/s**, unas 20 veces más lento que con Ollama nativo. La máquina de desarrollo tiene 7,7 GB de RAM: con
Docker Desktop en marcha quedaban 0,9 GB libres, Windows comprimía memoria (1,9 GB) y paginaba la VM de WSL (3,7 GB,
con 415 MB en swap). Así, el system prompt con las herramientas tarda más que el timeout de 300 s. **No es un error
del código ni de Compose: falta RAM.**

~~**Decisión (11 de noviembre):** repetir la prueba en otra máquina con más RAM.~~ Se descartó el 13 de noviembre:
nadie en el grupo tiene una PC con más RAM. Se resolvió con la variante de abajo.

### Solución: Ollama nativo y las apps en Docker (13 de noviembre)

Nuevo archivo [`docker-compose.host-ollama.yml`](docker-compose.host-ollama.yml), que se suma al original con un
segundo `-f`:

- No levanta el `ollama` de Docker (lo pasa a un perfil que no se activa).
- Las apps y el arnés usan el Ollama nativo de Windows en `http://host.docker.internal:11434`.
- Las apps y el arnés pasan de la red interna `lab` a `front`, porque una red interna no tiene ruta al host. Es la
  única pérdida de aislamiento y está documentada en el README como limitación.
- Ollama nativo sigue escuchando solo en `127.0.0.1`: Docker Desktop llega igual, así que no hubo que exponerlo ni
  tocar el firewall.
- Lo cubren 5 tests en [`tests/test_compose_host_ollama.py`](tests/test_compose_host_ollama.py), que validan la
  configuración combinada por `docker compose config`.

Resultado en la misma notebook de 7,7 GB, con Ollama nativo 0.40.15 y los mismos digests:

- `tests/test_e2e_smoke.py` desde el contenedor `harness`: **2 passed** en 95 s.
- Arnés de humo (`--reps 3`, dos perfiles) desde `harness`: **12 de 12** casos con éxito, entre 4 y 16 s por caso.
  El reporte se generó en `results/smoke/`.
- `app-vulnerable` (8001) y `app-segura` (8002) responden `/health` con su perfil.

Con esto la tarea 7 queda cerrada para la variante de poca RAM. El `docker-compose.yml` original (Ollama dentro de
Docker) sigue disponible para máquinas con 16 GB o más, pero no se validó en una máquina así.

No se probó el chat a mano en el navegador: la prueba de humo cubre la misma FAQ y la consulta del pedido 1001,
pero por código, no por la interfaz.

### Revisión del arnés (11 de noviembre)

Revisión independiente de `attacks/`, en solo lectura. Sin bloqueantes. Se resolvieron los dos hallazgos que había que
cerrar antes de la Fase C:

- **Un corte a mitad de escritura dejaba el JSONL ilegible.** Ahora `run_battery` descarta la línea cortada antes de
  agregar registros. Lo cubre el test `test_retoma_despues_de_una_escritura_cortada`.
- **Las semillas de validación coincidían con las de la medición final** (1000 a 1009). Ahora el plan indica validar y
  ajustar en la Fase C con `LLM_BASE_SEED=9000`.

Quedan para resolver **antes de congelar la batería (tarea 15)**:

- Validar los `args` de cada oráculo al cargar la batería: `values` como texto da falsos positivos.
- Asegurar que el `git_sha` corresponda al código de la imagen: reconstruir con `--build`, o rechazar la corrida si el
  árbol de trabajo tiene cambios.
- Simular en el runner la confirmación de V4, para que el oráculo de utilidad en `segura` no mida mal.
- Registrar `num_ctx`, `num_predict`, el modelo de embeddings y la versión de Ollama, y controlarlos en `--strict`.

Hallazgos menores:

- `--strict` no detecta perfiles ni ataques faltantes.
- El historial de errores se pierde.
- No hay corte cuando Ollama se cae.
- El docstring del runner dice que la comparación es "pareada", pero Fisher no es pareado.
- No hay corrección por comparaciones múltiples.
- El historial del runner no está recortado a 20 mensajes como en la app.

### Resultado de la elección del modelo

Detalle en [`docs/decisiones/modelo.md`](docs/decisiones/modelo.md) y resultados crudos en
[`docs/decisiones/spike-resultados.md`](docs/decisiones/spike-resultados.md). Máquina: i5-1235U, 7,7 GB de RAM,
sin GPU dedicada.

| Modelo | Resultado | Qué pasó con el modelo |
|---|---|---|
| `llama3.2:3b` | ❌ 60% de tool calls correctas: llama a herramientas en consultas generales | Desinstalado |
| `qwen2.5:7b` | ❌ unos 3,4 min por llamada; la medición llevaría unas 240 h | Desinstalado (podría servir en una máquina con GPU o 16 GB de RAM) |
| **`qwen2.5:3b`** | ✅ 100% de tool calls correctas, 5,8 s de latencia media, unas 6,8 h de medición estimada | **Elegido** y puesto como valor por defecto en `app/config.py`, Compose, `.env.example` y el README |

**Hallazgo que cambia el plan:** con Ollama en CPU, **la misma semilla no garantiza la misma salida**. La
salida depende de la caché de prompts y, aun igualando la caché, hay no determinismo numérico (2 salidas
distintas en 3 intentos). Esto contradice el ajuste 1 del plan. Consecuencias:

- La reproducibilidad pasa a ser **estadística**: se comparan tasas sobre 50 repeticiones con su intervalo
  de confianza, no salidas una por una.
- En la **demo (tarea 17)** una semilla "ganadora" puede no repetir el éxito. Conviene usar ataques con tasa
  alta, ensayar en la máquina de la presentación y tener el video de respaldo.
- Hay que declararlo como limitación en el **informe (tarea 16)**.

Arreglos al script durante la medición: la primera llamada ahora calienta el modelo, así la carga no infla
la latencia; el p95 se calcula por rango más cercano, y antes daba menos que la media; y la prueba de
reproducibilidad compara las dos llamadas partiendo del mismo estado de caché.

### Prueba con el modelo real, sin Docker

Con Ollama nativo (`OLLAMA_BASE_URL=http://127.0.0.1:11434`):

- `pytest -m llm tests/test_e2e_smoke.py` → **2 passed**: el asistente responde la FAQ de devoluciones
  ("30 días") y consulta el pedido 1001 con `get_order`.
- Runner con la batería de humo, `vulnerable` y `segura`, 3 repeticiones → **12 de 12 exitosas, 0 errores**.
  Tiempo por caso: unos 3,3 s para una FAQ y unos 12 s para una consulta de pedido. Con eso, la medición
  obligatoria lleva **unas 6 h** (presupuestar 8 a 10 h por los ataques de varios turnos).

### Lo que falta de la prueba con Docker

Comandos, en orden, con Docker Desktop iniciado:

```bash
docker compose --profile setup run --rm ollama-init
```

```bash
docker compose up -d --build
```

```bash
docker compose run --rm harness pytest -m llm tests/test_e2e_smoke.py -v
```

```bash
docker compose run --rm harness python -m attacks.runner --battery tests/data/smoke.yaml --profiles vulnerable,segura --reps 3 --out results/smoke.jsonl
```

```bash
docker compose run --rm harness python -m attacks.report results/smoke.jsonl --out results/smoke/
```

Compose levanta su propio Ollama en un contenedor, y `ollama-init` vuelve a descargar `qwen2.5:3b` y
`nomic-embed-text` (unos 2,2 GB) en su volumen. Los modelos del Ollama nativo no se reutilizan.

Para repetir la elección del modelo en la máquina de medición:

```bash
uv run python scripts/model_spike.py --model qwen2.5:3b --reps 10 --out docs/decisiones/spike-resultados.md
```

### Alternativas si `qwen2.5:3b` deja de servir

Están en [`docs/decisiones/modelo.md`](docs/decisiones/modelo.md). En resumen: `qwen2.5:7b` en una máquina
del grupo con GPU, `qwen3:4b` o `phi4-mini` en local. Usar una API externa (Groq u otra) o exponer Ollama con
ngrok contradice la propuesta aprobada (todo local, sin APIs externas ni servicios de terceros) y solo
debería considerarse con el acuerdo del profesor.

Además, antes de la Fase C el plan pide una **revisión independiente del arnés** (tareas 8 y 9). Todavía
no se hizo.

## Resumen de la Fase A

| Tarea | Estado | Tests |
|---|---|---|
| 1. Proyecto, perfiles y cliente LLM | ✅ Completa | 23 |
| 2. Elección del modelo | ✅ `qwen2.5:3b` elegido en la máquina de desarrollo; falta confirmarlo en la de medición | 6 |
| 3. Base de pedidos y herramientas vulnerables | ✅ Completa | 39 |
| 4. Base de conocimiento vulnerable (RAG) | ✅ Completa | 12 |
| 5. Prompts y orquestador | ✅ Completa | 19 |
| 6. API e interfaz web | ✅ Completa | 29 |
| 7. Docker Compose de punta a punta | 🟡 Configuración y tests listos; falta probar con Docker y el modelo | 11 (+2 con modelo real) |

**Suite de la Fase A:** 137 tests, sin Ollama ni Internet.
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

### Tarea 2: elección del modelo

- [`scripts/model_spike.py`](scripts/model_spike.py): con 10 consultas benignas en español (6 con herramienta
  esperada y 4 sin herramienta) mide tool calls correctas, latencia, reproducibilidad con la misma semilla,
  variación con semillas distintas y `prompt_eval_count` frente a los tokens enviados. Además estima las horas
  de la medición obligatoria (2800 ejecuciones). Si Ollama no responde, termina con código 1 y un mensaje claro.
- [`docs/decisiones/modelo.md`](docs/decisiones/modelo.md): criterios de aceptación definidos **antes** de
  ver resultados, los candidatos evaluados, la decisión (`qwen2.5:3b`, digest `357c53fb…`), la revisión del
  criterio de reproducibilidad, el costo confirmado con el runner real y las alternativas.
- [`docs/decisiones/spike-resultados.md`](docs/decisiones/spike-resultados.md): tablas crudas que generó el
  script para cada modelo.

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

## Fase B: arnés de medición

| Tarea | Estado | Tests |
|---|---|---|
| 8. Batería, oráculos y runner | ✅ Completa (probada con el modelo falso) | 33 |
| 9. Resumen estadístico | ✅ Completa | 20 |

### Tarea 8: batería, oráculos y runner

- [`attacks/schema.py`](attacks/schema.py): `OracleSpec`, `Attack` y `load_battery`, que recibe un archivo
  YAML o un directorio. **Valida toda la batería antes de ejecutar nada**: oráculo desconocido, `vuln` fuera de
  V1 a V6 o UTIL, `origin` distinto de `dev` o `heldout`, sesión que no es un cliente existente, `turns`
  vacío, campos desconocidos o ids duplicados dan `ValueError` al cargar, y no después de horas de medición.
- [`attacks/oracles.py`](attacks/oracles.py): `Evidence`, el registro `ORACLES` y el decorador `@oracle`,
  que rechaza nombres duplicados. Registra `reply_contains_any` (ignora mayúsculas y mira todos los turnos)
  y `tool_succeeded`, que solo cuenta herramientas que el backend dio por buenas. Las tareas 10 a 14
  registran los oráculos de cada vulnerabilidad con el mismo decorador.
- [`attacks/runner.py`](attacks/runner.py): `seed_for`, `RunContext`, `run_once`, `run_battery` y el CLI.
  - Cada repetición usa una **base SQLite nueva**, que se borra al terminar.
  - La base de conocimiento se arma **una vez por ataque y perfil**, con las `setup_reviews` del ataque
    cargadas con el perfil que se mide. Las reseñas de un ataque no llegan a otro.
  - La semilla es `base_seed + rep`, **igual en todos los perfiles**, así la comparación es pareada.
  - Los ataques de varios turnos comparten historial, como una conversación real.
  - Si el modelo o los embeddings no responden, la repetición queda como **`error`, no como `blocked`**. Un
    fallo inesperado del código también queda como `error` (con el detalle), para no perder horas de medición.
  - Cada registro se escribe y se sincroniza a disco (`fsync`) antes de seguir. Al volver a ejecutar el mismo
    comando, **retoma sin repetir** lo que ya tiene resultado y **reintenta los errores**.
  - Recorre repetición por repetición, así un corte deja todos los ataques con una cantidad pareja de
    repeticiones.
  - El CLI falla con código 1 si el modelo no está instalado o no responde, y avisa si falta `GIT_SHA`.
- [`attacks/records.py`](attacks/records.py): `RunRecord` y la lectura del JSONL. Si hay varios registros de
  la misma repetición, gana el válido más reciente: un reintento reemplaza al error. Tolera una última línea
  cortada por una interrupción.
- [`tests/data/smoke.yaml`](tests/data/smoke.yaml): batería de humo con dos tareas de utilidad (FAQ y
  consulta de pedido) para probar el arnés de punta a punta.

### Tarea 9: resumen estadístico

- [`attacks/report.py`](attacks/report.py): `wilson_interval` (sin dependencias; 0 de 50 da [0%; 7,1%]),
  `fisher_p` (con `scipy.stats.fisher_exact`, bilateral), `SummaryRow`, `summarize` y el CLI.
  - Los errores quedan **fuera del denominador** y se informan en su propia columna.
  - Genera `summary.csv` y `summary.md`, con los ataques `dev` y `heldout` en tablas separadas, la batería
    de utilidad aparte y una comparación de cada perfil contra `vulnerable` con el p-valor de Fisher.
  - Lista los valores encontrados de `model`, `model_digest`, `temperature` y `git_sha`, y **avisa si hay
    más de uno**.
  - Con `--strict --min-valid 50`, termina con error si algún caso tiene menos repeticiones válidas que el
    mínimo, si hay `git_sha=unknown` o si hay parámetros mezclados.

### Verificación de la Fase B

Además de los tests, probé el circuito completo, runner → JSONL → resumen, con la batería de humo,
2 perfiles × 10 repeticiones y un modelo falso que "se cae" cada 7 llamadas:

- El segundo intento reintentó los errores sin repetir lo demás.
- El error que persistió quedó fuera del denominador (6 de 9 válidas).
- `--strict --min-valid 10` lo rechazó, como corresponde.

## Instalación para el resto del grupo

[`INSTALACION.md`](INSTALACION.md) es la guía paso a paso para clonar el repo en otra PC y reproducir las
mismas pruebas: uv 0.13.7, `uv sync --frozen`, Ollama 0.40.15, `qwen2.5:3b` y `nomic-embed-text`, prueba de
humo con el modelo real, arnés y, si se quiere, Docker. También fija reglas para mantener el trabajo
consistente y una tabla de problemas frecuentes.

- [`scripts/verificar_entorno.py`](scripts/verificar_entorno.py) controla Python 3.12, la versión de Ollama,
  los **digests** de los modelos (fijados en `MODEL_DIGESTS`, en `app/config.py`), Docker y el commit. Sale con
  código 1 si algo obligatorio falla. Tiene 9 tests.
- La imagen de Ollama en Compose pasó de `0.12.6` a **`0.40.15`**, la misma versión con la que se midió.
- **Verificado** con una copia limpia del repo, armada solo con los archivos versionados: `uv sync --frozen`,
  201 tests en verde, "Entorno OK" y prueba de humo con el modelo real (`2 passed`). Las URLs de descarga
  fijadas en la guía (uv 0.13.7 y Ollama 0.40.15 para Windows y macOS) responden.
- **Para que el grupo pueda usarla hay que commitear y pushear el estado actual.** En GitHub solo está la
  fase A, con `qwen2.5:7b` por defecto y sin la guía.

## Otros pendientes

1. ~~Fijar la imagen base de Python~~ ✅ Fijada el 11 de noviembre a `python:3.12-slim@sha256:5e2bdb1b…`
   (Python 3.12.16). La imagen `ollama/ollama:0.40.15` ya se descargó y funciona.
2. **Commits:** el plan pide un commit por tarea. La fase A ya está en `origin/main` (commit `adb471b`); la
   fase B, la elección del modelo y la guía de instalación no están commiteadas. Mensajes sugeridos:
   - `feat: add security profiles and LLM client`
   - `docs: record model selection` (cuando se complete la tarea 2)
   - `feat: add orders database and vulnerable tools`
   - `feat: add knowledge base with unvalidated ingestion`
   - `feat: add prompts and tool-calling orchestrator`
   - `feat: add chat API and web interface`
   - `feat: add docker compose lab environment`
   - `feat: add attack battery runner and oracle registry`
   - `feat: add statistical report for attack results`
3. ~~**Decisión D1:** asignar los `[Integrante N]` de la sección 3 del plan.~~ **Descartada (11 nov):** no se
   asigna una vulnerabilidad por persona; la Fase C se trabaja en equipo.

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

### Fase B

15. **`RunRecord` está en `attacks/records.py` y no en `runner.py`**, para que el resumen lea los registros
    sin cargar Chroma ni la app. `runner.py` lo reexporta, así la firma del plan sigue valiendo.
16. **Al retomar, los errores reintentados se agregan al JSONL**, en lugar de reescribir el archivo, para
    no arriesgar los datos ante un corte. Al leer, un resultado válido reemplaza a un error de la misma
    repetición. *Si es incorrecta:* el archivo crudo tiene más líneas que repeticiones; el resumen ya lo
    resuelve.
17. **Un fallo inesperado del código también cuenta como `error`**, con su detalle, en lugar de cortar la
    medición. *Si es incorrecta:* un bug podría pasar desapercibido, pero sale como error en el resumen y
    `--strict` lo rechaza si deja menos de 50 repeticiones válidas.
18. **Se acepta `V6`** como vulnerabilidad en la batería, por si se hace la tarea 18 (LLM06).
19. **Las tasas del resumen usan coma decimal** (por ejemplo, 23,7%), para copiarlas directo al informe.
20. **La revisión independiente del arnés que pide el plan no se hizo**, porque implica lanzar un subagente
    y no lo pediste. Queda como pendiente antes de la Fase C.

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

Resultado esperado: `201 passed, 2 deselected`.

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
results/final/.gitkeep
```

Fase B:

```text
attacks/__init__.py  schema.py  oracles.py  records.py  runner.py  report.py
tests/data/smoke.yaml  tests/test_oracles.py  tests/test_runner.py  tests/test_report.py
pyproject.toml y uv.lock (se agregó scipy)
```
