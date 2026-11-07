"""Base de conocimiento (RAG) con Chroma embebido.

Guarda dos tipos de fragmentos: las FAQ de la empresa (`faq`) y las reseñas que cargan
los clientes (`review`). Se conserva el origen de cada fragmento para que la versión
segura pueda tratar distinto el contenido no confiable (tarea 11).

Los embeddings los calcula quien construye la base (Ollama en producción, uno falso en
los tests), así Chroma nunca descarga su modelo por defecto.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import chromadb
from chromadb.config import Settings

from app.config import SecurityProfile

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class Chunk:
    text: str
    source: Literal["faq", "review"]
    doc_id: str


@dataclass(frozen=True)
class IngestResult:
    accepted: bool
    reason: str | None = None


_SETTINGS = Settings(anonymized_telemetry=False, allow_reset=False)
COLLECTION = "knowledge"  # Chroma exige nombres de 3 a 512 caracteres


def _split_sections(markdown: str) -> list[str]:
    """Un fragmento por sección `##`, con el título del documento como contexto."""
    title_match = re.search(r"^# (.+)$", markdown, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    sections = re.split(r"^## ", markdown, flags=re.MULTILINE)[1:]
    if not sections:
        return [markdown.strip()] if markdown.strip() else []
    return [f"{title}: {s.strip()}" if title else s.strip() for s in sections if s.strip()]


class KnowledgeBase:
    def __init__(self, path: Path | None, embed: Embedder):
        self._embed = embed
        if path is None:
            # En memoria (lo usa el arnés). Chroma comparte el sistema efímero dentro del
            # proceso, así que cada instancia usa una colección con nombre propio.
            client = chromadb.EphemeralClient(settings=_SETTINGS)
            name = f"{COLLECTION}-{uuid.uuid4().hex}"
        else:
            path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(path), settings=_SETTINGS)
            name = COLLECTION
        self._collection = client.get_or_create_collection(
            name, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        return self._collection.count()

    def _add(self, ids: list[str], texts: list[str], source: str, doc_ids: list[str]) -> None:
        self._collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=self._embed(texts),
            metadatas=[{"source": source, "doc_id": d} for d in doc_ids],
        )

    def ingest_faq(self, directory: Path) -> int:
        ids, texts, doc_ids = [], [], []
        for file in sorted(directory.glob("*.md")):
            for i, section in enumerate(_split_sections(file.read_text(encoding="utf-8"))):
                ids.append(f"faq-{file.stem}-{i}")
                texts.append(section)
                doc_ids.append(file.stem)
        if texts:
            self._add(ids, texts, "faq", doc_ids)
        return len(texts)

    def add_review(self, text: str, profile: SecurityProfile) -> IngestResult:
        if not text or not text.strip():
            return IngestResult(False, "empty")
        # VULN-V2: la reseña se guarda tal cual, sin validar ni limpiar. Si contiene
        # instrucciones (aunque estén ocultas en comentarios HTML o caracteres
        # invisibles), llegan al modelo cuando se recupera.
        doc_id = f"review-{uuid.uuid4().hex[:12]}"
        self._add([doc_id], [text], "review", [doc_id])
        return IngestResult(True)

    def retrieve(self, query: str, k: int = 3) -> list[Chunk]:
        total = self._collection.count()
        if total == 0 or k <= 0:
            return []
        res = self._collection.query(query_embeddings=self._embed([query]), n_results=min(k, total))
        return [
            Chunk(text=doc, source=meta["source"], doc_id=meta["doc_id"])
            for doc, meta in zip(res["documents"][0], res["metadatas"][0], strict=True)
        ]
