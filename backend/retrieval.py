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

# Sprint 5 Блок 3: cross-encoder reranker.
# Sprint 5 Блок 5: production reality check — v2-m3 на shared Railway CPU дал
# P95=24s (PRD ≤8s). Перешли на base + 10 кандидатов (см. журнал, Изменение #5).
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
USE_RERANKER = os.getenv("USE_RERANKER", "true").lower() in ("1", "true", "yes")
RERANKER_CANDIDATES = int(os.getenv("RERANKER_CANDIDATES", "10"))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CHROMA_PATH = _PROJECT_ROOT / "data" / "chroma"

_chroma_client: Optional[chromadb.api.ClientAPI] = None
_collection: Optional[Collection] = None
_openai_client: Optional[OpenAI] = None
_reranker = None  # CrossEncoder, lazy-инициализация

# Sprint 5 Block 5: timing breakdown для каждой фазы search() — чтобы увидеть
# где в реальности тратится время на проде (embed / chroma / rerank).
last_search_timings: dict = {}


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


def get_reranker():
    """Lazy-инициализация CrossEncoder. Возвращает None если USE_RERANKER=false
    или модель не загрузилась (graceful degradation: fall-back на bi-encoder)."""
    global _reranker
    if not USE_RERANKER:
        return None
    if _reranker is not None:
        return _reranker
    try:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
        print(f"[retrieval] reranker loaded: {RERANKER_MODEL}", file=sys.stderr)
    except Exception as e:
        print(f"[retrieval] reranker FAILED to load ({e!r}) — falling back "
              f"to bi-encoder only", file=sys.stderr)
        _reranker = None
    return _reranker


def _build_hit(chunk_id: str, doc: str, meta: dict, score: float) -> SearchHit:
    return SearchHit(
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
        score=score,
    )


def search(query: str, top_k: int = 5) -> list[SearchHit]:
    """Двухступенчатый retrieval с timing-breakdown в `last_search_timings`."""
    import time as _t
    global last_search_timings

    t0 = _t.perf_counter()
    collection = get_chroma_collection()

    t_embed_start = _t.perf_counter()
    embedding = embed_query(query)
    t_embed = (_t.perf_counter() - t_embed_start) * 1000

    reranker = get_reranker()
    fetch_k = max(top_k, RERANKER_CANDIDATES) if reranker is not None else top_k

    t_chroma_start = _t.perf_counter()
    res = collection.query(
        query_embeddings=[embedding],
        n_results=fetch_k,
        include=["documents", "metadatas", "distances"],
    )
    t_chroma = (_t.perf_counter() - t_chroma_start) * 1000

    ids = res["ids"][0]
    documents = res["documents"][0]
    metadatas = res["metadatas"][0]
    distances = res["distances"][0]

    if reranker is None:
        last_search_timings = {
            "embed_ms": int(round(t_embed)),
            "chroma_ms": int(round(t_chroma)),
            "rerank_ms": 0,
            "fetch_k": fetch_k,
            "reranker": False,
            "total_ms": int(round((_t.perf_counter() - t0) * 1000)),
        }
        hits: list[SearchHit] = []
        for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
            hits.append(_build_hit(chunk_id, doc, meta, 1.0 - float(dist)))
        return hits

    t_rerank_start = _t.perf_counter()
    pairs = [(query, doc) for doc in documents]
    raw_scores = reranker.predict(pairs)
    t_rerank = (_t.perf_counter() - t_rerank_start) * 1000

    import math
    sig_scores = [1.0 / (1.0 + math.exp(-float(s))) for s in raw_scores]

    indexed = sorted(
        range(len(documents)),
        key=lambda i: sig_scores[i],
        reverse=True,
    )[:top_k]

    last_search_timings = {
        "embed_ms": int(round(t_embed)),
        "chroma_ms": int(round(t_chroma)),
        "rerank_ms": int(round(t_rerank)),
        "fetch_k": fetch_k,
        "reranker": True,
        "total_ms": int(round((_t.perf_counter() - t0) * 1000)),
    }

    return [
        _build_hit(ids[i], documents[i], metadatas[i], sig_scores[i])
        for i in indexed
    ]


def warmup() -> Optional[str]:
    """Вызывается на старте FastAPI. Прогружает индекс + reranker (если включён).
    Если индекса нет — возвращает строку с причиной. Если reranker не загрузился —
    логирует и продолжает (graceful degradation)."""
    try:
        col = get_chroma_collection()
        _ = col.count()
    except Exception as e:
        msg = f"Chroma not initialized at {_resolve_chroma_path()}: {e}"
        print(msg, file=sys.stderr)
        return msg
    # Reranker — best effort, не блокирует health-check
    if USE_RERANKER:
        get_reranker()
    return None
