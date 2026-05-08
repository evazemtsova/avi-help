from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.api.models.Collection import Collection
from openai import OpenAI
from pydantic import BaseModel, Field

EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION_NAME = "avi_help"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CHROMA_PATH = _PROJECT_ROOT / "data" / "chroma"

_chroma_client: Optional[chromadb.api.ClientAPI] = None
_collection: Optional[Collection] = None
_openai_client: Optional[OpenAI] = None


class SearchHit(BaseModel):
    chunk_id: str
    article_id: int
    article_url: str
    title: str
    category: str
    section: Optional[str] = None
    lastmod: Optional[str] = None
    chunk_text: str
    chunk_index: int
    total_chunks: int
    score: float = Field(..., description="1 - cosine distance, выше = релевантнее")


def _resolve_chroma_path() -> Path:
    raw = os.getenv("CHROMA_PATH")
    if raw:
        return Path(raw)
    return _DEFAULT_CHROMA_PATH


def get_chroma_collection() -> Collection:
    """Открывает persistent Chroma-клиент и возвращает collection `avi_help`.
    Кэширует клиент и коллекцию на уровне модуля. Бросает RuntimeError, если
    индекс не найден / коллекция не существует."""
    global _chroma_client, _collection
    if _collection is not None:
        return _collection

    path = _resolve_chroma_path()
    if not path.exists():
        raise RuntimeError(f"Chroma not initialized at {path}")

    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=str(path))

    try:
        _collection = _chroma_client.get_collection(COLLECTION_NAME)
    except Exception as e:
        raise RuntimeError(
            f"Chroma collection '{COLLECTION_NAME}' not found at {path}: {e}"
        ) from e
    return _collection


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(timeout=8.0, max_retries=1)
    return _openai_client


def embed_query(query: str) -> list[float]:
    client = _get_openai_client()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=query)
    return resp.data[0].embedding


def _none_if_empty(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    return value


def search(query: str, top_k: int = 5) -> list[SearchHit]:
    collection = get_chroma_collection()
    embedding = embed_query(query)

    res = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    ids = res["ids"][0]
    documents = res["documents"][0]
    metadatas = res["metadatas"][0]
    distances = res["distances"][0]

    hits: list[SearchHit] = []
    for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
        hits.append(
            SearchHit(
                chunk_id=meta.get("chunk_id", chunk_id),
                article_id=int(meta["article_id"]),
                article_url=meta["article_url"],
                title=meta["title"],
                category=meta["category"],
                section=_none_if_empty(meta.get("section")),
                lastmod=_none_if_empty(meta.get("lastmod")),
                chunk_text=doc,
                chunk_index=int(meta["chunk_index"]),
                total_chunks=int(meta["total_chunks"]),
                score=1.0 - float(dist),
            )
        )
    return hits


def warmup() -> Optional[str]:
    """Вызывается на старте FastAPI. Если индекса нет — возвращает строку с
    причиной (для логов и /search 503). Если ОК — возвращает None."""
    try:
        col = get_chroma_collection()
        _ = col.count()
        return None
    except Exception as e:
        msg = f"Chroma not initialized at {_resolve_chroma_path()}: {e}"
        print(msg, file=sys.stderr)
        return msg
