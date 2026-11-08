# Instalación en otra PC

Guía para que cada integrante del grupo clone el repositorio y reproduzca las mismas pruebas, con
**exactamente las mismas versiones** de Python, dependencias, Ollama y modelo. Al final, el script
`scripts/verificar_entorno.py` confirma que tu máquina coincide con la de referencia.

- **Tiempo estimado:** de 30 a 45 minutos, más lo que tarde la descarga de unos 3 GB.
- **Sistema principal:** Windows 10/11 con PowerShell. Para macOS y Linux están los comandos
  equivalentes en cada paso.

> ⚠️ El asistente es **vulnerable a propósito**. Todo corre en tu máquina, contra `127.0.0.1`. No lo
> expongas en la red ni lo publiques con túneles como ngrok.

## Versiones de referencia

Son las que se usaron para elegir el modelo y probar el sistema ([`docs/decisiones/modelo.md`](docs/decisiones/modelo.md)).
Están fijadas en el repo: `uv.lock` fija las dependencias y `app/config.py`, los digests.

| Componente | Versión | Cómo se fija |
|---|---|---|
| Python | 3.12 (3.12.16 en la máquina de referencia) | `pyproject.toml`; uv lo descarga solo |
| uv | 0.13.7 | Se instala esa versión exacta |
| Dependencias de Python | las de `uv.lock` | `uv sync --frozen` |
| Ollama | **0.40.15** | Instalador de esa versión |
| Modelo de chat | `qwen2.5:3b`, digest `357c53fb659c…` | `MODEL_DIGESTS` en `app/config.py` |
| Modelo de embeddings | `nomic-embed-text`, digest `0a109f422b47…` | `MODEL_DIGESTS` en `app/config.py` |
| Docker Desktop | cualquiera reciente (opcional) | Solo para el laboratorio con Compose |

## Requisitos de la máquina

- **8 GB de RAM** como mínimo; el modelo usa unos 2,5 GB mientras responde. Con menos memoria funciona,
  pero muy lento.
- **6 GB libres en disco**: modelos, entorno de Python y, si usás Docker, sus imágenes.
- No hace falta GPU. Si tenés una NVIDIA, Ollama la usa sola y responde más rápido.
- Git instalado.
- Acceso al repositorio. Si es privado, pedile a Thomas que te agregue como colaborador en GitHub.

---

## Paso 1: instalar uv

uv instala Python 3.12 y las dependencias exactas del proyecto. Instalá la versión fija:

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.13.7/install.ps1 | iex"
```

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/0.13.7/install.sh | sh
```

Cerrá y volvé a abrir la terminal, y verificá:

```powershell
uv --version
```

Tiene que decir `uv 0.13.7`. Si ya tenés Python instalado, también sirve `python -m pip install uv==0.13.7`;
en ese caso, usá `python -m uv` en lugar de `uv` en el resto de los comandos.

## Paso 2: clonar el repositorio

Clonalo **fuera de OneDrive, Dropbox o Google Drive**. La carpeta `.venv` tiene miles de archivos y la
sincronización la vuelve lenta o la rompe. Por ejemplo, en `C:\dev`:

```powershell
mkdir C:\dev -Force; cd C:\dev
```

```powershell
git clone https://github.com/ThomasSalomon/TP_SEG.git
```

```powershell
cd TP_SEG
```

## Paso 3: instalar las dependencias y correr los tests

```powershell
uv sync --frozen
```

`--frozen` instala exactamente lo que dice `uv.lock`, sin actualizar nada. Si falla con un mensaje sobre el
lockfile, no lo arregles con `uv lock`: avisá al grupo, porque significa que alguien cambió dependencias sin
commitear el `uv.lock`.

```powershell
uv run pytest
```

**Resultado esperado:** `201 passed, 2 deselected`. Estos tests usan un modelo falso, así que todavía no
necesitan Ollama. Los 2 "deselected" son los que usan el modelo real (paso 7).

## Paso 4: instalar Ollama 0.40.15

Instalá **esa versión exacta**, no la última. Otra versión puede dar resultados distintos con el mismo modelo.

- **Windows:** descargá `OllamaSetup.exe` de la página de la versión,
  <https://github.com/ollama/ollama/releases/tag/v0.40.15>, e instalalo.
- **macOS:** descargá `Ollama-darwin.zip` de la misma página, descomprimilo y mové `Ollama.app` a Aplicaciones.
- **Linux:**

  ```bash
  curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.40.15 sh
  ```

Abrí Ollama (en Windows queda como ícono junto al reloj) y verificá en una terminal nueva:

```powershell
ollama --version
```

Tiene que decir `0.40.15`.

> **No aceptes las actualizaciones automáticas** de Ollama mientras dure el TP. Si la app ofrece "Restart to
> update", ignoralo. Si se actualizó sin querer, reinstalá la 0.40.15.

## Paso 5: descargar los modelos

```powershell
ollama pull qwen2.5:3b
```

```powershell
ollama pull nomic-embed-text
```

Son unos 2,2 GB en total. Para confirmar:

```powershell
ollama list
```

En la columna `ID` tienen que aparecer `357c53fb659c` para `qwen2.5:3b` y `0a109f422b47` para
`nomic-embed-text`.

## Paso 6: verificar el entorno

```powershell
uv run python scripts/verificar_entorno.py
```

Resultado esperado (Docker puede quedar en ADVERTENCIA si no lo usás):

```text
[    OK     ] Python                   3.12.16
[    OK     ] Ollama                   responde en http://127.0.0.1:11434
[    OK     ] Versión de Ollama        0.40.15
[    OK     ] modelo qwen2.5:3b        digest 357c53fb659c
[    OK     ] modelo nomic-embed-text  digest 0a109f422b47
[ADVERTENCIA] Docker                   ...
[    OK     ] Commit                   <commit actual>

Entorno OK.
```

Si alguna línea dice **FALLA**, no sigas: buscá la solución en [Problemas frecuentes](#problemas-frecuentes).

## Paso 7: prueba de humo con el modelo real

Comprueba que el asistente responde una pregunta frecuente y consulta un pedido con el modelo de verdad.

Windows (PowerShell):

```powershell
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"; uv run pytest -m llm tests/test_e2e_smoke.py -v
```

macOS / Linux:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434 uv run pytest -m llm tests/test_e2e_smoke.py -v
```

**Resultado esperado:** `2 passed`, en 1 o 2 minutos.

## Paso 8: probar el arnés de medición

Corre la batería de humo (2 tareas legítimas) en las versiones `vulnerable` y `segura`, 3 veces cada una,
y genera el resumen estadístico. Reemplazá `<tu-nombre>` por tu nombre, para no mezclar archivos.

Windows (PowerShell):

```powershell
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"; uv run python -m attacks.runner --battery tests/data/smoke.yaml --profiles vulnerable,segura --reps 3 --out results/smoke-<tu-nombre>.jsonl
```

```powershell
uv run python -m attacks.report results/smoke-<tu-nombre>.jsonl --out results/smoke-<tu-nombre>/
```

En macOS / Linux, igual que en el paso 7: anteponé `OLLAMA_BASE_URL=http://127.0.0.1:11434` al primer
comando.

**Resultado esperado:** 12 ejecuciones, todas `success`, sin `error`. El resumen queda en
`results/smoke-<tu-nombre>/summary.md`. Los avisos de "mínimo 50" son normales con 3 repeticiones. La carpeta
`results/` está en `.gitignore`: estos archivos no se suben, salvo los de `results/final/`.

En la máquina de referencia, cada caso tardó unos 3,3 s (FAQ) y unos 12 s (consulta de pedido). Anotá
tus tiempos: sirven para elegir en qué máquina se hace la medición final.

## Paso 9 (recomendado): medir tu máquina con el script de elección de modelo

Tarda unos 15 minutos y dice cuánto llevaría la medición completa en tu PC. Es la base para elegir la
máquina de medición final, que tiene que ser una sola para todo el grupo.

```powershell
uv run python scripts/model_spike.py --model qwen2.5:3b --reps 10 --base-url http://127.0.0.1:11434
```

Pasale al grupo la latencia media, el costo estimado y los datos de tu máquina (CPU, RAM y GPU). No
commitees la tabla salvo que se acuerde: el registro oficial está en
[`docs/decisiones/spike-resultados.md`](docs/decisiones/spike-resultados.md).

## Paso 10 (opcional): usar el asistente en el navegador

Windows (PowerShell), versión vulnerable:

```powershell
$env:SECURITY_PROFILE = "vulnerable"; $env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"; $env:DATA_DIR = "var/vulnerable"; uv run uvicorn --factory app.main:app_from_env --host 127.0.0.1 --port 8001
```

Abrí <http://127.0.0.1:8001> e ingresá con `alice` / `alice-demo` (o `bob` / `bob-demo`). Son
credenciales ficticias del laboratorio. Para la versión segura, usá `SECURITY_PROFILE = "segura"`,
`DATA_DIR = "var/segura"` y el puerto `8002`.

> Hasta que se haga la Fase C, la versión `segura` todavía no tiene las correcciones: se comporta igual que
> la vulnerable, salvo que muestra las respuestas como texto.

## Paso 11 (opcional): laboratorio completo con Docker

> **Todavía no está validado de punta a punta** en ninguna máquina; es un pendiente de la tarea 7. Si lo
> probás, contale al grupo cómo te fue.

Compose levanta su propio Ollama (`ollama/ollama:0.40.15`) en una red interna, con las dos versiones del
asistente. Los modelos se vuelven a descargar dentro de un volumen de Docker; no se reutilizan los del
paso 5. Con Docker Desktop iniciado:

```powershell
docker compose --profile setup run --rm ollama-init
```

```powershell
docker compose up -d --build
```

```powershell
docker compose run --rm harness pytest -m llm tests/test_e2e_smoke.py -v
```

Versión vulnerable en <http://127.0.0.1:8001> y segura en <http://127.0.0.1:8002>.

---

## Reglas para que todos tengamos la misma versión

1. **Antes de trabajar**, actualizá y verificá:

   ```powershell
   git pull
   ```

   ```powershell
   uv sync --frozen
   ```

   ```powershell
   uv run pytest
   ```

2. **Antes de hacer push**, `uv run pytest` tiene que pasar entero.
3. **No cambies el modelo, los parámetros** (`LLM_TEMPERATURE`, `LLM_BASE_SEED`, etc.) **ni las dependencias**
   sin acordarlo con el grupo. Si hay que agregar una dependencia, usá `uv add <paquete>` y commiteá
   `pyproject.toml` y `uv.lock` juntos.
4. **No actualices Ollama ni vuelvas a hacer `ollama pull`** de los modelos sin correr después
   `scripts/verificar_entorno.py`. Un tag puede apuntar a otro modelo con el tiempo; el digest no.
5. **La medición final se hace en una sola máquina**, con `verificar_entorno.py` todo en OK, sin cambios sin
   commitear y con `GIT_SHA` definido (ver la tarea 15 del plan).
6. **No esperes salidas idénticas entre máquinas**, ni siquiera entre corridas. Con Ollama en CPU, la misma
   semilla no garantiza la misma respuesta. Lo que se compara son tasas sobre muchas repeticiones (ver
   `docs/decisiones/modelo.md`).

## Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `uv` no se reconoce como comando | La terminal se abrió antes de instalar uv | Cerrá y abrí la terminal, o usá `python -m uv` |
| `uv sync --frozen` falla por el lockfile | `pyproject.toml` y `uv.lock` no coinciden en el repo | No corras `uv lock`; avisá al grupo |
| `verificar_entorno`: Python en FALLA | Ejecutaste `python` en lugar de `uv run python` | Usá siempre `uv run …` |
| `verificar_entorno`: Ollama no responde | Ollama no está abierto | Abrilo (en Windows, desde el menú Inicio) y esperá unos segundos |
| Versión de Ollama en ADVERTENCIA | Se instaló o actualizó otra versión | Reinstalá la 0.40.15 (paso 4) |
| Modelo en FALLA por digest distinto | Se bajó otra versión del modelo | Avisá al grupo antes de seguir: el plan exige medir con el digest registrado |
| La prueba de humo tarda varios minutos o da timeout | Poca RAM libre, o el modelo se está cargando | Cerrá otros programas y reintentá; la primera llamada siempre es más lenta |
| Errores de caracteres raros (`UnicodeEncodeError`) en la consola | Consola con codificación vieja | En PowerShell: `$env:PYTHONIOENCODING = "utf-8"` |
| `docker compose` dice que no encuentra el daemon | Docker Desktop no está iniciado | Inicialo y esperá a que diga "Engine running" |

Si algo no está en esta tabla, anotá el comando, el mensaje completo y la salida de
`scripts/verificar_entorno.py`, y compartilo con el grupo.
