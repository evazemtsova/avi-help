"""Build BM25 index from Chroma → save to data/bm25_index.pkl.

Используется для:
  - Воспроизводимости (можно собрать локально и закинуть в `bm25_probe.py`).
  - Дебага токенизации (если sanity-search не находит ожидаемый chunk).

В проде индекс пересобирается на старте FastAPI в lifespan event
(см. `backend/main.py` -> `_startup`), поэтому файл `data/bm25_index.pkl`
не обязателен к деплою и в `.gitignore`.

Запуск из корня репо:
    backend/.venv/bin/python scripts/build_bm25_index.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

import json  # noqa: E402

from bm25 import BM25Searcher  # noqa: E402
from retrieval import get_chroma_collection  # noqa: E402

OUT_PATH = REPO / "data" / "bm25_index.pkl"
GOLDEN_PATH = REPO / "data" / "eval" / "golden_set.jsonl"

# Полный golden-запрос g020 — на нём probe верифицировал BM25 #1 (см. журнал
# Sprint 5 → BM25 probe). Бриф упоминал короткий «телефон со сколом», но в
# нём нет лексических матчей с чанками 2831 (там нет «телефон» / «сколом») —
# короткий вариант на полном корпусе даёт зашумлённый top-10. Используем
# полный golden-запрос как воспроизводимый sanity.
SANITY_QUERY_ID = "g020"
SANITY_EXPECT_ARTICLE_ID = 2831  # «Приехал повреждённый товар» — 8 чанков
SANITY_TOP_K = 10
SANITY_REQUIRE_IN_TOP = 3  # бриф Блока 1: 2831 в top-3


def _chunk_id_matches_article(chunk_id: str, article_id: int) -> bool:
    """chunk_id формат: '{article_id}_{NNN}' — см. articles.jsonl."""
    return chunk_id.startswith(f"{article_id}_")


def main() -> int:
    print(f"[build_bm25] reading Chroma from default path…")
    t0 = time.perf_counter()
    col = get_chroma_collection()
    n_chunks = col.count()
    print(f"[build_bm25] chroma collection has {n_chunks} chunks")

    searcher = BM25Searcher.from_chroma(col)
    print(
        f"[build_bm25] BM25 built over {searcher.size} chunks in "
        f"{(time.perf_counter() - t0) * 1000:.0f}ms"
    )

    # --- sanity-search ---
    sanity_query = None
    with GOLDEN_PATH.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("id") == SANITY_QUERY_ID:
                sanity_query = d["query"]
                break
    if sanity_query is None:
        print(f"❌ Could not load query {SANITY_QUERY_ID} from {GOLDEN_PATH}")
        return 1
    results = searcher.search(sanity_query, top_k=SANITY_TOP_K)
    print(f"\n[sanity] {SANITY_QUERY_ID}: query={sanity_query!r}")
    matched_position: int | None = None
    for i, (cid, score) in enumerate(results, start=1):
        flag = ""
        if _chunk_id_matches_article(cid, SANITY_EXPECT_ARTICLE_ID):
            flag = " ← expected"
            if matched_position is None:
                matched_position = i
        print(f"  #{i:2}  {cid:>12}  score={score:.3f}{flag}")

    if matched_position is None:
        print(
            f"\n❌ Sanity-check FAILED: article {SANITY_EXPECT_ARTICLE_ID} "
            f"not in BM25 top-{SANITY_TOP_K} for {SANITY_QUERY!r}"
        )
        return 1
    if matched_position > SANITY_REQUIRE_IN_TOP:
        print(
            f"\n❌ Sanity-check FAILED: article {SANITY_EXPECT_ARTICLE_ID} "
            f"at rank #{matched_position}, expected within top-{SANITY_REQUIRE_IN_TOP}"
        )
        return 1
    print(
        f"\n✓ Sanity OK: article {SANITY_EXPECT_ARTICLE_ID} at rank "
        f"#{matched_position} (require ≤ #{SANITY_REQUIRE_IN_TOP})"
    )

    # --- save ---
    searcher.save(OUT_PATH)
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"\n[build_bm25] saved → {OUT_PATH.relative_to(REPO)} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
