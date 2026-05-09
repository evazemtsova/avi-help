"""BM25 retrieval — Sprint 6 hybrid retrieval (Блок 1).

Tokenizer: lowercase + split по non-word (Юникод) + filter длины ≥ 2.
Без стемминга, стоп-слов, лемматизации — минимальный baseline (бриф Sprint 6
явно требует не делать в первой итерации, чтобы изолировать эффект BM25).

Источник истины для chunk_text — Chroma collection (та же коллекция, что
обслуживает bi-encoder retrieval). Index — in-memory; на старте FastAPI
пересобирается из Chroma за ~1-2 сек на 4288 чанков (вариант A из брифа).

Persistence через pickle — для дебага/воспроизводимости (например, для
повторного запуска `scripts/bm25_probe.py` без построения с нуля).
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Optional

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[\W_]+", flags=re.UNICODE)
_MIN_TOKEN_LEN = 2


def tokenize_ru(text: str) -> list[str]:
    """lowercase + non-word split + длина ≥ 2.

    Та же логика что в `scripts/bm25_probe.py` (доказанная на 5 cherry-picked):
    `[\\W_]+` режет по любому символу не-буква/цифра, юникод-флаг работает с
    кириллицей. Фильтр `len >= 2` убирает одиночные «и»/«в»/«с» — они дают
    шум при очень коротких запросах.
    """
    return [t for t in _TOKEN_RE.split(text.lower()) if len(t) >= _MIN_TOKEN_LEN]


class BM25Searcher:
    """Wraps BM25Okapi с stable chunk_id-маппингом.

    Порядок chunk_ids фиксирован при инициализации; ranks из `search()` —
    1-indexed позиции в результате. Ничего не знает про Chroma и article_url —
    выдаёт только chunk_id и BM25 score, маппинг на полный SearchHit делается
    выше по стеку (в `retrieval.search()` через RRF, Блок 2).
    """

    def __init__(self, bm25: BM25Okapi, chunk_ids: list[str]) -> None:
        self._bm25 = bm25
        self._chunk_ids = list(chunk_ids)

    @classmethod
    def from_documents(
        cls, chunk_ids: list[str], documents: list[str]
    ) -> "BM25Searcher":
        if len(chunk_ids) != len(documents):
            raise ValueError(
                f"len mismatch: {len(chunk_ids)} ids vs {len(documents)} docs"
            )
        tokenized = [tokenize_ru(d) for d in documents]
        return cls(BM25Okapi(tokenized), list(chunk_ids))

    @classmethod
    def from_chroma(cls, collection) -> "BM25Searcher":
        """Достаёт документы и chunk_id-метаданные из Chroma, строит индекс.

        Корпус для BM25: `meta['title'] + '\\n' + document`. Title явно
        prepend'ится перед document — это **mirror** поведения probe
        (`scripts/bm25_probe.py`), который верифицирован на 4/5 cherry-picked.
        Document в Chroma уже начинается с title (см. `data/articles.jsonl`),
        поэтому prepend даёт **двойной title** — лёгкий upweighting заголовков
        в BM25 score, что эмпирически помогает на запросах, лексически
        совпадающих с заголовками статей.

        Порядок: как Chroma вернёт через `get()`. chunk_id из метаданных —
        ground-truth идентификатор; маппинг RRF в Блоке 2 идёт по chunk_id.
        """
        res = collection.get(include=["documents", "metadatas"])
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        chunk_ids: list[str] = []
        indexed_texts: list[str] = []
        for i, (meta, doc) in enumerate(zip(metas, docs)):
            meta = meta or {}
            cid = meta.get("chunk_id") or (ids[i] if i < len(ids) else None)
            if cid is None:
                raise ValueError(f"chunk_id missing for doc index {i}")
            chunk_ids.append(str(cid))
            title = meta.get("title") or ""
            indexed_texts.append(f"{title}\n{doc}" if title else doc)
        return cls.from_documents(chunk_ids, indexed_texts)

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        """Возвращает [(chunk_id, bm25_score), ...] sorted desc, top_k.

        Позиция в списке = rank (1-indexed) — используется RRF в Блоке 2.
        Если query после токенизации пуст (например, чистая пунктуация) —
        возвращает пустой список (BM25Okapi на пустом query даёт NaN).
        """
        q_tokens = tokenize_ru(query)
        if not q_tokens:
            return []
        scores = self._bm25.get_scores(q_tokens)
        top_idx = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:top_k]
        return [(self._chunk_ids[i], float(scores[i])) for i in top_idx]

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(
                {"bm25": self._bm25, "chunk_ids": self._chunk_ids, "version": 1},
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    @classmethod
    def load(cls, path: Path | str) -> "BM25Searcher":
        with Path(path).open("rb") as f:
            obj = pickle.load(f)
        return cls(obj["bm25"], obj["chunk_ids"])

    @property
    def size(self) -> int:
        return len(self._chunk_ids)


# === Module-level singleton (used by FastAPI lifespan in main.py) ===

_searcher: Optional[BM25Searcher] = None


def init_from_chroma(collection) -> BM25Searcher:
    """Строит singleton BM25Searcher из Chroma. Вызывается в lifespan event."""
    global _searcher
    _searcher = BM25Searcher.from_chroma(collection)
    return _searcher


def get_searcher() -> Optional[BM25Searcher]:
    return _searcher
