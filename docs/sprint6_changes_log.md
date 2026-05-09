# Sprint 6 — Журнал технических изменений

**Дата старта:** 2026-05-09
**Цель спринта:** внедрить BM25 + bi-encoder + RRF (Reciprocal Rank Fusion) как production retrieval. Закрыть PRD-цель Recall@5 ≥ 0.85 без инфра-апгрейда.
**Принцип:** одна правка = один замер = одна запись в этом журнале.

---

## Baseline (Sprint 5 final, post-rollback)

| Метрика | Sprint 5 final | Цель PRD |
|---|---|---|
| Recall@5 | 0.8125 | ≥ 0.85 |
| MRR@10 | 0.7007 | ≥ 0.6 |
| Faithfulness (non-fb) | 0.6907 | ≥ 0.85 (revised) |
| Relevance avg (non-fb) | 4.6495 | ≥ 4 |
| Refusal rate (OOD) | 1.0 | 1.0 |
| Latency P50 (prod) | 4.56s | ≤ 5s (revised TTFB) |
| Latency P95 (prod) | 7.32s | ≤ 8s |
| Cost per query | $0.0068 | ≤ $0.005 (caching roadmap) |

Источники: `docs/eval_results.md`, `data/eval/runs/mvp_20260509_153514/`, `data/eval/prod_latency_v3/results.json`.

**Конфигурация Sprint 5 final (то на чём строимся):**
- Bi-encoder: `text-embedding-3-small` (1536 dim) + Chroma 4288 чанков из 518 статей.
- Threshold pre-LLM fallback: top-1 cosine `< 0.3` на bi-encoder scale.
- Reranker: **OFF** (`USE_RERANKER=false`, в коде остался opt-in).
- Top_k в LLM: 5.
- Generation: Claude Haiku 4.5 + tool use, FAITHFULNESS_SYSTEM v4 + override (Sprint 5 Блок 1), SAFETY_TRIGGERS query-уровень (Блок 2), COMPETITOR_PLATFORMS (Блок 3.5).
- Бюджет: $9.04 потрачено в Sprint 5, остаток $5.96 от $15.

---

## Failure cases для отслеживания (контрольная группа)

### Probe BM25 hybrid вернул 4/5 на cherry-picked

| id | query | expected | BM25 alone | bi-encoder alone | hybrid (RRF k=60) | гипотеза по полному eval |
|---|---|---|---|---|---|---|
| g002 | трек номер не отслеживается | 2802 | not in top-20 | not in top-10 | ❌ not in top-5 | content gap, не лечится никаким retrieval'ом — roadmap для HyDE / multi-query |
| g020 | телефон со сколом | 2831, 4400 | #1 | not in top-10 | ✅ #1 | ожидаем починку — главный win probe (cherry-pick победитель), который не закрыл reranker в Sprint 5 |
| g050 | оплата прошла два раза | 4440, 4389 | #6 | #2 | ✅ #4 | ожидаем починку, R@5=1 в Sprint 5 но в pre-LLM fallback (top-1 score 0.548) |
| g061 | vip для обяв | 2148, 4194 | not in top-20 | #2 | ✅ #4 | demo-blocker Sprint 5 (top-1 0.510 < 0.55 в Блоке 3.5) — ожидаем что hybrid RRF поднимет score |
| g023 | перейти в вотсап | 4331, 4334 | #1 | #1 | ✅ #1 | оба ранкера согласны, ожидаем стабильно top-1 |

**Probe-результат 4/5 cherry-picked — это верхняя оценка.** На полном golden-сете эффект будет меньше потому что cherry-picked кейсы выбраны как BM25-friendly (короткие лексически-плотные запросы).

### Failure cases Sprint 5 с Recall@5=0 (контрольная группа)

**Группа A — короткие/разговорные (BM25 ожидаем поможет на части):**
- g002 — «трек номер не отслеживается куда копать» — content gap (expected 2802 не в top-20 bi-encoder)
- g011 — «курьер не приехал что делать» — expected 2462 на позиции 17/20 в bi-encoder, reranker не вытянул в Sprint 5; BM25 может найти через лексику «курьер»
- g020 — «приехал телефон со сколом на экране» — probe подтвердил BM25 #1

**Группа B — реальные галлюцинации (Recall=1 в Sprint 5, но faith=False):**
- g003 — «как сделать возврат если заказ не подошёл» — overgeneralization про 15 дней
- g014 — «включить доставку в обявах» — выдуманное «сдвиньте вправо»
- g017 — «отправить посылку через авито» — split фразы + выдуманные 48 часов

**Гипотеза по группе B:** BM25 не должен их трогать (retrieval уже находит правильную статью; галлюцинация — на стороне generation, не retrieval). Если faithfulness регрессирует на этих ID — это побочка от смены top-5 порядка → новые формулировки → judge находит другое.

### Failure cases Sprint 5 в pre-LLM fallback (R@5=1, но in-domain в fallback)

| id | query | top-1 bi-encoder | гипотеза по hybrid |
|---|---|---|---|
| g023 | перейти в вотсап | 0.508 | RRF score высокий (BM25 #1 + bi #1) → вернётся в LLM |
| g050 | оплата прошла два раза | 0.548 | ожидаем подъём через лексическое совпадение |
| g061 | vip для обяв | 0.510 | demo-blocker; зависит от того подхватит ли BM25 «vip» как термин |

**Важно:** threshold pre-LLM fallback в Sprint 6 остаётся на bi_score 0.3 (см. Блок 2) — то есть фолбэк решается по bi-encoder части независимо от BM25. Это означает что **g023/g050/g061 могут так и остаться в fallback** если их bi_score top-1 < 0.3 — но если bi_score top-1 ≥ 0.3, hybrid даст лучший top-5 и ответ будет более релевантным.

### OOD-кейсы (контроль refusal rate)

20 OOD из Sprint 5 — refusal rate 1.0 через 2 механизма:
- 18 ловятся по threshold 0.3 на bi-encoder cosine
- 2 («юла», «озон») — через competitor-list (Sprint 5 Блок 3.5)

В Sprint 6 ожидание: refusal rate **остаётся 1.0** потому что (а) threshold на bi_score не трогаем, (б) competitor-list работает на уровне query и не зависит от retrieval.

**Риск:** BM25 может выдать высокие RRF scores на OOD-запросах с лексикой пересекающейся с Авито (например, «доставка озон» — слово «доставка» широко представлено в чанках). Но финальное решение по fallback — на bi_score. Sanity на OOD в Блоке 2.

---

## Изменение #1 — BM25 индекс

**Дата:** 2026-05-09
**Время на разработку:** ~1.5ч (модуль + sanity + lifespan + дебаг расхождения с probe)
**$ потрачено:** $0 (никаких LLM/embed-вызовов)

### Что конкретно сделано

- `backend/bm25.py` (новый, 130 строк) — singleton-модуль:
  - `tokenize_ru(text)` — `lowercase + re.split(r"[\W_]+", flags=UNICODE) + len ≥ 2`. Без стемминга, стоп-слов, лемматизации (минимальный baseline по брифу).
  - `BM25Searcher` — wraps `BM25Okapi` со stable `chunk_id`-маппингом; `from_documents`, `from_chroma`, `search(query, top_k)`, `save(path)`, `load(path)`.
  - `init_from_chroma(collection)` / `get_searcher()` — модульный singleton (аналогично `_chroma_client` в `retrieval.py`).
- `scripts/build_bm25_index.py` (новый) — собирает индекс из Chroma, sanity-search на golden g020 (полный запрос из `golden_set.jsonl`), сохраняет в `data/bm25_index.pkl`.
- `backend/main.py` — в `_startup()` после `warmup()` добавлен `init_bm25_from_chroma(get_chroma_collection())` с timing-логом; новое поле `_BM25_INIT_ERROR` + `/health` теперь возвращает `bm25_ready: bool`.
- `backend/requirements.txt` — добавлен `rank-bm25==0.2.2` (chistopython, ~5 KB).
- `.gitignore` — добавлен `data/bm25_index.pkl` (бинарный, ~4.7 MB, пересобирается скриптом).

### Гипотеза (что ожидали)

- BM25 индекс собирается за <2 сек на 4288 чанков (бриф порог).
- Sanity-search g020 находит статью 2831 в top-3 (по probe — должна быть #1).
- Lifespan event добавляет +1-2 сек к cold start FastAPI.
- Никаких регрессий в bi-encoder retrieval — мы только добавили модуль, существующий `search()` не трогали.

### Результат

- **BM25 индекс:** 4288 чанков, vocab 18433 терминов, avgdl 78.7 (с длиновым фильтром ≥2). Build time **414–500ms** на M-series — **в 4× быстрее порога**.
- **Sanity g020 («приехал телефон со сколом…»):** статья 2831 на rank **#1** (chunk `2831_007`, score 23.097). 4 из 8 чанков 2831 в top-10. ✓
- **Pickle round-trip:** save → load → search идентичный результат.
- **Lifespan:** через `from main import _startup; _startup()` → `[bm25] index built over 4288 chunks in 414ms` в stderr; `/health` возвращает `bm25_ready: true`.

### Расхождение с брифом (документирую)

- **Sanity-query:** бриф предложил `«телефон со сколом»` — на полном корпусе эта строка **не находит 2831 даже в top-10**. Причина: чанки 2831 не содержат токенов «телефон» или «сколом» (только формы «скол», «сколов», «сколы» — а у нас нет стемминга). Проверено: 4288 чанков, 0 матчей с «сколом», 0 — с «телефон» в чанках 2831. **Использую полный golden-запрос g020** (123 символа, в нём «приехал», «продавец», «деньги» — все есть в чанках 2831) — на нём BM25 находит 2831 на #1, что воспроизводит probe-результат журнала Sprint 5.
- **Title prefix в корпусе:** `from_chroma()` склеивает `meta['title'] + "\n" + document` перед токенизацией — **mirror** probe'а (`scripts/bm25_probe.py:116`). Document в Chroma уже начинается с title (см. `articles.jsonl`), поэтому префикс даёт **двойной title** → лёгкий upweighting заголовков. Без этого upweighting'а 2831 на той же query падает на rank #3. Probe валидирован на 4/5 cherry-picked именно с этой токенизацией.
- **Длиновый фильтр ≥ 2:** бриф предписывает, probe не имеет. Тестировал обе версии — на g020 рank #1 получается в обеих, но фильтр чище (1-char токены типа «и»/«а» не засоряют vocab). Идём с фильтром по брифу.

### Failure cases (probe baseline зафиксирован)

Полный probe-результат на 5 cherry-picked воспроизведён без изменений (тот же `scripts/bm25_probe.py` запускался для финал-сверки):

| id | BM25 alone (Sprint 6 build) | Что подтвердилось |
|---|---|---|
| g002 | not in top-20 | content gap — никакая токенизация не лечит |
| g020 | #1 (`2831_007`) | главный win, как в probe |
| g050 | #6 (top-20) | BM25 нашёл, hybrid в Блоке 2 поднимет |
| g061 | not in top-20 | сленг «обяв» не лексически связан с «vip» — BM25 alone бессилен; роль для bi-encoder в hybrid |
| g023 | #1 (`4331_xxx`) | оба ранкера согласны |

### Что узнала

- **Брифовый sanity-query был «короткой паразрафой»** — на полном корпусе токены «телефон/сколом» из «телефон со сколом» не пересекаются с чанками 2831 (нет лексической связи без стемминга). Это **не баг моего BM25**, а свойство query × corpus. Probe изначально работал на полном golden-запросе (123 символа) — там много токенов, которые матчатся («приехал», «продавец», «деньги»). Урок: при копировании sanity-кейсов из probe в production-тест нужно мирорить **ровно ту query**, которую probe использовал.
- **Title duplication в корпусе важна для retrieval-латчинга** — без `f"{title}\n{document}"` 2831 падает с #1 на #3 на g020. Это эффективный «бесплатный» upweighting заголовков, на 4288 чанков добавляет ~0.03s к build time. Почему работает: BM25 IDF × TF — заголовки обычно содержат самые informative термины статьи; их повторение увеличивает TF и поэтому score.
- **Lifespan-вариант (build-from-chroma в RAM) проще, чем persistent pickle.** На 4288 чанков 500ms cold start приемлем. Альтернатива (pickle на volume или GitHub release как у Chroma) добавила бы ещё одно место для рассинхрона между retrieval-источниками. Принимаем cold start +500ms как цену за consistency.
- **`rank-bm25 0.2.2` plug-and-play** — никаких side-effects на CPython, никакого native build. Это контраст с `sentence-transformers` (Sprint 5 Блок 3), который тянул torch и на shared Railway CPU давал +8500ms на forward pass. BM25 — алгоритм, не нейросеть; на 4288 чанков время поиска должно быть <50ms (точный замер в Блоке 5).

## Изменение #2 — Hybrid retrieval (RRF)
_(заполнится после Блока 2)_

## Изменение #3 — Eval ablation
_(заполнится после Блока 3)_

## Изменение #4 — Анализ + решение по deploy
_(заполнится после Блока 4)_

## Изменение #5 — Деплой на прод
_(заполнится после Блока 5)_

## Финальная сводка
_(заполнится после Блока 6)_
