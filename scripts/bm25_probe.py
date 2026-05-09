"""BM25 probe — диагностика для roadmap, НЕ продакшн-интеграция.

Цель: на 5 cherry-picked failure cases (g002, g020, g050, g061, g023)
прикинуть стоит ли BM25/hybrid retrieval тащить в Sprint 6+.

Что делает:
  1. Строит BM25Okapi index по 4288 чанкам из data/articles.jsonl
  2. Берёт bi-encoder top-10 из последнего mvp run
     (data/eval/runs/mvp_20260509_153514/results.jsonl)
     — НИКАКИХ новых embedding-запросов
  3. Считает RRF-fusion (Reciprocal Rank Fusion, k=60) → top-5 hybrid
  4. Печатает таблицу: ранк expected URL'а в BM25 vs bi-encoder vs hybrid

Запуск из корня репо:
  backend/.venv/bin/python scripts/bm25_probe.py

НЕ запускает eval, НЕ дёргает Anthropic/OpenAI, НЕ меняет retrieval.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi


REPO_ROOT = Path(__file__).resolve().parent.parent
ARTICLES = REPO_ROOT / "data" / "articles.jsonl"
GOLDEN = REPO_ROOT / "data" / "eval" / "golden_set.jsonl"
LATEST_RUN = REPO_ROOT / "data" / "eval" / "runs" / "mvp_20260509_153514" / "results.jsonl"

PROBE_IDS = ["g002", "g020", "g050", "g061", "g023"]
RRF_K = 60
TOP_N_FOR_RANKING = 20  # «not in top-20» если ранк выше


# ---------- tokenizer ----------

_TOKEN_RE = re.compile(r"[\W_]+", flags=re.UNICODE)


def tokenize(text: str) -> list[str]:
    """lowercase + split по non-word (юникод) — без стемминга, без стоп-слов."""
    return [t for t in _TOKEN_RE.split(text.lower()) if t]


# ---------- load ----------

def load_chunks() -> list[dict]:
    chunks = []
    with ARTICLES.open(encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


def load_golden_subset(ids: list[str]) -> dict[str, dict]:
    want = set(ids)
    out = {}
    with GOLDEN.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["id"] in want:
                out[d["id"]] = d
    return out


def load_bi_encoder_top10(ids: list[str]) -> dict[str, list[dict]]:
    want = set(ids)
    out = {}
    with LATEST_RUN.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("id") in want:
                out[d["id"]] = d.get("retrieval_top_10") or []
    return out


# ---------- ranking helpers ----------

def find_rank(article_urls_in_top: list[str], expected_urls: list[str]) -> int | None:
    """Возвращает 1-based позицию первого expected URL в top-list, или None."""
    expected_set = set(expected_urls)
    for i, url in enumerate(article_urls_in_top, start=1):
        if url in expected_set:
            return i
    return None


def fmt_rank(r: int | None, top_n: int = TOP_N_FOR_RANKING) -> str:
    if r is None:
        return f"not in top-{top_n}"
    return f"#{r}"


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K, top_n: int = 5) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: each ranker contributes 1/(k+rank) per chunk_id."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    sorted_ids = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_ids[:top_n]


# ---------- main ----------

def main() -> None:
    print(f"Loading {ARTICLES.name}...")
    chunks = load_chunks()
    print(f"  {len(chunks)} chunks loaded")

    print("Tokenizing + building BM25Okapi index...")
    # В индекс кладём title + chunk_text — чтобы matched terms из заголовка работали
    corpus_tokens = [tokenize(f"{c['title']}\n{c['chunk_text']}") for c in chunks]
    bm25 = BM25Okapi(corpus_tokens)
    print(f"  index built: vocab~{len(bm25.idf)} terms, avgdl={bm25.avgdl:.1f}")

    chunk_id_by_idx = {i: c["chunk_id"] for i, c in enumerate(chunks)}
    chunk_by_id = {c["chunk_id"]: c for c in chunks}

    golden = load_golden_subset(PROBE_IDS)
    bi_top10_by_id = load_bi_encoder_top10(PROBE_IDS)

    print()
    print("=" * 110)
    print(f"{'id':5} | {'BM25 rank':<14} | {'bi-enc rank':<14} | {'hybrid (RRF k=60) top-5 URLs':<60}")
    print("=" * 110)

    summary_rows = []

    for qid in PROBE_IDS:
        gold = golden[qid]
        query = gold["query"]
        expected = gold["expected_article_urls"]

        # --- BM25 top-N ---
        q_tokens = tokenize(query)
        bm25_scores = bm25.get_scores(q_tokens)
        bm25_top_idx = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:TOP_N_FOR_RANKING]
        bm25_top_urls = [chunk_by_id[chunk_id_by_idx[i]]["article_url"] for i in bm25_top_idx]
        bm25_top_chunk_ids = [chunk_id_by_idx[i] for i in bm25_top_idx]

        # --- Bi-encoder top-10 (из cache) ---
        bi_top10 = bi_top10_by_id.get(qid, [])
        bi_top_urls = [h["article_url"] for h in bi_top10]
        bi_top_chunk_ids = [h["chunk_id"] for h in bi_top10]

        # --- Hybrid RRF (BM25 top-20 + bi-encoder top-10) ---
        rrf = rrf_fuse([bm25_top_chunk_ids, bi_top_chunk_ids], k=RRF_K, top_n=5)
        rrf_chunk_ids = [cid for cid, _ in rrf]
        rrf_urls = [chunk_by_id[cid]["article_url"] for cid in rrf_chunk_ids]

        bm25_rank = find_rank(bm25_top_urls, expected)
        bi_rank = find_rank(bi_top_urls, expected)
        hybrid_rank = find_rank(rrf_urls, expected)

        # дедуплицируем article_url в hybrid top-5 для наглядности
        seen = set()
        rrf_unique = []
        for u in rrf_urls:
            if u not in seen:
                rrf_unique.append(u)
                seen.add(u)
        rrf_str = " ".join(u.replace("https://support.avito.ru/articles/", "") for u in rrf_unique)

        print(f"{qid:5} | {fmt_rank(bm25_rank):<14} | {fmt_rank(bi_rank, 10):<14} | {rrf_str:<60}")
        summary_rows.append((qid, query, expected, bm25_rank, bi_rank, hybrid_rank, rrf_unique))

    print("=" * 110)
    print()

    # ---------- detailed per-case table ----------
    print("\nDetailed per-case (expected URL → ID; * = expected; rank in TOP-N):")
    print()
    for qid, query, expected, bm25_r, bi_r, hyb_r, hyb_urls in summary_rows:
        exp_ids = ", ".join(u.replace("https://support.avito.ru/articles/", "") for u in expected)
        print(f"  [{qid}] q={query[:70]}")
        print(f"        expected={exp_ids}")
        print(f"        BM25 rank={fmt_rank(bm25_r)} | bi-enc rank={fmt_rank(bi_r, 10)} | hybrid top-5 rank={fmt_rank(hyb_r, 5)}")
        print()

    # ---------- summary ----------
    n = len(summary_rows)
    bm25_in_top5 = sum(1 for r in summary_rows if r[3] is not None and r[3] <= 5)
    bm25_in_top10 = sum(1 for r in summary_rows if r[3] is not None and r[3] <= 10)
    bi_in_top5 = sum(1 for r in summary_rows if r[4] is not None and r[4] <= 5)
    bi_in_top10 = sum(1 for r in summary_rows if r[4] is not None and r[4] <= 10)
    hybrid_in_top5 = sum(1 for r in summary_rows if r[5] is not None and r[5] <= 5)

    print("=" * 110)
    print("SUMMARY (count expected URL in top-K):")
    print(f"  bi-encoder    top-5:  {bi_in_top5}/{n}     top-10: {bi_in_top10}/{n}")
    print(f"  BM25          top-5:  {bm25_in_top5}/{n}     top-10: {bm25_in_top10}/{n}")
    print(f"  hybrid (RRF)  top-5:  {hybrid_in_top5}/{n}")
    print("=" * 110)


if __name__ == "__main__":
    main()
