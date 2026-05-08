"""Sprint 4 eval — retrieval + generation на golden + ood.

Запуск из корня репо:
    backend/.venv/bin/python scripts/eval.py --config mvp [--limit 5] [--ood] [--no-cache]

Кэширует Anthropic-вызовы в data/llm_cache.jsonl и OpenAI embeddings в
data/embedding_cache.jsonl. Повторный прогон того же конфига = бесплатно.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

# Подтягиваем .env (ANTHROPIC_API_KEY, OPENAI_API_KEY) из backend/.env
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / "backend" / ".env")

from anthropic import Anthropic  # noqa: E402

import generation  # noqa: E402
import retrieval  # noqa: E402
from llm_cache import (  # noqa: E402
    CachedAnthropic,
    DEFAULT_CACHE_PATH,
    DEFAULT_EMB_CACHE_PATH,
    embedding_get,
    embedding_put,
    load_cache,
    load_embedding_cache,
    stats as cache_stats,
)

# Pricing (input/output per 1M tokens). Включает versioned id-шники Anthropic.
PRICING = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (5.0, 25.0),
}

JUDGE_MODEL = "claude-sonnet-4-6"

# Чанки в результаты пишем урезанными — судье и человеку этого хватает,
# а файл не раздувается. Чанки в среднем ~1000 символов.
CHUNK_TEXT_MAX_CHARS = 2000

FAITHFULNESS_TOOL = {
    "name": "score_faithfulness",
    "description": "Оцени, опирается ли каждое утверждение в ответе на чанки справки.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_faithful": {
                "type": "boolean",
                "description": "true если все фактические утверждения в ответе подкреплены приложенными чанками. Если в ответе нет фактических утверждений (например, fallback) — также true.",
            },
            "unsupported_claims": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Список фактических утверждений из ответа, которых нет в чанках. Пустой массив, если is_faithful=true.",
            },
        },
        "required": ["is_faithful", "unsupported_claims"],
    },
}

RELEVANCE_TOOL = {
    "name": "score_relevance",
    "description": "Оцени релевантность ответа исходному вопросу пользователя.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "1 — не отвечает, 2 — мимо, 3 — частично, 4 — в основном, 5 — полный точный ответ.",
            },
            "reasoning": {
                "type": "string",
                "description": "Краткое обоснование (1 предложение).",
            },
        },
        "required": ["score", "reasoning"],
    },
}

FAITHFULNESS_SYSTEM = """Ты — эксперт-оценщик ответов RAG-системы по справке Авито.

Задача: проверить, что каждое фактическое утверждение в ответе системы подкреплено приложенными чанками из справки.

Считаются фактическими утверждениями:
- конкретные действия пользователя (нажмите X, перейдите в Y);
- сроки и условия (в течение 7 дней, если прошло больше 24 часов);
- названия фич, кнопок, разделов, статусов;
- числа, лимиты, проценты;
- условия применимости (только для PRO, доступно в категориях X, Y).

Не считаются утверждениями (не проверяем):
- общие фразы вежливости (обратитесь в поддержку);
- отказ ответить (по этому запросу нет информации, попробуйте сформулировать иначе).

Если в ответе нет фактических утверждений (например, fallback-ответ) — is_faithful=true, unsupported_claims=[].

Если хотя бы одно утверждение НЕ найдено в чанках (даже частично/перефразированно) — is_faithful=false, перечисли его в unsupported_claims короткой фразой."""

RELEVANCE_SYSTEM = """Ты — эксперт-оценщик ответов RAG-системы по справке Авито.

Задача: оценить релевантность ответа исходному вопросу пользователя по шкале 1-5.

Шкала:
1 — Совсем не отвечает (отказ или совершенно мимо).
2 — Адресует тему, но не отвечает на конкретный запрос.
3 — Частично отвечает, упускает важные аспекты.
4 — Отвечает в основном, минорные пробелы.
5 — Полный точный ответ на заданный вопрос.

Не оцениваешь правдивость или подкреплённость источниками — только насколько ответ полезен пользователю."""


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    """Считает стоимость по префиксу модели (Anthropic возвращает c date suffix)."""
    rate = None
    if model in PRICING:
        rate = PRICING[model]
    else:
        for prefix, r in PRICING.items():
            if model.startswith(prefix):
                rate = r
                break
    if rate is None:
        return 0.0
    in_per_m, out_per_m = rate
    return input_tokens * in_per_m / 1e6 + output_tokens * out_per_m / 1e6


def load_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def install_caches(use_cache: bool) -> None:
    real_anthropic = Anthropic(timeout=30.0, max_retries=1)
    if use_cache:
        load_cache(DEFAULT_CACHE_PATH)
        load_embedding_cache(DEFAULT_EMB_CACHE_PATH)
        # Anthropic — через wrapper
        generation._anthropic_client = CachedAnthropic(real_anthropic)
        # OpenAI embed — патчим retrieval.embed_query
        _orig_embed = retrieval.embed_query

        def cached_embed(text: str) -> list[float]:
            cached = embedding_get(retrieval.EMBEDDING_MODEL, text)
            if cached is not None:
                return cached
            vec = _orig_embed(text)
            embedding_put(retrieval.EMBEDDING_MODEL, text, vec)
            return vec

        retrieval.embed_query = cached_embed
    else:
        generation._anthropic_client = real_anthropic


def apply_config(config: str) -> None:
    if config == "mvp":
        return
    if config == "baseline":
        # Отключаем safety-priming для ablation
        generation._needs_safety_priming = lambda hits: False
        return
    raise SystemExit(f"unknown config: {config}")


def hit_to_dict(h) -> dict:
    text = h.chunk_text or ""
    if len(text) > CHUNK_TEXT_MAX_CHARS:
        text = text[:CHUNK_TEXT_MAX_CHARS] + "…"
    return {
        "chunk_id": h.chunk_id,
        "article_id": h.article_id,
        "article_url": h.article_url,
        "title": h.title,
        "category": h.category,
        "score": round(h.score, 4),
        "chunk_text": text,
    }


# === LLM-judge (Sonnet) ===

def _build_chunks_for_judge(hits) -> str:
    """Топ-5 чанков, в одном текстовом блоке для подачи в judge."""
    parts = []
    for i, h in enumerate(hits[:5], start=1):
        parts.append(
            f"[Чанк {i}, chunk_id={h.chunk_id}, статья: {h.title}, категория: {h.category}]\n"
            f"{h.chunk_text}"
        )
    return "\n\n---\n\n".join(parts)


def _build_answer_text(result) -> str:
    out = result.lead or ""
    for s in result.sections:
        out += f"\n\n[Раздел «{s.title}»]\n{s.body}"
    return out


def _extract_tool_input(resp):
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    return None


def judge_faithfulness(client, query: str, result, hits) -> dict:
    msg = (
        f"ВОПРОС: {query}\n\n"
        f"ОТВЕТ СИСТЕМЫ:\n{_build_answer_text(result)}\n\n"
        f"ЧАНКИ ИЗ СПРАВКИ (которые видела модель):\n{_build_chunks_for_judge(hits)}"
    )
    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=512,
        temperature=0,
        system=FAITHFULNESS_SYSTEM,
        tools=[FAITHFULNESS_TOOL],
        tool_choice={"type": "tool", "name": "score_faithfulness"},
        messages=[{"role": "user", "content": msg}],
    )
    ti = _extract_tool_input(resp) or {}
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return {
        "is_faithful": bool(ti.get("is_faithful", False)),
        "unsupported_claims": list(ti.get("unsupported_claims") or []),
        "model": resp.model,
        "usage": usage,
    }


def judge_relevance(client, query: str, result) -> dict:
    msg = (
        f"ВОПРОС: {query}\n\n"
        f"ОТВЕТ СИСТЕМЫ:\n{_build_answer_text(result)}"
    )
    resp = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        system=RELEVANCE_SYSTEM,
        tools=[RELEVANCE_TOOL],
        tool_choice={"type": "tool", "name": "score_relevance"},
        messages=[{"role": "user", "content": msg}],
    )
    ti = _extract_tool_input(resp) or {}
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    score = ti.get("score")
    if not isinstance(score, int) or score < 1 or score > 5:
        score = None
    return {
        "score": score,
        "reasoning": str(ti.get("reasoning", "")),
        "model": resp.model,
        "usage": usage,
    }


def _judge_pair(client, query: str, result, hits) -> dict:
    """Зовём faithfulness + relevance, возвращаем judge-блок с метриками и стоимостью."""
    s0 = cache_stats()
    t0 = time.perf_counter()
    j_faith = judge_faithfulness(client, query, result, hits)
    j_rel = judge_relevance(client, query, result)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    s1 = cache_stats()

    # Cache-hits для каждого из двух judge-вызовов (faith первый, rel второй).
    new_hits = s1["hits"] - s0["hits"]
    new_misses = s1["misses"] - s0["misses"]
    # Если все 2 hit — paid=0; если 1 miss — paid за этот один; если 2 miss — за оба.
    faith_cost_rate = cost_for(j_faith["model"], j_faith["usage"]["input_tokens"],
                               j_faith["usage"]["output_tokens"])
    rel_cost_rate = cost_for(j_rel["model"], j_rel["usage"]["input_tokens"],
                             j_rel["usage"]["output_tokens"])
    cost_rate_total = faith_cost_rate + rel_cost_rate
    # Грубая оценка: если оба hit — paid=0; иначе — пропорционально miss-долe.
    if new_misses == 0:
        cost_paid_total = 0.0
    elif new_misses == 2:
        cost_paid_total = cost_rate_total
    else:
        # 1 miss из 2. Не знаем какой. Платим средне.
        cost_paid_total = cost_rate_total / 2.0

    return {
        "faithfulness": j_faith,
        "relevance": j_rel,
        "cost_usd_rate": round(cost_rate_total, 8),
        "cost_usd_paid": round(cost_paid_total, 8),
        "elapsed_ms": round(elapsed_ms, 1),
    }


def run_one(item: dict, is_ood: bool, judge_client=None) -> dict:
    query = item["query"]
    t_total = time.perf_counter()

    # Снимаем счётчики до вызова, чтобы потом понять, был ли реально cache-hit
    # (а значит — реальная стоимость = 0).
    s0 = cache_stats()

    t_ret = time.perf_counter()
    hits = retrieval.search(query, top_k=10)
    t_ret_ms = (time.perf_counter() - t_ret) * 1000

    t_gen = time.perf_counter()
    result = generation.generate(query, hits[:5])
    t_gen_ms = (time.perf_counter() - t_gen) * 1000

    s1 = cache_stats()
    anthropic_hit = s1["hits"] > s0["hits"]
    embedding_hit = s1["emb_hits"] > s0["emb_hits"]

    usage = result.usage
    cost_rate = cost_for(result.model, usage.get("input_tokens", 0),
                         usage.get("output_tokens", 0))
    cost_paid = 0.0 if anthropic_hit else cost_rate

    # Judge только для in-domain (для OOD считаем только refusal_rate отдельно).
    judge_block = None
    if not is_ood and judge_client is not None:
        judge_block = _judge_pair(judge_client, query, result, hits)

    total_ms = (time.perf_counter() - t_total) * 1000

    rec = {
        "id": item["id"],
        "query": query,
        "is_ood": is_ood,
        "category": item.get("category"),
        "difficulty": item.get("difficulty"),
        "notes": item.get("notes", ""),
        "expected_article_urls": item.get("expected_article_urls", []),
        "genre": item.get("genre"),
        "retrieval_top_10": [hit_to_dict(h) for h in hits],
        "answer": {
            "lead": result.lead,
            "sections": [s.model_dump() for s in result.sections],
            "sources_used": result.sources_used,
            "sources": [s.model_dump() for s in result.sources],
            "is_fallback": result.is_fallback,
        },
        "model": result.model,
        "usage": usage,
        "cost_usd": round(cost_paid, 8),
        "cost_usd_rate": round(cost_rate, 8),
        "cache_hit": {"anthropic": anthropic_hit, "embedding": embedding_hit},
        "latency_ms": {
            "retrieval": round(t_ret_ms, 1),
            "generation": round(t_gen_ms, 1),
            "total": round(total_ms, 1),
        },
    }
    if judge_block is not None:
        rec["judge"] = judge_block
    return rec


def compute_retrieval_metrics(results: list[dict]) -> dict:
    """Recall@5 и MRR@10 по in-domain (content-gap c пустым expected — исключаем)."""
    # Records с error не имеют retrieval_top_10 — отдельно считаем и пропускаем.
    failed = [r for r in results if "retrieval_top_10" not in r]
    in_domain = [r for r in results
                 if not r.get("is_ood") and "retrieval_top_10" in r]
    countable = [r for r in in_domain if r.get("expected_article_urls")]
    content_gap = [r for r in in_domain if not r.get("expected_article_urls")]

    by_cat: dict[str, list[tuple[int, float]]] = defaultdict(list)
    by_diff: dict[str, list[tuple[int, float]]] = defaultdict(list)
    worst: list[dict] = []
    recalls: list[int] = []
    mrrs: list[float] = []

    for r in countable:
        urls_top5 = [h["article_url"] for h in r["retrieval_top_10"][:5]]
        urls_top10 = [h["article_url"] for h in r["retrieval_top_10"]]
        expected = set(r["expected_article_urls"])

        recall = 1 if any(u in expected for u in urls_top5) else 0
        mrr = 0.0
        for i, u in enumerate(urls_top10, start=1):
            if u in expected:
                mrr = 1.0 / i
                break

        recalls.append(recall)
        mrrs.append(mrr)
        by_cat[r["category"]].append((recall, mrr))
        by_diff[r["difficulty"]].append((recall, mrr))

        if recall == 0:
            worst.append({
                "id": r["id"],
                "query": r["query"],
                "category": r["category"],
                "difficulty": r["difficulty"],
                "expected_urls": list(expected),
                "found_top5": [
                    {"url": h["article_url"], "title": h["title"], "score": h["score"]}
                    for h in r["retrieval_top_10"][:5]
                ],
                "mrr": round(mrr, 4),
            })

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    def block(items):
        rs = [x[0] for x in items]
        ms = [x[1] for x in items]
        return {
            "n": len(items),
            "recall_at_5": round(avg(rs), 4),
            "mrr_at_10": round(avg(ms), 4),
        }

    return {
        "n_failed": len(failed),
        "failed_ids": [r.get("id") for r in failed],
        "n_in_domain": len(in_domain),
        "n_countable": len(countable),
        "n_content_gap": len(content_gap),
        "recall_at_5": round(avg(recalls), 4),
        "mrr_at_10": round(avg(mrrs), 4),
        "by_category": {c: block(v) for c, v in sorted(by_cat.items())},
        "by_difficulty": {d: block(v) for d, v in sorted(by_diff.items())},
        "worst_recall0": worst,
    }


def compute_judge_metrics(results: list[dict]) -> dict:
    """Faithfulness % и relevance avg по in-domain. Делаем 2 среза:
    full (все 100) и non_fallback (только содержательные ответы)."""
    in_domain = [r for r in results
                 if not r.get("is_ood") and r.get("judge") is not None]

    is_faithful = [r["judge"]["faithfulness"]["is_faithful"] for r in in_domain]
    relevances = [r["judge"]["relevance"]["score"] for r in in_domain
                  if isinstance(r["judge"]["relevance"]["score"], int)]

    # Срез без fallback-ответов.
    non_fb = [r for r in in_domain if not r["answer"]["is_fallback"]]
    is_faithful_nf = [r["judge"]["faithfulness"]["is_faithful"] for r in non_fb]
    relevances_nf = [r["judge"]["relevance"]["score"] for r in non_fb
                     if isinstance(r["judge"]["relevance"]["score"], int)]

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    unfaithful = [
        {
            "id": r["id"],
            "query": r["query"],
            "category": r["category"],
            "is_fallback": r["answer"]["is_fallback"],
            "lead": r["answer"]["lead"][:150],
            "unsupported_claims": r["judge"]["faithfulness"]["unsupported_claims"],
        }
        for r in in_domain
        if not r["judge"]["faithfulness"]["is_faithful"]
    ]
    low_relevance = [
        {
            "id": r["id"],
            "query": r["query"],
            "category": r["category"],
            "is_fallback": r["answer"]["is_fallback"],
            "score": r["judge"]["relevance"]["score"],
            "reasoning": r["judge"]["relevance"]["reasoning"],
        }
        for r in in_domain
        if isinstance(r["judge"]["relevance"]["score"], int)
        and r["judge"]["relevance"]["score"] < 3
    ]

    cost_paid = sum(r["judge"]["cost_usd_paid"] for r in in_domain)
    cost_rate = sum(r["judge"]["cost_usd_rate"] for r in in_domain)

    return {
        "n_judged": len(in_domain),
        "n_non_fallback": len(non_fb),
        "faithfulness_pct_full": round(avg(is_faithful), 4),
        "faithfulness_pct_non_fallback": round(avg(is_faithful_nf), 4),
        "relevance_avg_full": round(avg(relevances), 4),
        "relevance_avg_non_fallback": round(avg(relevances_nf), 4),
        "n_unfaithful": len(unfaithful),
        "n_low_relevance": len(low_relevance),
        "judge_cost_paid_usd": round(cost_paid, 6),
        "judge_cost_rate_usd": round(cost_rate, 6),
        "unfaithful_cases": unfaithful,
        "low_relevance_cases": low_relevance,
    }


def compute_refusal_metrics(results: list[dict]) -> dict:
    """Refusal rate на OOD: % ответов, помеченных is_fallback=true."""
    ood = [r for r in results if r.get("is_ood") and "answer" in r]
    refused = [r for r in ood if r["answer"]["is_fallback"]]
    not_refused = [
        {
            "id": r["id"],
            "query": r["query"],
            "genre": r.get("genre"),
            "lead": r["answer"]["lead"][:150],
            "top1_score": (r["retrieval_top_10"][0]["score"]
                           if r.get("retrieval_top_10") else None),
        }
        for r in ood
        if not r["answer"]["is_fallback"]
    ]
    return {
        "n_ood": len(ood),
        "n_refused": len(refused),
        "refusal_rate": round(len(refused) / len(ood), 4) if ood else None,
        "ood_not_refused_cases": not_refused,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=["mvp", "baseline"], default="mvp")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-judge", action="store_true",
                    help="не запускать LLM-judge (только retrieval-метрики)")
    ap.add_argument("--limit", type=int, default=None,
                    help="взять первые N запросов (для sanity)")
    ap.add_argument("--ood", action="store_true",
                    help="прогнать только OOD-набор")
    ap.add_argument("--outdir", type=str, default=None)
    args = ap.parse_args()

    use_cache = not args.no_cache
    install_caches(use_cache)
    apply_config(args.config)

    # Judge использует тот же Anthropic-клиент (с кэшем) что и generation.
    # Sonnet и Haiku — разные cache-keys, не пересекаются.
    judge_client = None if args.no_judge else generation._anthropic_client
    if judge_client is not None:
        print(f"[eval] judge model: {JUDGE_MODEL} (faithfulness + relevance)")

    ts = time.strftime("%Y%m%d_%H%M%S")
    outdir = (Path(args.outdir) if args.outdir
              else REPO / "data" / "eval" / "runs" / f"{args.config}_{ts}")
    outdir.mkdir(parents=True, exist_ok=True)

    golden = load_jsonl(REPO / "data" / "eval" / "golden_set.jsonl")
    ood = load_jsonl(REPO / "data" / "eval" / "ood_set.jsonl")

    if args.ood:
        items = [(o, True) for o in ood]
    else:
        items = [(g, False) for g in golden] + [(o, True) for o in ood]

    if args.limit is not None:
        items = items[: args.limit]

    print(f"[eval] config={args.config} cache={'on' if use_cache else 'off'} "
          f"judge={'on' if judge_client else 'off'} "
          f"n={len(items)} outdir={outdir}")

    results_path = outdir / "results.jsonl"
    started = time.perf_counter()
    results: list[dict] = []
    with open(results_path, "w", encoding="utf-8") as fout:
        for i, (item, is_ood) in enumerate(items, start=1):
            try:
                rec = run_one(item, is_ood, judge_client=judge_client)
            except Exception as e:
                print(f"  [{i}/{len(items)}] {item['id']} ERROR: {e!r}",
                      file=sys.stderr)
                rec = {
                    "id": item["id"],
                    "query": item["query"],
                    "is_ood": is_ood,
                    "category": item.get("category"),
                    "difficulty": item.get("difficulty"),
                    "expected_article_urls": item.get("expected_article_urls", []),
                    "error": repr(e),
                }
            results.append(rec)
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            if i % 10 == 0 or i == len(items) or args.limit is not None:
                lat = rec.get("latency_ms", {}).get("total")
                fb = rec.get("answer", {}).get("is_fallback")
                print(f"  [{i}/{len(items)}] {item['id']} "
                      f"lat={lat}ms fallback={fb}")

    elapsed = time.perf_counter() - started
    metrics = compute_retrieval_metrics(results)
    cost_paid_total = sum((r.get("cost_usd") or 0) for r in results)
    cost_rate_total = sum((r.get("cost_usd_rate") or 0) for r in results)

    judge_metrics = compute_judge_metrics(results) if judge_client else None
    refusal_metrics = compute_refusal_metrics(results)

    summary = {
        "config": args.config,
        "ts": ts,
        "n_total": len(results),
        "n_in_domain": sum(1 for r in results if not r.get("is_ood")),
        "n_ood": sum(1 for r in results if r.get("is_ood")),
        "elapsed_seconds": round(elapsed, 1),
        "cost_total_usd": round(cost_paid_total, 6),
        "cost_rate_usd": round(cost_rate_total, 6),
        "cache_stats": cache_stats(),
        "retrieval_metrics": {k: v for k, v in metrics.items()
                              if k != "worst_recall0"},
        "worst_retrieval_recall0": metrics["worst_recall0"],
        "judge_metrics": judge_metrics,
        "refusal_metrics": refusal_metrics,
    }
    summary_path = outdir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print()
    print("=== retrieval ===")
    print(f"  recall@5      = {metrics['recall_at_5']:.4f} "
          f"(n={metrics['n_countable']}, content-gap excluded={metrics['n_content_gap']})")
    print(f"  mrr@10        = {metrics['mrr_at_10']:.4f}")
    print(f"  by category:")
    for cat, blk in metrics["by_category"].items():
        print(f"    {cat:55s} n={blk['n']:>3d} "
              f"R@5={blk['recall_at_5']:.3f} MRR@10={blk['mrr_at_10']:.3f}")
    print(f"  by difficulty:")
    for d, blk in metrics["by_difficulty"].items():
        print(f"    {d:8s} n={blk['n']:>3d} "
              f"R@5={blk['recall_at_5']:.3f} MRR@10={blk['mrr_at_10']:.3f}")

    if judge_metrics:
        print()
        print("=== generation (judge) ===")
        print(f"  faithfulness  = {judge_metrics['faithfulness_pct_full']:.4f} "
              f"(full, n={judge_metrics['n_judged']})")
        print(f"                  {judge_metrics['faithfulness_pct_non_fallback']:.4f} "
              f"(non-fallback, n={judge_metrics['n_non_fallback']})")
        print(f"  relevance avg = {judge_metrics['relevance_avg_full']:.4f} "
              f"(full)")
        print(f"                  {judge_metrics['relevance_avg_non_fallback']:.4f} "
              f"(non-fallback)")
        print(f"  unfaithful    = {judge_metrics['n_unfaithful']}")
        print(f"  low relevance = {judge_metrics['n_low_relevance']} (score < 3)")

    if refusal_metrics["n_ood"]:
        print()
        print("=== refusal (OOD) ===")
        print(f"  refusal rate  = {refusal_metrics['refusal_rate']:.4f} "
              f"({refusal_metrics['n_refused']}/{refusal_metrics['n_ood']})")
        for c in refusal_metrics["ood_not_refused_cases"]:
            print(f"    NOT refused: {c['id']} ({c['genre']}) — "
                  f"score={c['top1_score']} lead={c['lead'][:80]}")

    print()
    print("=== cost ===")
    print(f"  generation paid  = ${cost_paid_total:.4f}")
    print(f"  generation rate  = ${cost_rate_total:.4f}")
    if judge_metrics:
        print(f"  judge paid       = ${judge_metrics['judge_cost_paid_usd']:.4f}")
        print(f"  judge rate       = ${judge_metrics['judge_cost_rate_usd']:.4f}")
    print(f"  cache stats      = {cache_stats()}")
    print(f"  elapsed          = {elapsed:.1f}s")
    print(f"  outdir           = {outdir}")


if __name__ == "__main__":
    main()
