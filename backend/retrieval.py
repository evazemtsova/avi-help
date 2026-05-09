from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.api.models.Collection import Collection
from openai import OpenAI
from pydantic import BaseModel, Field

import bm25 as bm25_module

EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION_NAME = "avi_help"

# Sprint 5 Блок 3: cross-encoder reranker (v2-m3, candidates=20) — добавили,
# дал Recall@5 +7.3 п.п. на eval, но на shared Railway CPU latency P95=24s.
# Sprint 5 Блок 5: попробовали base+10 (3х быстрее) — Recall@5 упал до 0.80
# (ниже Sprint 4 baseline 0.81). Решение: полный откат reranker, top_k=5
# вернулся обратно. Reranker оставлен в коде как roadmap-кандидат для
# dedicated-CPU deploy. См. журнал «Изменение #5».
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
USE_RERANKER = os.getenv("USE_RERANKER", "false").lower() in ("1", "true", "yes")
RERANKER_CANDIDATES = int(os.getenv("RERANKER_CANDIDATES", "20"))

# Sprint 6 Блок 2: BM25 + bi-encoder + RRF (Reciprocal Rank Fusion).
# По умолчанию hybrid включён — делаем default безопасным после ablation
# в Блоке 3. Для bi-encoder-only baseline (ablation `--config bi_only`)
# выставить `USE_HYBRID_RETRIEVAL=false`. Reranker и hybrid взаимно исключают
# друг друга: при USE_RERANKER=true hybrid игнорируется (Sprint 5-путь).
USE_HYBRID_RETRIEVAL = os.getenv("USE_HYBRID_RETRIEVAL", "true").lower() in (
    "1",
    "true",
    "yes",
)
HYBRID_CANDIDATES = int(os.getenv("HYBRID_CANDIDATES", "20"))
RRF_K = int(os.getenv("RRF_K", "60"))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CHROMA_PATH = _PROJECT_ROOT / "data" / "chroma"

_chroma_client: Optional[chromadb.api.ClientAPI] = None
_collection: Optional[Collection] = None
_openai_client: Optional[OpenAI] = None
_reranker = None  # CrossEncoder, lazy-инициализация

# Sprint 5 Block 5: timing breakdown для каждой фазы search() — чтобы увидеть
# где в реальности тратится время на проде (embed / chroma / rerank).
# Sprint 6 Block 2: добавлены bm25_ms / merge_ms для hybrid-пути.
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
    score: float = Field(
        ...,
        description="Legacy ranking score: rrf_score в hybrid режиме, bi_score в bi-only.",
    )
    bi_score: float = Field(
        default=0.0,
        description=(
            "Bi-encoder cosine (1 - distance). Для BM25-only чанков (попавших в "
            "топ через BM25, но не в bi-encoder top-N) = 0.0 — это означает что "
            "bi-encoder не считает чанк релевантным. Используется generation.py "
            "для pre-LLM fallback решения (`max(h.bi_score) < THRESHOLD`)."
        ),
    )
    rrf_score: Optional[float] = Field(
        default=None,
        description="Reciprocal Rank Fusion score (1/(k+rank) суммарно). None в bi-only.",
    )


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


def _build_hit(
    chunk_id: str,
    doc: str,
    meta: dict,
    *,
    bi_score: float,
    score: Optional[float] = None,
    rrf_score: Optional[float] = None,
) -> SearchHit:
    """`score` — legacy ranking score; если не передан, копируется из bi_score
    (bi-only режим). В hybrid выставляется = rrf_score после RRF merge."""
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
        score=bi_score if score is None else score,
        bi_score=bi_score,
        rrf_score=rrf_score,
    )


def _rrf_merge(
    bi_hits: list[SearchHit],
    bm25_pairs: list[tuple[str, float]],
    bm25_only_hits: dict[str, SearchHit],
    k: int,
    top_k: int,
) -> list[SearchHit]:
    """Reciprocal Rank Fusion: суммируем `1/(k+rank)` по обоим ранкерам.

    Для chunk_id, попавших только в один список — учитывается только тот ранкер
    (стандартная RRF-формула). После merge сортируем по rrf_score desc и
    выдаём top_k. `bi_hits` отсортирован по bi-encoder score desc; `bm25_pairs`
    — по BM25 score desc. `bm25_only_hits` — pre-fetched SearchHit'ы (с bi_score=0)
    для chunk_id, которых нет в bi top-N.
    """
    rrf_scores: dict[str, float] = {}
    for rank, h in enumerate(bi_hits, start=1):
        rrf_scores[h.chunk_id] = rrf_scores.get(h.chunk_id, 0.0) + 1.0 / (k + rank)
    for rank, (cid, _bm25_score) in enumerate(bm25_pairs, start=1):
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)

    sorted_ids = sorted(rrf_scores.keys(), key=lambda c: rrf_scores[c], reverse=True)
    bi_by_id = {h.chunk_id: h for h in bi_hits}

    out: list[SearchHit] = []
    for cid in sorted_ids[:top_k]:
        rrf = rrf_scores[cid]
        h = bi_by_id.get(cid) or bm25_only_hits.get(cid)
        if h is None:
            continue
        # В hybrid режиме `score` = rrf_score (legacy field reflects current ranker)
        out.append(
            h.model_copy(update={"rrf_score": rrf, "score": rrf})
        )
    return out


def search(query: str, top_k: int = 5) -> list[SearchHit]:
    """Двухступенчатый retrieval с timing-breakdown в `last_search_timings`.

    Режимы (по env-переменным):
      * USE_RERANKER=true   → bi-encoder top-20 → cross-encoder rerank → top_k.
        Sprint 5-путь, в Sprint 6 не используется (default false).
      * USE_HYBRID_RETRIEVAL=true (default) → bi-encoder top-20 + BM25 top-20 →
        RRF merge → top_k. Sprint 6-путь.
      * Оба false → bi-encoder top_k (Sprint 4 baseline, для ablation `bi_only`).
    """
    import time as _t
    global last_search_timings

    t0 = _t.perf_counter()
    collection = get_chroma_collection()

    t_embed_start = _t.perf_counter()
    embedding = embed_query(query)
    t_embed = (_t.perf_counter() - t_embed_start) * 1000

    reranker = get_reranker()
    bm25_searcher = (
        bm25_module.get_searcher() if (USE_HYBRID_RETRIEVAL and reranker is None) else None
    )

    # Сколько кандидатов тащим из Chroma (bi-encoder top-N).
    if reranker is not None:
        fetch_k = max(top_k, RERANKER_CANDIDATES)
    elif bm25_searcher is not None:
        fetch_k = max(top_k, HYBRID_CANDIDATES)
    else:
        fetch_k = top_k

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

    bi_hits: list[SearchHit] = []
    for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
        bi_score = 1.0 - float(dist)
        bi_hits.append(_build_hit(chunk_id, doc, meta, bi_score=bi_score))

    # === Path 1: reranker on (Sprint 5, opt-in) ===
    if reranker is not None:
        t_rerank_start = _t.perf_counter()
        pairs = [(query, doc) for doc in documents]
        raw_scores = reranker.predict(pairs)
        t_rerank = (_t.perf_counter() - t_rerank_start) * 1000

        import math
        sig_scores = [1.0 / (1.0 + math.exp(-float(s))) for s in raw_scores]
        indexed = sorted(
            range(len(documents)), key=lambda i: sig_scores[i], reverse=True
        )[:top_k]

        last_search_timings = {
            "embed_ms": int(round(t_embed)),
            "chroma_ms": int(round(t_chroma)),
            "rerank_ms": int(round(t_rerank)),
            "bm25_ms": 0,
            "merge_ms": 0,
            "fetch_k": fetch_k,
            "mode": "reranker",
            "total_ms": int(round((_t.perf_counter() - t0) * 1000)),
        }
        # В reranker-режиме score = sigmoid logit (Sprint 5 семантика);
        # bi_score из изначальной cosine, rrf_score=None.
        return [
            bi_hits[i].model_copy(update={"score": sig_scores[i]}) for i in indexed
        ]

    # === Path 2: hybrid (Sprint 6, default) ===
    if bm25_searcher is not None:
        t_bm25_start = _t.perf_counter()
        bm25_pairs = bm25_searcher.search(query, top_k=HYBRID_CANDIDATES)
        t_bm25 = (_t.perf_counter() - t_bm25_start) * 1000

        t_merge_start = _t.perf_counter()
        bi_chunk_ids = {h.chunk_id for h in bi_hits}
        bm25_only_ids = [cid for cid, _ in bm25_pairs if cid not in bi_chunk_ids]

        bm25_only_hits: dict[str, SearchHit] = {}
        if bm25_only_ids:
            extra = collection.get(
                ids=bm25_only_ids, include=["documents", "metadatas"]
            )
            for cid, doc, meta in zip(
                extra["ids"], extra["documents"], extra["metadatas"]
            ):
                bm25_only_hits[cid] = _build_hit(cid, doc, meta, bi_score=0.0)

        merged = _rrf_merge(
            bi_hits=bi_hits[:HYBRID_CANDIDATES],
            bm25_pairs=bm25_pairs,
            bm25_only_hits=bm25_only_hits,
            k=RRF_K,
            top_k=top_k,
        )
        t_merge = (_t.perf_counter() - t_merge_start) * 1000

        last_search_timings = {
            "embed_ms": int(round(t_embed)),
            "chroma_ms": int(round(t_chroma)),
            "rerank_ms": 0,
            "bm25_ms": int(round(t_bm25)),
            "merge_ms": int(round(t_merge)),
            "fetch_k": fetch_k,
            "mode": "hybrid",
            "total_ms": int(round((_t.perf_counter() - t0) * 1000)),
        }
        return merged

    # === Path 3: bi-only (ablation `bi_only`, Sprint 4 baseline) ===
    last_search_timings = {
        "embed_ms": int(round(t_embed)),
        "chroma_ms": int(round(t_chroma)),
        "rerank_ms": 0,
        "bm25_ms": 0,
        "merge_ms": 0,
        "fetch_k": fetch_k,
        "mode": "bi_only",
        "total_ms": int(round((_t.perf_counter() - t0) * 1000)),
    }
    return bi_hits[:top_k]


def warmup() -> Optional[str]:
    """Вызывается на старте FastAPI. Прогружает индекс + reranker (если включён).
    Если индекса нет — возвращает строку с причиной. Если reranker не загрузился —
    логирует и продолжает (graceful degradation). BM25 инициализация — отдельно
    в `main._startup` через `bm25.init_from_chroma`."""
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
