"""API HTTP e interfaz web del asistente.

El historial de cada conversación vive en el servidor, asociado a la sesión: el cliente
no puede fabricar turnos del asistente. La identidad sale siempre de la cookie de sesión,
nunca del cuerpo del pedido. No hay rutas de "reset" de laboratorio: serían superficie de
ataque y el arnés no las necesita.

Arranque con datos reales (lo usa el Dockerfile):
    uvicorn --factory app.main:app_from_env
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictStr, field_validator

from app.config import DEFAULT_EMBED_MODEL, SecurityProfile, load_profile, model_params_from_env
from app.db import connect, init_db, verify_password
from app.llm import LLMUnavailable, OllamaClient
from app.orchestrator import Deps, handle_message
from app.rag import KnowledgeBase
from app.tools import Session

log = logging.getLogger("asistente")

STATIC_DIR = Path(__file__).resolve().parent / "static"
KB_DIR = Path(__file__).resolve().parent.parent / "data" / "kb"
SESSION_COOKIE = "session"
MAX_HISTORY_MESSAGES = 20


class LoginIn(BaseModel):
    customer_id: StrictStr
    password: StrictStr


class ChatIn(BaseModel):
    message: StrictStr

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El mensaje no puede estar vacío")
        return v


class ReviewIn(BaseModel):
    text: StrictStr


@dataclass
class Conversation:
    session: Session
    history: list[dict] = field(default_factory=list)


class SessionStore:
    def __init__(self):
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def create(self, session: Session) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._items[token] = Conversation(session)
        return token

    def get(self, token: str | None) -> Conversation | None:
        if not token:
            return None
        with self._lock:
            return self._items.get(token)

    def delete(self, token: str | None) -> None:
        with self._lock:
            self._items.pop(token or "", None)


def create_app(profile: SecurityProfile, deps: Deps) -> FastAPI:
    app = FastAPI(title="TiendaFicticia — asistente", docs_url=None, redoc_url=None, openapi_url=None)
    sessions = SessionStore()
    # La conexión SQLite y la colección de Chroma se comparten entre hilos: se serializa
    # el trabajo. Con un solo modelo local tampoco hay paralelismo real que ganar.
    work_lock = threading.Lock()

    def current(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> tuple[str, Conversation]:
        conv = sessions.get(session)
        if conv is None:
            raise HTTPException(status_code=401, detail="Iniciá sesión")
        return session, conv

    @app.get("/health")
    def health():
        return {"status": "ok", "profile": profile.name}

    @app.post("/api/login")
    def login(body: LoginIn, response: Response):
        with work_lock:
            ok = verify_password(deps.conn, body.customer_id, body.password)
            row = deps.conn.execute("SELECT email FROM customers WHERE id = ?", (body.customer_id,)).fetchone() if ok else None
        if not ok or row is None:
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
        token = sessions.create(Session(customer_id=body.customer_id, email=row["email"]))
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/")
        return {"customer_id": body.customer_id}

    @app.post("/api/logout")
    def logout(response: Response, session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
        sessions.delete(session)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/chat")
    def chat(body: ChatIn, auth: tuple[str, Conversation] = Depends(current)):
        _, conv = auth
        seed = secrets.randbelow(2**31)
        try:
            with work_lock:
                result = handle_message(body.message, conv.history[-MAX_HISTORY_MESSAGES:], conv.session,
                                        deps, profile, seed)
        except LLMUnavailable as exc:
            log.warning("Modelo no disponible: %s", exc)
            raise HTTPException(status_code=503, detail="El asistente no está disponible en este momento") from None
        conv.history += [{"role": "user", "content": body.message}, {"role": "assistant", "content": result.reply}]
        return {"reply": result.reply, "pending_confirmation": result.pending_confirmation}

    @app.post("/api/reviews")
    def add_review(body: ReviewIn, auth: tuple[str, Conversation] = Depends(current)):
        try:
            with work_lock:
                r = deps.kb.add_review(body.text, profile)
        except LLMUnavailable:
            raise HTTPException(status_code=503, detail="No se pudo procesar la reseña ahora") from None
        return {"accepted": r.accepted, "reason": r.reason}

    @app.get("/api/config")
    def config():
        # VULN-V5: sin la corrección, la interfaz inserta la respuesta del modelo como HTML.
        return {"render_mode": "text" if profile.fix_v5 else "html"}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def app_from_env() -> FastAPI:
    """Construye la app con Ollama, SQLite y Chroma reales a partir de variables de entorno."""
    logging.basicConfig(level=logging.INFO)
    env = os.environ
    profile = load_profile(env.get("SECURITY_PROFILE"))  # sin perfil, la app no arranca
    params = model_params_from_env(env)
    llm = OllamaClient(
        env.get("OLLAMA_BASE_URL", "http://ollama:11434"),
        params,
        env.get("EMBED_MODEL", DEFAULT_EMBED_MODEL),
        float(env.get("LLM_TIMEOUT_S", "120")),
    )
    data_dir = Path(env.get("DATA_DIR", "var"))
    db_path = data_dir / "orders.sqlite3"
    init_db(db_path, datetime.now(UTC))
    kb = KnowledgeBase(data_dir / "chroma", llm.embed)
    kb.ingest_faq(KB_DIR)
    log.info("Perfil %s, modelo %s, datos en %s", profile.name, params.model, data_dir)
    return create_app(profile, Deps(llm=llm, kb=kb, conn=connect(db_path)))
