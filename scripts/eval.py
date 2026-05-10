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

import bm25 as bm25_module  # noqa: E402
import generation  # noqa: E402
import retrieval  # noqa: E402
import spell as spell_module  # noqa: E402
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

═══════════════════════════════════════════════════════════════════════
ПРАВИЛО ОПРЕДЕЛЕНИЯ is_faithful:

is_faithful = true  ⇔  в списке unsupported_claims нет ни одного "hard" claim'а.

"Hard" claim — это утверждение которое ПРОТИВОРЕЧИТ источникам или ВЫДУМАНО (нет в источниках). Только такие включаются в unsupported_claims.

"Soft" claim (НЕ считать unsupported, НЕ включать в список):
- стилистические переформулировки факта который есть в источниках;
- упрощения или обобщения которые сохраняют смысл;
- неполная передача информации из чанка (если основной факт верен);
- пометки самого judge типа "(ок)", "подкреплено чанком N", "не проверяем",
  "упомянуто корректно", "не противоречит чанку", "формулировка корректна";
- утверждения типа "X отсутствует в ответе", "не упомянуто Y", "пропущено Z" —
  это про completeness, не про faithfulness, НЕ флагим.

Если в результате анализа у тебя в unsupported_claims остались только soft claims или пометки "ОК" — is_faithful ОБЯЗАН быть true, а сам список ОБЯЗАН быть пустым.

═══════════════════════════════════════════════════════════════════════
OVERGENERALIZATION — это HARD unsupported:

Если модель применяет факт из источника к более широкому случаю чем в источнике — это hard, флагим.

Пример: в чанке "15 дней для домашней доставки", в ответе "15 дней для всех типов доставки" → HARD.
Пример: в чанке "только для ПВЗ", в ответе "также работает на постаматах" → HARD.
Пример: в чанке "инструкция продавцу", в ответе "инструкция покупателю" (wrong audience) → HARD.

═══════════════════════════════════════════════════════════════════════
ПРИМЕР 1 (is_faithful=true, soft переформулировки):

ВОПРОС: сколько стоит доставка кто платит
ОТВЕТ:
  Обычно доставку полностью оплачивает покупатель. Стоимость формируется
  автоматически в зависимости от категории товара, цены и расстояния.
  Некоторые продавцы могут сделать скидку на доставку в пункт выдачи —
  такие объявления помечены специальным значком.
ЧАНКИ:
  [Чанк 1] Обычно доставку полностью оплачивает покупатель. Стоимость
  формируется автоматически в зависимости от категории, цены, веса,
  габаритов, расстояния. Некоторые продавцы могут предоставить скидку
  на доставку в пункт выдачи — у таких объявлений отображается
  специальный значок.

Анализ:
- claim "обычно покупатель оплачивает доставку" — точная цитата из чанка → soft, не флагим;
- claim "стоимость формируется автоматически в зависимости от категории, цены, расстояния" —
  переформулировка чанка с упрощением (упущены "вес/габариты"). Основной факт верен → soft, не флагим;
- claim "продавцы могут сделать скидку, объявления помечены значком" —
  переформулировка → soft, не флагим.

Результат: { "is_faithful": true, "unsupported_claims": [] }

═══════════════════════════════════════════════════════════════════════
ПРИМЕР 2 (is_faithful=false, реальная overgeneralization):

ВОПРОС: как сделать возврат если заказ не подошёл
ОТВЕТ:
  Если заказ уже у вас — можете вернуть его в течение 15 дней.
  Если получаете через постамат — заберите товар, потом договоритесь
  с продавцом о возврате напрямую.
ЧАНКИ:
  [Чанк 1] При доставке на дом покупатель может вернуть товар в
  течение 15 дней с момента получения.
  [Чанк 2] Если заказ через постамат или кассу 5Post вам не подошёл —
  отказаться и положить обратно не получится. Заберите товар.

Анализ:
- claim "можете вернуть его в течение 15 дней" подан как универсальный, без оговорки про
  тип доставки. В чанках срок 15 дней указан ТОЛЬКО для доставки на дом, а для постамата
  срока нет → overgeneralization → HARD.

Результат: {
  "is_faithful": false,
  "unsupported_claims": [
    "обобщение срока 15 дней на все типы доставки — в чанках срок указан только для доставки на дом"
  ]
}

═══════════════════════════════════════════════════════════════════════

ИНСТРУКЦИЯ:
Если хотя бы одно утверждение действительно противоречит источникам или выдумано — is_faithful=false, перечисли его в unsupported_claims короткой фразой. Иначе — is_faithful=true, unsupported_claims=[]."""


# Hard-disqualifier'ы: явные сигналы что claim — реальный hard-unsupported.
# Если найден — claim НЕ soft даже если есть soft-маркеры рядом
# (например "(сдвинуть вправо) корректна, но утверждение X не подкреплено").
_HARD_DISQUALIFIERS = (
    "не подкреплен",       # не подкреплено / не подкреплён / не подкреплены
    "противоречит чанк",
    "противоречат чанк",
    "корректна, но",
    "корректно, но",
    "обобщен",             # обобщено / обобщение / обобщён
    "overgeneraliz",
    "выдуман",
    "адресован",           # wrong audience: «инструкция адресована продавцу»
    "wrong audience",
)

# Явные soft-маркеры. Без них claim — потенциально hard, override не делаем.
# Узкие подстроки чтобы избежать ложных срабатываний на «не подкреплено» и т.п.
_SOFT_MARKERS = (
    "(ок)", "(ок,", "(ок.", "(ok)",
    ", ок)", ", ок,", ", ок.",
    "— ок", "— ок,", "— ок.", "— ОК", "— ОК,", "— ОК.",
    " ок;", " ок:",
    "подкреплено чанком",
    "подкреплено в чанке",
    "подкреплён чанком",
    "подкреплены чанком",
    "не проверяем",
    "не противоречит чанк",
    "не противоречат чанк",
    "не противоречие",
    "структурное упрощение",
)


def _looks_soft(claim: str) -> bool:
    """True если claim — soft (стилистический / явная пометка ОК / completeness).

    Алгоритм: сначала ищем hard-disqualifier — если есть, претендент hard.
    Иначе ищем soft-marker. Только при явном soft-маркере считаем soft.
    """
    if not claim or not claim.strip():
        return True
    low = claim.lower()
    if any(h in low for h in _HARD_DISQUALIFIERS):
        return False
    return any(s in low for s in _SOFT_MARKERS)


def _override_is_faithful(judge_out: dict) -> tuple[bool, bool]:
    """Страховка: если judge помечает is_faithful=false, но все unsupported_claims
    выглядят как soft (содержат маркеры «(ок)», «подкреплено», «не проверяем» и т.п.),
    переопределяем на true локально.

    Возвращает (final_is_faithful, override_applied).
    """
    if judge_out.get("is_faithful"):
        return True, False
    claims = judge_out.get("unsupported_claims") or []
    if not claims:
        # is_faithful=false при пустом списке — буг judge'а, переопределяем.
        return True, True
    if all(_looks_soft(c) for c in claims):
        return True, True
    return False, False

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
        # Sprint 6 Блок 2: mvp по умолчанию = hybrid (BM25 + bi-encoder + RRF).
        # Faithfulness/safety фиксы из Sprint 5 Блоков 1+2+3.5 продолжают работать
        # (они независимы от retrieval-механизма).
        retrieval.USE_RERANKER = False
        retrieval.USE_HYBRID_RETRIEVAL = True
        retrieval._reranker = None
        generation.RETRIEVAL_THRESHOLD = 0.3
        return
    if config == "bi_only":
        # Sprint 6 Блок 3 ablation: только bi-encoder (Sprint 5 final state).
        # На текущем кэше = $0 (top-5 идентичны Sprint 5 mvp_20260509_153514).
        retrieval.USE_RERANKER = False
        retrieval.USE_HYBRID_RETRIEVAL = False
        retrieval._reranker = None
        generation.RETRIEVAL_THRESHOLD = 0.3
        return
    if config == "baseline":
        # Ablation Sprint 5 Блока 2: без safety-priming. Retrieval — bi-only
        # (как было в Sprint 5; для Sprint 6 ablation hybrid-без-safety не нужно).
        retrieval.USE_RERANKER = False
        retrieval.USE_HYBRID_RETRIEVAL = False
        retrieval._reranker = None
        generation.RETRIEVAL_THRESHOLD = 0.3
        generation._needs_safety_priming = lambda query, hits: False
        return
    if config == "mvp_with_reranker":
        # Ablation для журнала Sprint 5 Блока 3: reranker v2-m3 + candidates=20.
        # Не используем как mvp — оставлено для воспроизводимости старых runs.
        retrieval.USE_RERANKER = True
        retrieval.USE_HYBRID_RETRIEVAL = False
        retrieval._reranker = None
        retrieval.RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
        retrieval.RERANKER_CANDIDATES = 20
        generation.RETRIEVAL_THRESHOLD = 0.55
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
    raw = {
        "is_faithful": bool(ti.get("is_faithful", False)),
        "unsupported_claims": list(ti.get("unsupported_claims") or []),
    }
    final_faithful, override_applied = _override_is_faithful(raw)
    return {
        "is_faithful": final_faithful,
        "unsupported_claims": [] if override_applied else raw["unsupported_claims"],
        "judge_override": override_applied,
        "raw_is_faithful": raw["is_faithful"],
        "raw_unsupported_claims": raw["unsupported_claims"],
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
    result = generation.generate(query, hits[:5])  # Sprint 5 Блок 5 final: после отката reranker top_k=5 вернулся
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


def run_one_retrieval_only(item: dict, is_ood: bool) -> dict:
    """Sprint 6 Блок 3.2: только retrieval (skip generation + judge).

    Считаем синтетический is_fallback по тому же правилу что в `generation.generate()`:
        is_fallback = (not hits) or (max bi_score < threshold) or competitor-query
    Это чистый retrieval-side decision, LLM не нужен. Cost = $0 (только embed cache hit).
    """
    query = item["query"]
    s0 = cache_stats()
    t_ret = time.perf_counter()
    hits = retrieval.search(query, top_k=10)
    t_ret_ms = (time.perf_counter() - t_ret) * 1000
    s1 = cache_stats()
    embedding_hit = s1["emb_hits"] > s0["emb_hits"]

    bi_top1 = max((h.bi_score for h in hits), default=0.0)
    is_fallback = (
        not hits
        or bi_top1 < generation.RETRIEVAL_THRESHOLD
        or generation._is_competitor_query(query)
    )

    return {
        "id": item["id"],
        "query": query,
        "is_ood": is_ood,
        "category": item.get("category"),
        "difficulty": item.get("difficulty"),
        "notes": item.get("notes", ""),
        "expected_article_urls": item.get("expected_article_urls", []),
        "genre": item.get("genre"),
        "retrieval_top_10": [hit_to_dict(h) for h in hits],
        # Синтетический answer-блок только с is_fallback (для compute_refusal_metrics).
        "answer": {
            "lead": "",
            "sections": [],
            "sources_used": [],
            "sources": [],
            "is_fallback": is_fallback,
        },
        "synthetic_fallback": True,  # помечаем что это retrieval-only прогон
        "bi_top1_score": round(bi_top1, 4),
        "is_competitor_query": generation._is_competitor_query(query),
        "cache_hit": {"anthropic": False, "embedding": embedding_hit},
        "latency_ms": {
            "retrieval": round(t_ret_ms, 1),
            "generation": 0.0,
            "total": round(t_ret_ms, 1),
        },
        "retrieval_mode": retrieval.last_search_timings.get("mode"),
    }


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


def _find_latest_run(prefix: str) -> Path:
    runs_dir = REPO / "data" / "eval" / "runs"
    matches = sorted(p for p in runs_dir.iterdir()
                     if p.is_dir() and p.name.startswith(prefix + "_"))
    if not matches:
        raise SystemExit(f"no runs with prefix {prefix!r} in {runs_dir}")
    return matches[-1]


def _stub_from_record(rec: dict):
    """Восстанавливаем минимальные объекты hits + result из results.jsonl записи,
    достаточные для _build_chunks_for_judge и _build_answer_text."""
    from types import SimpleNamespace

    hits = [SimpleNamespace(
        chunk_id=h["chunk_id"],
        article_id=h["article_id"],
        article_url=h["article_url"],
        title=h["title"],
        category=h["category"],
        score=h["score"],
        chunk_text=h["chunk_text"],
    ) for h in rec.get("retrieval_top_10", [])]

    ans = rec.get("answer") or {}
    sections = [SimpleNamespace(title=s["title"], body=s["body"])
                for s in ans.get("sections", [])]
    result = SimpleNamespace(
        lead=ans.get("lead", ""),
        sections=sections,
        sources_used=ans.get("sources_used", []),
        sources=ans.get("sources", []),
        is_fallback=ans.get("is_fallback", False),
        model=rec.get("model"),
        usage=rec.get("usage", {}),
    )
    return hits, result


def run_rerun_judge_only(from_run: Path, outdir: Path,
                         only_ids: list[str] | None = None,
                         limit: int | None = None) -> None:
    """Пересчёт только judge на сохранённых ответах из from_run.

    only_ids — фильтр по списку id запросов (для sanity-теста на кейсах).
    limit — взять первые N записей.
    """
    src = from_run / "results.jsonl"
    if not src.exists():
        raise SystemExit(f"no results.jsonl in {from_run}")

    judge_client = generation._anthropic_client
    print(f"[rerun-judge-only] from: {from_run}")
    print(f"[rerun-judge-only] judge model: {JUDGE_MODEL}")

    outdir.mkdir(parents=True, exist_ok=True)
    results_path = outdir / "results.jsonl"

    started = time.perf_counter()
    results: list[dict] = []
    src_records = load_jsonl(src)
    if only_ids:
        wanted = set(only_ids)
        src_records = [r for r in src_records if r.get("id") in wanted]
    if limit is not None:
        src_records = src_records[:limit]
    n = len(src_records)
    with open(results_path, "w", encoding="utf-8") as fout:
        for i, rec in enumerate(src_records, start=1):
            new_rec = dict(rec)  # копируем как есть retrieval/answer/cost — они валидны
            # error-record'ы (без answer) пропускаем мимо judge
            if "answer" not in rec or rec.get("is_ood"):
                # OOD не judge'им — оставляем без изменений (но удаляем старый judge,
                # если он там был, чтобы summary считался корректно)
                new_rec.pop("judge", None)
                fout.write(json.dumps(new_rec, ensure_ascii=False) + "\n")
                fout.flush()
                results.append(new_rec)
                continue
            try:
                hits, result = _stub_from_record(rec)
                jb = _judge_pair(judge_client, rec["query"], result, hits)
                new_rec["judge"] = jb
            except Exception as e:
                print(f"  [{i}/{n}] {rec.get('id')} JUDGE_ERROR: {e!r}",
                      file=sys.stderr)
                new_rec["judge"] = {"error": repr(e)}
            results.append(new_rec)
            fout.write(json.dumps(new_rec, ensure_ascii=False) + "\n")
            fout.flush()
            if i % 10 == 0 or i == n:
                fb = new_rec.get("answer", {}).get("is_fallback")
                jf = (new_rec.get("judge", {}) or {}).get("faithfulness", {})
                print(f"  [{i}/{n}] {rec['id']} fallback={fb} "
                      f"is_faithful={jf.get('is_faithful')} "
                      f"override={jf.get('judge_override')}")

    elapsed = time.perf_counter() - started

    # Метрики: retrieval — те же что в исходном run (генерация и retrieval не менялись),
    # но пересчёт по тем же данным даст идентичный результат, так что считаем заново.
    metrics = compute_retrieval_metrics(results)
    judge_metrics = compute_judge_metrics(results)
    refusal_metrics = compute_refusal_metrics(results)

    n_overrides = sum(
        1 for r in results
        if (r.get("judge") or {}).get("faithfulness", {}).get("judge_override")
    )

    summary = {
        "config": "rerun_judge_only",
        "ts": time.strftime("%Y%m%d_%H%M%S"),
        "from_run": str(from_run),
        "n_total": len(results),
        "n_in_domain": sum(1 for r in results if not r.get("is_ood")),
        "n_ood": sum(1 for r in results if r.get("is_ood")),
        "n_judge_overrides": n_overrides,
        "elapsed_seconds": round(elapsed, 1),
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
    print("=== retrieval (from source run, без изменений) ===")
    print(f"  recall@5 = {metrics['recall_at_5']:.4f}  "
          f"mrr@10 = {metrics['mrr_at_10']:.4f}  "
          f"n_countable={metrics['n_countable']}")
    print()
    print("=== generation (judge, новый промпт) ===")
    print(f"  faithfulness  = {judge_metrics['faithfulness_pct_full']:.4f} "
          f"(full, n={judge_metrics['n_judged']})")
    print(f"                  {judge_metrics['faithfulness_pct_non_fallback']:.4f} "
          f"(non-fallback, n={judge_metrics['n_non_fallback']})")
    print(f"  relevance avg = {judge_metrics['relevance_avg_full']:.4f} (full)  "
          f"{judge_metrics['relevance_avg_non_fallback']:.4f} (non-fb)")
    print(f"  unfaithful    = {judge_metrics['n_unfaithful']}")
    print(f"  judge overrides = {n_overrides}")
    print()
    print("=== refusal (OOD) ===")
    print(f"  refusal rate = {refusal_metrics['refusal_rate']} "
          f"({refusal_metrics['n_refused']}/{refusal_metrics['n_ood']})")
    print()
    print("=== cost ===")
    print(f"  judge paid = ${judge_metrics['judge_cost_paid_usd']:.4f}")
    print(f"  judge rate = ${judge_metrics['judge_cost_rate_usd']:.4f}")
    print(f"  cache stats= {cache_stats()}")
    print(f"  elapsed    = {elapsed:.1f}s")
    print(f"  outdir     = {outdir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config",
                    choices=["mvp", "bi_only", "baseline", "mvp_with_reranker"],
                    default="mvp")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-judge", action="store_true",
                    help="не запускать LLM-judge (только retrieval-метрики)")
    ap.add_argument("--retrieval-only", action="store_true",
                    help="только retrieval (skip generation + judge); $0 paid")
    ap.add_argument("--limit", type=int, default=None,
                    help="взять первые N запросов (для sanity)")
    ap.add_argument("--ood", action="store_true",
                    help="прогнать только OOD-набор")
    ap.add_argument("--outdir", type=str, default=None)
    ap.add_argument("--rerun-judge-only", action="store_true",
                    help="пересчёт только judge на сохранённых ответах "
                         "из --from-run (или из последнего mvp_*-прогона)")
    ap.add_argument("--from-run", type=str, default=None,
                    help="путь к папке run'а для --rerun-judge-only")
    ap.add_argument("--ids", type=str, default=None,
                    help="фильтр по id через запятую "
                         "(для sanity-теста --rerun-judge-only)")
    args = ap.parse_args()

    if args.rerun_judge_only:
        install_caches(use_cache=not args.no_cache)
        from_run = (Path(args.from_run) if args.from_run
                    else _find_latest_run("mvp"))
        only_ids = ([s.strip() for s in args.ids.split(",")]
                    if args.ids else None)
        ts = time.strftime("%Y%m%d_%H%M%S")
        outdir = (Path(args.outdir) if args.outdir
                  else REPO / "data" / "eval" / "runs"
                       / f"mvp_v2_judge_{ts}")
        run_rerun_judge_only(from_run, outdir,
                             only_ids=only_ids, limit=args.limit)
        return

    use_cache = not args.no_cache
    install_caches(use_cache)

    # Sprint 6 Блок 3: инициализируем BM25 singleton для hybrid-режимов.
    # На bi_only / mvp_with_reranker не используется, но build занимает ~500ms
    # и не блокирует eval — делаем безусловно.
    try:
        bm25_module.init_from_chroma(retrieval.get_chroma_collection())
        print(f"[eval] BM25 ready ({bm25_module.get_searcher().size} chunks)")
    except Exception as e:
        print(f"[eval] BM25 init failed (continuing without): {e!r}",
              file=sys.stderr)

    # Sprint 7 Block 1: spell-corrector vocab из BM25-корпуса. Если
    # USE_SPELL_CORRECTION=false — corrector не используется в search(),
    # но init дешёвый (~100ms) и не мешает ablation.
    try:
        searcher = bm25_module.get_searcher()
        if searcher is not None:
            corrector = spell_module.init_from_vocab(searcher.vocab_frequencies())
            print(f"[eval] spell ready (vocab={corrector.vocab_size}, "
                  f"deletes={corrector.index_size})")
    except Exception as e:
        print(f"[eval] spell init failed (continuing without): {e!r}",
              file=sys.stderr)

    apply_config(args.config)

    # Judge использует тот же Anthropic-клиент (с кэшем) что и generation.
    # Sonnet и Haiku — разные cache-keys, не пересекаются.
    judge_client = (
        None
        if (args.no_judge or args.retrieval_only)
        else generation._anthropic_client
    )
    if judge_client is not None:
        print(f"[eval] judge model: {JUDGE_MODEL} (faithfulness + relevance)")

    ts = time.strftime("%Y%m%d_%H%M%S")
    if args.outdir:
        outdir = Path(args.outdir)
    elif args.retrieval_only:
        outdir = REPO / "data" / "eval" / "runs" / f"{args.config}_retrieval_only_{ts}"
    else:
        outdir = REPO / "data" / "eval" / "runs" / f"{args.config}_{ts}"
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
          f"retrieval_only={args.retrieval_only} "
          f"n={len(items)} outdir={outdir}")

    results_path = outdir / "results.jsonl"
    started = time.perf_counter()
    results: list[dict] = []
    with open(results_path, "w", encoding="utf-8") as fout:
        for i, (item, is_ood) in enumerate(items, start=1):
            try:
                if args.retrieval_only:
                    rec = run_one_retrieval_only(item, is_ood)
                else:
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
