# АИ-Помощь — AI Overview по справке Авито

RAG-пайплайн поверх 518 статей [support.avito.ru](https://support.avito.ru): вопрос на естественном языке → краткий ответ со ссылками на источники за ~5 секунд. Аналог AI Overview в Google для help-центра.

**Демо:** [avi-help.vercel.app](https://avi-help.vercel.app/)


## Что закрыто из PRD (8 из 9)

| Метрика | Цель | Факт |
|---|---|---|
| Recall@5 | ≥ 0.85 | **0.854** |
| MRR@10 | ≥ 0.6 | 0.702 |
| Faithfulness (LLM-as-judge) | ≥ 0.7 | **0.74** |
| Refusal rate (OOD) | 1.0 | 1.0 |
| TTFB до пилюль источников | ≤ 500 мс | **151 мс** |
| P50 / P95 полного ответа | ≤ 5 / 8 с | 4.8 / 7.3 с |
| Cost / запрос | ≤ $0.005 | $0.0068 ❌ |


## Архитектура

**Offline** (build, ~2 мин, $0.025): `parse_articles.py` → `build_chunks.py` → `build_index.py` (Chroma, OpenAI `text-embedding-3-small`) + `build_bm25_index.py`.

**Online** (~5 с/запрос):
1. Pre-LLM фильтр (конкуренты / OOD)
2. Spell-correction (SymSpell, vocab из BM25)
3. Bi-encoder retrieval (Chroma, top-20)
4. BM25 retrieval (top-20, параллельно)
5. RRF merge → top-5
6. **Adaptive bi-only routing (T4)** — если в hybrid топ-5 есть `bi_score<0.3` И `top1_bi≥0.6` → fallback в bi-only
7. Claude Haiku 4.5 + tool use → структурированный JSON со стримингом


## Стек

- **Бэкенд:** Python 3.12, FastAPI, async SSE стриминг
- **Retrieval:** Chroma (1536 dim, 68 MB), rank-bm25 (in-RAM)
- **Embeddings:** OpenAI `text-embedding-3-small`
- **Генерация:** Claude Haiku 4.5 + tool use
- **LLM-judge:** Claude Sonnet 4.6 (только в eval)
- **Фронт:** Vite + React, ~107 KB gzipped, native SSE
- **Деплой:** Railway (бэк + volume), Vercel (фронт)

## Структура репо

```
backend/         FastAPI + retrieval + generation + админка
frontend/        Vite + React UI со стримингом
scripts/         parse_articles, build_chunks, build_index, build_bm25_index, eval
data/
  articles.jsonl       4288 чанков
  chroma/              векторный индекс
  bm25_index.pkl       BM25 индекс
  eval/golden_set.jsonl     100 in-domain Q
  eval/ood_set.jsonl        20 OOD Q
docs/            PRD, TDR, ML System Design, журналы спринтов
```

## Запуск

```bash
# 1. Бэкенд
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # ANTHROPIC_API_KEY, OPENAI_API_KEY, ADMIN_TOKEN
uvicorn main:app --reload

# 2. Фронт
cd frontend && npm i && npm run dev

# 3. Eval
cd backend && .venv/bin/python ../scripts/eval.py --config mvp
```

## Лицензия и данные

Некоммерческий пет-проект. Использованы публичные данные [support.avito.ru](https://support.avito.ru) для демонстрации ML-продукта.
