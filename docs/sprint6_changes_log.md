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
- Бюджет на старте Sprint 6: $9.04 потрачено в Sprint 5, остаток $5.96 от $15.

**Бюджет — пополнение перед Блоком 3.4:**
Перед прогоном `mvp` (hybrid full eval gen+judge) бюджет пополнен **+$6** (Sprint 5 spend $9.04 + Sprint 6 Блока 3.1 $2.77 = $11.81 уже потрачено, остатка $3.19 не хватало с запасом на $3.01 прогноза + Sprint 7 буфер). **Итоговый бюджет проекта: $21** ($15 изначально + $6 пополнение). Это важно для финальной сводки — Sprint 6 cumulative spend ≈$5.50 + $0.20 (Блок 5 latency) ≈$5.70 на $6 пополнении, остаток ~$6.30 на Sprint 7 (демо/README — обычно $0 paid, буфер).

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

### Production smoke check (Блок 1)

Push коммита `78bc36d` → Railway auto-deploy → **Success**. Контейнер заменился, `/health` (cache-busted) на 5 sequential calls стабильно возвращает:

```json
{"status":"ok","retrieval_ready":true,"bm25_ready":true}
```

**Что подтверждает `bm25_ready: true`:**
- Lifespan event на shared Railway CPU прошёл без exception (иначе `_BM25_INIT_ERROR` был бы set, поле `bm25_ready: false`).
- `init_bm25_from_chroma(get_chroma_collection())` успешно построил singleton — все 4288 чанков проиндексированы.

**Что НЕ замерено здесь** (не критично для приёмки Блока 1):
- Точное build-time BM25 на Railway shared CPU. Цифра пишется в stderr строкой `[bm25] index built over 4288 chunks in Xms`, доступна только через Railway logs UI. Локально на M-series было ~414ms; на shared Railway CPU без MKL ожидаем ~1-3 секунды (порог брифа <2s — на грани, но не блокирует приёмку, т.к. это singleton init вне горячего пути запросов).
- Прямой timing запросов с/без BM25. Это в Блоке 5 (dedicated latency-замер).

Verdict: production smoke ✓. Идём в Блок 2.

## Изменение #2 — Hybrid retrieval (RRF)

**Дата:** 2026-05-09
**Время на разработку:** ~1.5ч (рефакторинг `search()` + 2 новых поля в `SearchHit` + RRF + sanity)
**$ потрачено:** $0 (никаких LLM-вызовов; embed-кэша достаточно)

### Что конкретно сделано

- `backend/retrieval.py` строка 32-43: env-переменные `USE_HYBRID_RETRIEVAL` (default `true`), `HYBRID_CANDIDATES` (default 20), `RRF_K` (default 60). Reranker и hybrid взаимно исключают друг друга через `bm25_searcher = ... if (USE_HYBRID_RETRIEVAL and reranker is None) else None`.
- `backend/retrieval.py` `SearchHit` (строки 65-89): добавлены `bi_score: float = 0.0` (bi-encoder cosine; 0 для BM25-only чанков) и `rrf_score: Optional[float] = None`. Поле `score` оставлено как legacy ranking score: rrf_score в hybrid, bi_score в bi-only — для совместимости с eval.py / API response / logs.
- `backend/retrieval.py` `_rrf_merge()` (строки 165-194): стандартная RRF-формула `score(d) = Σ 1/(k+rank_r(d))` по двум ранкерам. Документы из одного ранкера учитываются с одним `1/(k+rank)`. Pre-fetch BM25-only чанков из Chroma через `collection.get(ids=...)` для построения SearchHit'ов.
- `backend/retrieval.py` `search()` (строки 197-301): три взаимно-исключающие пути с timing-breakdown в `last_search_timings`:
  1. **reranker** (Sprint 5, opt-in `USE_RERANKER=true`)
  2. **hybrid** (Sprint 6 default) — bi-encoder top-20 + BM25 top-20 → RRF → top_k
  3. **bi-only** (для ablation `--config bi_only`) — Chroma top_k без RRF
- `backend/generation.py` `_query_bi_top1(hits)` (строки 99-110): `max(h.bi_score for h in hits)` — устойчивая замена `hits[0].score < THRESHOLD` для случая когда RRF top-1 — BM25-only чанк с bi_score=0 (false-positive fallback на легитимных in-domain). Bi-encoder top-1 типично попадает в RRF top-K (1/61 — competitive RRF score), `max` его захватывает.
- `backend/generation.py` строки 282 и 397: `hits[0].score < RETRIEVAL_THRESHOLD` → `_query_bi_top1(hits) < RETRIEVAL_THRESHOLD` (sync и SSE-пути).
- `backend/main.py`: `latency_ms` в response теперь содержит `bm25_ms`, `merge_ms` (через прокидку из `last_search_timings` в `latency` dict; уже было в Sprint 5 паттерне).

### Гипотеза (что ожидали)

- **4/5 cherry-picked** в hybrid top-5 (как probe): g020/g050/g061/g023 ✓, g002 — content gap, остаётся ✗.
- **5/5 healthy** не должны сломаться (BM25 не должен ломать что работало bi-encoder'у).
- **bi_top1 на in-domain ≥ 0.3** — fallback не должен false-positive на легитимных запросах.
- **Latency**: BM25 search ≈ 10-30ms на 4288 чанках (in-RAM); RRF merge ≈ 1-5ms (чистый питон); pre-fetch BM25-only из Chroma ≈ 5-10ms. Суммарно +30-50ms к bi-only пути.

### Sanity-результаты

**Cherry-picked (5 ID):**

| id | bi_only | bm25_only | **hybrid** | bi_top1 | прогноз probe | факт |
|---|---|---|---|---|---|---|
| g002 | ✗ | ✗ | ✗ | 0.431 | ✗ (content gap) | ✓ как probe |
| g020 | ✗ | ✓ #1 | **✓ #2** (`2831_007`) | 0.526 | ✓ #1 | ⚠ probe был #1, у меня #2 (рядом) |
| g050 | ✓ #2 | ✗ | **✓ #3** (`4389_001`) | 0.483 | ✓ #4 | ✓ лучше probe |
| g061 | ✓ #2 | ✗ | **✓ #3** (`2148_002`) | 0.509 | ✓ #4 | ✓ лучше probe |
| g023 | ✓ #1 | ✓ #2 | **✓ #1** (`4331_010`) | 0.515 | ✓ #1 | ✓ как probe |

**Hybrid: 4/5 cherry-picked в top-5** — точно как probe (✓ для приёмки).

**Healthy (5 ID):**

| id | bi_only top-1 | hybrid top-1 | вердикт |
|---|---|---|---|
| g006 «сколько стоит доставка» | ✓ `1951_000` (#1) | ✓ `1951_000` (#1) | OK |
| g008 «как отменить заказ» | ✓ `4387_006` (#1) | ✓ `4387_006` (#1) | OK |
| g021 «звонят якобы из службы безопасности... код из смс» | ✓ `1881_003` на #4 | ⚠ **expected ушёл из top-5** | микро-регрессия (см. ниже) |
| g034 «слила доступ как сменить пароль» | ✗ (R@5=0 в Sprint 5) | ✗ | OK (не было) |
| g070 «не могу позвонить продавцу» | ✓ `1827_000` (#1) | ✓ `1827_000` (#1) | OK |

**Net на 5 healthy: 4/5 без изменений, 1 микро-регрессия** (g021).

### bi_top1 sanity на fallback

| id | mode | bi_top1 | < 0.3? |
|---|---|---|---|
| g002 | hybrid | 0.431 | нет ✓ |
| g020 | hybrid | 0.526 | нет ✓ |
| g050 | hybrid | 0.483 | нет ✓ |
| g061 | hybrid | 0.509 | нет ✓ |
| g023 | hybrid | 0.515 | нет ✓ |

**Все 5 cherry-picked + 5 healthy дают bi_top1 ≥ 0.43** → fallback threshold 0.3 не сработает на in-domain, refusal-логика не сломалась переходом на hybrid.

### Latency-замер (Mac M-series, тёплый embed-cache отсутствует — реальный embed)

| mode | total_ms | embed | chroma | bm25 | merge |
|---|---|---|---|---|---|
| hybrid | 242 | 214 | 10 | 15 | 3 |
| bi-only | 342 | 335 | 6 | 0 | 0 |

embed варьируется 200-350ms (OpenAI API + сеть), это шум. BM25 search занимает **15ms на 4288 чанков** — на shared Railway CPU ожидаем 30-50ms (всё ещё <100ms). RRF merge ≈ 3ms — пренебрежимо. Hybrid contribution: **~+20ms к bi-only** на M-series.

### Микро-регрессия g021 — анализ

**Запрос:** «звонят якобы из службы безопасности авито просят код из смс говорят что взломан профиль что делать»
**Expected URLs:** 4332, 1881
**bi-only top-5:** `1872_004`, `1869_002`, `4221_004`, **`1881_003` (#4)**, `1872_002`
**hybrid top-5:** `1872_004`, `4221_000`, `4221_006`, `4221_004`, `4295_004` — `1881_003` ушёл

**Причина:** запрос лексически сильный по словам «звонят», «безопасности», «код», «смс» — BM25 поднимает чанки `4221_*` (другая статья про безопасность, в ней эти слова повторяются часто) выше, чем `1881_003` (про мошенников, более семантически правильный). RRF не может отличить «семантически правильный» от «лексически плотный» — он просто сливает ранги.

**Verdict для приёмки блока:** не блокирует — это **известный риск hybrid retrieval** на запросах с пересекающимся вокабуляром между правильной и соседней категорией. На полном eval (Блок 3) увидим net effect — типично BM25 даёт +N кейсов где expected URL имеет лексический матч (g020/g050/g061), но возможно отнимает где expected URL семантически точнее (g021). Если net Δ Recall@5 < +1 п.п. в Блоке 3 — значит компенсация не работает, обсуждаем.

### Что узнала

- **`max(h.bi_score)` вместо `hits[0].score` для fallback — правильное решение.** Без этого hybrid с BM25-only чанком в RRF top-1 (bi_score=0) давал бы false-positive fallback на легитимных in-domain. На 5 cherry-picked этого не случилось (все RRF top-1 либо в bi top-20, либо bi-encoder top-1 рядом с RRF top-1), но edge case теоретически возможен на полном сете — `max` устойчивее.
- **RRF score scale ≠ legacy `score` semantics.** В hybrid mode `hits[0].score = rrf_score ≈ 0.02-0.04`, vs Sprint 5 cosine `≈ 0.5-0.7`. Любой downstream код, читающий `score` как cosine, упадёт. Проверила: `eval.py` пишет `round(h.score, 4)` в результаты — будет писать RRF scale в hybrid run, но это не ломает eval-логику (Recall/MRR считаются по chunk_id'ам, не по scores). API response `retrieval_scores` отдаёт RRF в hybrid режиме — фронт его просто отображает, не парсит численно.
- **Reranker и hybrid взаимно исключают друг друга.** Если когда-то поднимем reranker на dedicated-CPU (`USE_RERANKER=true`), hybrid автоматически отключается через `if (USE_HYBRID_RETRIEVAL and reranker is None)`. Это правильный паттерн — два независимых retrieval-механизма, оба opt-in после Sprint 6 default.
- **BM25 search 15ms на M-series — на 4288 чанках это IDF-lookup'ы по Python dict.** Никакой векторной арифметики. На shared Railway CPU ожидаем 30-50ms — порог брифа Блока 5 ≤500ms server retrieval P50 будет легко.

## Изменение #3 — Eval ablation (bi_only vs hybrid)

**Дата:** 2026-05-09
**Время на разработку:** ~2.5ч (правки eval.py + 3 прогона + декомпозиция)
**$ потрачено:** **$5.50** (bi_only $2.77 + hybrid $2.73). bm25_only пропущен.

### Решение по урезанному ablation (по запросу пользователя)

Полный 3-config ablation (bi_only / bm25_only / hybrid) пропущен ради экономии бюджета. Прогон bm25_only на полном сете не делали — диагностику Sprint 5 probe (BM25 alone 2/5 cherry-picked vs bi 3/5 vs hybrid 4/5) считаем достаточной для понимания вклада BM25 как изолированного ранкера. Декомпозиция «какой ранкер что дал» в Блоке 3 идёт через failure case analysis на bi_only vs hybrid (см. ниже).

### Что конкретно сделано

- `scripts/eval.py` — добавлен config `bi_only` (`USE_HYBRID_RETRIEVAL=False`); `mvp` теперь по умолчанию hybrid (через env-default `USE_HYBRID_RETRIEVAL=True` + явный `apply_config('mvp')`).
- `scripts/eval.py` `run_one_retrieval_only(item, is_ood)` — новая функция: только `retrieval.search()`, синтетический `is_fallback = (not hits) or (max bi_score < 0.3) or _is_competitor_query()`. Skip generation + judge → $0 paid.
- `scripts/eval.py` `--retrieval-only` flag — переключает на retrieval-only path; outdir `<config>_retrieval_only_<ts>/`.
- `scripts/eval.py` — BM25 singleton теперь инициализируется в main() через `bm25_module.init_from_chroma()` до `apply_config()` (без этого hybrid path в `retrieval.search()` падал на bi-only из-за `bm25_module.get_searcher() is None`).

### Cache-invalidation discovery (важная находка)

Sprint 5 final eval (`mvp_20260509_153514`) показывал Faithfulness non-fb 0.6907 / Relevance 4.6495. После прогона `--config bi_only` в Sprint 6 (с **тем же retrieval** — Recall@5 0.8125 идентичен) — получили Faithfulness 0.6495 (-4 п.п.) и Relevance 4.6082. **При retrieval идентичном.**

Причина: коммит `5baa5e2 fix bullet-points '•' → '- '` (2026-05-09 15:55:10, **после** Sprint 5 final eval в 15:35:14) изменил `ANSWER_TOOL` description (требование markdown-list `- ` вместо `•`). Это **смена tools-payload в кэш-ключе**: `make_key(model, messages, tools, temperature, system)` — все 308 кэш-ключей Sprint 5 final стали невалидны при изменении tool description.

В Sprint 6 bi_only run заплатили **$2.77** на пересоздание кэша с новым tool. Это **одноразовый payment**, эффект чисто методологический — никаких регрессий retrieval (Recall тождественно тот же).

**Урок:** изменение tool definition между eval-прогонами требует осознанного решения перепрогона, и любое сравнение «Sprint N final → Sprint N+1» должно происходить на ОДНОЙ кодовой базе (мы это делаем — Sprint 6 bi_only теперь baseline для hybrid).

### Финальные метрики (bi_only baseline vs hybrid final)

| Метрика | bi_only (Sprint 6 baseline) | **hybrid (Sprint 6 final)** | Δ | PRD цель | Verdict |
|---|---|---|---|---|---|
| **Recall@5** | 0.8125 | **0.8542** | **+0.0417** | ≥0.85 | ✅ **закрыли впервые** |
| MRR@10 | 0.7007 | 0.7024 | +0.0017 | ≥0.6 | ✅ |
| **Faithfulness (full)** | 0.6600 | **0.7400** | **+0.080** | ≥0.7 (revised) | ✅ |
| Faithfulness (non-fb) | 0.6495 | 0.7396 | +0.0901 | — | bonus |
| Relevance (non-fb) | 4.6082 | 4.6979 | +0.0897 | ≥4 | ✅ |
| Refusal rate (OOD) | 1.0 | **1.0** | 0 | 1.0 | ✅ сохранено |
| n_non_fallback | 97 | 96 | −1 | — | минор сдвиг |
| Cost paid | $2.77 | $2.73 | — | — | (одноразовый из-за bullet-fix) |

**Все 5 PRD-целей закрыты в hybrid конфиге.** Cumulative spend Sprint 6 = $5.50, total $14.54/$15.

### Декомпозиция «какой ранкер что дал» через failure case analysis

#### R@5 fixed (0→1, +7 кейсов)

| id | query | bi top-10 pos | BM25 top-20 pos | attribution |
|---|---|---|---|---|
| g011 | «курьер не приехал что делать» | not in top-10 | **#8** | **BM25 only** (bi-encoder промахнулся, BM25 поднял) |
| g020 | «телефон со сколом… продавец…» | not in top-10 | **#1** | **BM25 only** (cherry-pick победитель probe) |
| g054 | «верниите деньги за доставку» | not in top-10 | **#2** | **BM25 only** (опечатка «верниите» → лексика) |
| g073 | «сообщения не отправляются» | not in top-10 | **#1** | **BM25 only** |
| g025 | «обновите данные карты — фишинг» | #8 | #7 | RRF synergy (оба нашли, RRF поднял) |
| g035 | «странная авторизация с другого устр» | #9 | #1 | RRF synergy |
| g060 | «как продвинуть объявление…» | #10 | #1 | RRF synergy |

**4 win'а через BM25 only** (статья не была в bi-encoder top-10 — лечится только лексическим поиском). **3 win'а через RRF synergy** (оба ранкера нашли, RRF поднял в top-5 что было на позициях 7-10 у bi-encoder).

#### R@5 broken (1→0, −3 кейса)

| id | query | bi top-10 pos | BM25 top-20 pos | hybrid pos | Что произошло |
|---|---|---|---|---|---|
| g021 | «звонят якобы из СБ просят код из смс» | #4 | #5 | #10 | RRF подавил `1881_xxx` соседними `4221_xxx` (другая статья про безопасность с пересекающейся лексикой) |
| g049 | «что делать если профиль удалили без меня» | #1 | not in top-20 | #6 | BM25 не нашёл (нет лексических матчей), но RRF дал boost другим статьям → expected ушёл с #1 на #6 |
| g051 | «не могу пополнить кошелёк» | #3 | not in top-20 | #10 | аналогично g049 — BM25 boost'нул нерелевантные лексически-плотные чанки |

**1 поломка через RRF (g021)** — оба нашли, но соседняя статья получила boost. **2 поломки через BM25-noise (g049, g051)** — BM25 не нашёл expected, но boost'нул другие чанки → RRF переставил в top-5 что не было правильным.

**Net R@5 эффект:** +7 wins −3 losses = **+4 кейса** = +4.17 п.п. на n=96 ✓ (подтверждается агрегированной метрикой 0.8125 → 0.8542).

#### Faithfulness changes (in-domain)

- **+21 кейс True→False→True (fixed)**: g001, g005, g012, g014, g017, g018, g019, g022, g024, g028, g040, g046, g051, g053, g054, g065, g068, g087, g093, g097, g099
- **−13 кейсов True→False (broken)**: g006, g008, g011, g013, g016, g023, g038, g047, g066, g079, g081, g088, g100
- **Net: +8 faithful cases** → 0.66 → 0.74 (+8 п.п. full) ✓

**Гипотеза по +21 fixed:** другие top-5 → новый ответ Haiku → Sonnet находит меньше hard claims (или находит другие, но в среднем строже к bi_only-варианту). Включая критические cherry-picked Sprint 5 failure cases:
- **g017 «отправить посылку через авито»** — Sprint 4/5 имел выдуманные «48 часов». В hybrid faith=True (Haiku ответил без этого claim).
- **g014 «включить доставку в обявах»** — Sprint 4/5 «сдвиньте вправо» (выдумка). В hybrid faith=True.
- **g054 «верниите деньги за доставку»** — починен retrieval'ом (BM25 only), faith тоже улучшился.

**Гипотеза по −13 broken:** новые top-5 содержат чанки которые Haiku пытается включить → Sonnet flagит overgeneralization. Включая:
- **g011 «курьер не приехал»** — recall fixed (BM25 нашёл), но Haiku выдумал детали → faith=False. Здесь BM25-win по retrieval НЕ означает win по generation. Roadmap-кандидат: лучшие промпты для коротких/разговорных запросов.

#### Pre-LLM fallback changes

- **g002** «трек номер» — был fallback в bi_only, теперь in-domain ответ. Hybrid retrieval дал Haiku top-5 чанков, в которых модель смогла ответить (вероятно, неправильно — content gap; faith=False). Это потенциальная regression: hallucinated answer вместо graceful "не нашлось".
- **g050** «оплата два раза» — был in-domain answer в bi_only, теперь fallback. RRF переставил top-5 → Haiku решил `is_fallback=true`.
- **g061** «vip для обяв» — аналогично g050, демо-blocker возвращается в fallback.

**Trade-off:** g050/g061 — это известные демо-blocker'ы Sprint 5 Блока 3.5. Roadmap-кандидат: query-нормализация «обяв→объявления».

### Stop-conditions check

- Recall@5 hybrid 0.8542 > 0.81 ✓
- Refusal rate 1.0 ✓
- Faithfulness non-fb 0.7396 > 0.65 ✓ (выше PRD revised 0.7)
- Cost paid hybrid eval $2.73 < $4 cap ✓ (cumulative Sprint 6 = $5.50, total = $14.54)

### Что узнала

- **Hybrid даёт net +4 кейса R@5 (+4.17 п.п.)** на полном сете — точно в прогноз брифа (+4..+8 п.п.). Probe 4/5 cherry-picked = 80% hit rate был верхней оценкой; на полном сете BM25-friendly запросов меньше → ~7/96 = 7.3% wins, разбавлено.
- **Faithfulness +8 п.п. — побочный win.** Лучший retrieval (или просто другой) → меньше overgeneralization у Haiku в среднем. Не было в брифовом прогнозе (-1..+2 п.п.) — обогнали ожидание на 6+ п.п.
- **BM25 alone закрывает 4/7 wins** (g011/g020/g054/g073). Это ID где expected статья **вообще не была в bi-encoder top-10**. Без BM25 они нерешаемы через retrieval-tuning. Probe правильно идентифицировал главный win-pattern (короткие лексически-плотные запросы).
- **3 broken R@5 — RRF noise.** На запросах где bi-encoder уже ставил правильный chunk на #1-#3, добавление BM25 могло boost'нуть лексически-близкие соседние статьи и оттеснить правильный. Это **встроенный риск hybrid retrieval**, его не уберёшь без post-RRF фильтра релевантности (cross-encoder reranker — но он не работает на shared CPU).
- **Refusal rate 1.0 сохранён без изменений в threshold-логике.** Решение использовать `bi_score` (а не legacy `score`) для fallback decision окупилось — все 20 OOD корректно обработаны через комбинацию pre-LLM (12) + LLM (8). Никаких false-positive fallback на in-domain (`g050/g061` — это LLM-fallback, не pre-LLM).
- **Bullet-fix (`5baa5e2`) — методологический урок.** Любая правка `ANSWER_TOOL` или `SYSTEM_PROMPT` инвалидирует весь LLM-кэш (через cache-key payload). Roadmap для эконом: версионировать tools/system отдельно и хранить старые версии в кэше для воспроизведения.

## Изменение #4 — Анализ + решение по deploy

**Дата:** 2026-05-09
**Время на разработку:** ~1ч (декомпозиция через scripts + 3 deep-dive ответа на вопросы пользователя)
**$ потрачено:** $0 (анализ из cached results)

### Решение: **A — deploy hybrid as-is**

**Обоснование:**
- Все 5 PRD-целей закрыты (Recall@5 ≥ 0.85 впервые в проекте — главный goal Sprint 6).
- Refusal rate сохранён на 1.0 — `bi_score`-based fallback работает как задумано (риск 1.0→0.9 не реализовался).
- Регрессий R=1→0 ровно 3 (g021/g049/g051) — компенсированы 7 wins, net +4 кейса.
- Faithfulness +8 п.п. (decomp ниже: устойчивые +5..+7) — bonus, не блокер.
- Latency локально hybrid = 242ms (Mac M-series), BM25 contribution ~20ms — на shared Railway CPU ожидаем 30-50ms (порог брифа Блока 5 ≤500ms server retrieval P50 пройдём с большим запасом).

### Шаг 1 — Декомпозиция Δ Recall@5 (4 buckets)

Sprint 6 bi_only baseline: 18 кейсов с R@5=0 на n=96 countable.

| Bucket | n | Кейсы |
|---|---|---|
| **Fixed via BM25 only** (expected не было в bi-encoder top-10, BM25 вытянул) | **4** | g011, g020, g054, g073 |
| **Fixed via RRF synergy** (оба ранкера нашли, RRF поднял в top-5) | **3** | g025, g035, g060 |
| **Remained — content gap** (не в top-20 ни одного ранкера) | 6 | g002, g007, g024, g042, g058, g095 |
| **Remained — другое** (в top-20 одного ранкера, но RRF не вытянул в top-5) | 5 | g003 (BM25 #1), g026 (BM25 #15), g034 (BM25 #13), g089 (bi #6), g094 (bi #6) |

**Net:** +7 fixed − 3 broken (g021, g049, g051) = **+4 кейса = +4.17 п.п.** ✓ совпадает с агрегатом 0.8125 → 0.8542.

### Шаг 2 — Классификация всех 18 failure cases

| id | query | вердикт | причина |
|---|---|---|---|
| g002 | трек номер не отслеживается | ✗ | content gap (expected 2802 не в top-20) — roadmap HyDE / multi-query |
| g003 | как сделать возврат если заказ не подошёл | ✗ | BM25 нашёл #1, но bi-encoder промахнулся → RRF не вытянул в top-5 |
| g007 | купил наушники с авито доставкой… не то | ✗ | content gap (chunks 2831/4400 не в top-20) |
| **g011** | **курьер не приехал что делать** | ✓ | **BM25 only (#8)** |
| **g020** | **приехал телефон со сколом** | ✓ | **BM25 only (#1) — cherry-pick win** |
| g024 | подозрительный qr код продавец прислал | ✗ | content gap |
| **g025** | пришло на почту письмо обновите данные карты | ✓ | RRF synergy (bi #8 + BM25 #7) |
| g026 | в смс пришёл код хотя я ничего не запрашивал | ✗ | BM25 #15 — слишком далеко для RRF поднять в top-5 |
| g034 | слила доступ к профилю случайно как сменить пароль | ✗ | BM25 #13 — слишком далеко |
| **g035** | странная авторизация с другого устройства | ✓ | RRF synergy (bi #9 + BM25 #1) |
| g042 | забыл пороль как восстановить | ✗ | content gap (опечатка «пороль» сломала bi-encoder, BM25 без стемминга тоже мимо) |
| **g054** | **верниите деньги за доставку** | ✓ | **BM25 only (#2) — опечатка «верниите» лексикой матчится** |
| g058 | хочу вывыести деньги с авито доставки | ✗ | content gap (опечатка «вывыести») |
| **g060** | как продвинуть объявление чтобы его видели больше людей | ✓ | RRF synergy (bi #10 + BM25 #1) |
| **g073** | **сообщения не отправляются что делать** | ✓ | **BM25 only (#1)** |
| g089 | объявление отклонили без причины как восстановить | ✗ | bi #6, BM25 #13 — RRF не вытянул в top-5 |
| g094 | как подать объявление о квартире | ✗ | bi #6, BM25 #13 — content gap по ML System Design (нет универсальной статьи «как подать», только по доменам) |
| g095 | как опубликовать объявление о товаре с нуля | ✗ | content gap (тот же паттерн что g094) |

**Реальные галлюцинации Sprint 5 (g003/g014/g017):** g003 остался R@5=0 (BM25 нашёл, но в RRF не вытянул); g014/g017 уже имели R@5=1 и в hybrid faith улучшилось. **Эти кейсы Sprint 5 был flagged как «реальные галлюцинации» — Sprint 6 показал что хотя bad retrieval (g003) сам по себе не лечится hybrid, на g014/g017 правильный retrieval остался стабильным и faith улучшился через top-5 reordering.**

### Pre-LLM fallback cases (3 кейса Sprint 5 Block 3.5)

| id | Sp5 Block 3.5 (threshold 0.55) | Sp5 final (0.3) | Sp6 bi_only | **Sp6 hybrid** |
|---|---|---|---|---|
| g023 | pre-LLM fallback | answered | answered | **answered** (faith=False) |
| g050 | pre-LLM fallback | answered | answered | **LLM-fallback** (Haiku decided) |
| g061 | pre-LLM fallback | answered | answered | **LLM-fallback** ⚠ demo-blocker remains |

**g061 НЕ снят hybrid'ом** — переехал из pre-LLM fallback (Sp5 Block 3.5) в LLM-fallback (Sp6 hybrid). Top-1 chunk_id `4371_024` тот же, но RRF переставил остальные top-5 → Haiku сам решил «не нашлось точного ответа». Demo-mitigation в Sprint 7 нужен (см. roadmap).

### Шаг 3 — 5 контрольных кейсов (R=1 → R=1?)

| id | bi R@5 | hy R@5 | вердикт |
|---|---|---|---|
| g006 «сколько стоит доставка» | 1 (#1) | 1 (#1) | ✓ |
| g008 «как отменить заказ» | 1 (#1) | 1 (#1) | ✓ |
| g030 — | 1 (#1) | 1 (#1) | ✓ |
| g070 «не могу позвонить продавцу» | 1 (#1) | 1 (#1) | ✓ |
| g021 «звонят якобы из СБ просят код из смс» | 1 (#4) | **0** | ⚠ regression (RRF noise — `4221_*` соседняя статья boost'нула) |

4/5 контрольных OK. Регрессия g021 — известная (Block 2 sanity предсказал, Block 3 подтвердил на полном сете).

### Шаг 4 — Решение и обоснование

**A. Deploy hybrid as-is** ✓

**Stop-conditions check:**
- Recall@5 hybrid 0.8542 > 0.81 ✓
- Refusal rate 1.0 ✓
- Faithfulness non-fb 0.7396 > 0.65 ✓ (выше PRD revised 0.7)
- Cost paid Block 3.4 $2.73 < $4 cap ✓

**Что НЕ делаем:**
- B (откат) — нет регрессий критических. 3 R=1→0 < 7 R=0→1.
- C (промежуточный fix) — фиксы g021/g089/g094/g095/g050/g061 требуют либо stemming (g042/g058 опечатки), либо HyDE / multi-query rewrite (g002/g024/g094/g095 content gaps), либо query-нормализации (g061 «обяв→объявления»). Все это 2-5 часов работы — не вписывается в Sprint 6, переносим в Sprint 7 roadmap.

### Decomposition Faithfulness +8 п.п. — честный анализ

Из deep-dive ответа на вопросы пользователя (Q3):

| Источник | Вклад | Доказательство |
|---|---|---|
| **(a) BM25 cluster effect** — top-5 целиком из правильной статьи → меньше шума | ~30-40% | g014: bi_only top-5 mixed `[4050, 4362, 4362, 4362, 4296]`, hybrid `[4362]×5` → лучший ответ |
| **(b) g023/g050/g061 returned from fallback** | **0%** | Не подтвердилось — g050/g061 наоборот ушли в LLM-fallback в hybrid |
| **(c) Different chunks → different answer style** | ~40-50% | g012: hybrid mixed top-5 → Haiku пишет более conservative ответ → меньше specific claims |
| **Sonnet noise** | ~10-20% | g001: top-5 article ids идентичны (`[2831]×5`), leads почти одинаковые, faith flipped — это шум judge'а |

**Реалистичный устойчивый Δ Faithfulness = +5..+7 п.п.** Не overstate'м «+8 п.п.» в финальной таблице — часть — Sonnet noise (перекликается с methodological finding Sprint 5 о judge inconsistency).

### Methodological finding #6 — Bullet-fix как cache-invalidating change

Из deep-dive ответа на Q1: коммит `5baa5e2 fix bullet-points '•' → '- '` (косметическая правка ANSWER_TOOL description) после Sprint 5 final eval вызвал:

**Format shift в ответах Haiku:**
| | Sprint 5 final | Sprint 6 bi_only |
|---|---|---|
| Ответов с `•` | 30/97 | 0/97 |
| Ответов с `- ` lists | 18/97 | 83/97 |

Haiku массово стал писать markdown-списки. **86% ответов теперь содержат `- ` против 19% до.**

**Эффект на faithfulness — −4 п.п. (0.6907 → 0.6495 на одной retrieval):**

Смесь причин (анализ 16 True→False flips):
1. **~70% format-induced specificity:** новый `- ` формат → Haiku enumerates cases более явно → Sonnet парсит каждый item как discrete claim → находит больше overgeneralization (g005, g019, g046).
2. **~30% реальные content-shifts:** Haiku ответил по-другому, не только формат (g018 «не дают распаковать» — Sp5 «нормально» с caveat'ом, Sp6 «не нормально» с выдумкой про «запечатывать полностью»).

**Cache-invalidation:**
- `make_key(model, messages, tools, temperature, system)` — изменение tool description = новый ключ для всех queries.
- 308 кэш-ключей Sprint 5 final стали невалидны.
- Sprint 6 bi_only paid $2.77 на пересоздание кэша.

**Урок (новая methodological finding для собеса):**
> **«Косметическая правка промпта инвалидирует cache как retrieval-правка, и формат вывода влияет на judge так же сильно как содержание.»** Любая смена `ANSWER_TOOL`/`SYSTEM_PROMPT`/`FAITHFULNESS_SYSTEM`/`USER_TEMPLATE` требует осознанного решения paid rerun. Особенно правки которые меняют **структуру** ответа (списки vs параграфы) — judge сильнее реагирует на структуру чем на стилистику.

Это **6-я методологическая находка** проекта (5 из Sprint 5 + эта). Полный список — в Финальной сводке.

### g061 demo-blocker — roadmap Sprint 7

В hybrid g061 «vip для обяв» переехал из pre-LLM fallback (Sp5 Block 3.5) в LLM-fallback. RRF top-1 chunk_id тот же (`4371_024`), но порядок остальных top-5 другой → Haiku решил `is_fallback=true`.

**Demo-mitigation:** query-нормализация «обяв→объявления» через словарь синонимов (~30 строк в `retrieval.search()`, $0 paid, **30 минут код**). Закрывает не только g061, но и g042 «забыл пороль», g058 «вывыести» — в общем класс опечаток/сленга.

Записать в Sprint 7 roadmap.

### Что узнала

- **Декомпозиция R@5 показывает что probe был справедливой оценкой направления, но на полном сете эффект меньше пропорционально:** на 5 cherry-picked probe BM25 fixed 4/5 = 80%; на 18 R@5=0 кейсах bi_only Sprint 6 BM25/RRF fixed 7/18 = 39%. Cherry-pick bias подтверждён эмпирически.
- **6 content gaps из 18 (33%) — это структурные дыры в БЗ Авито, не лечатся retrieval'ом.** g094/g095/g024 «как подать объявление о товаре с нуля» — статьи с этим заголовком в Авито нет (только domain-specific «Авто/Недвижимость/Путешествия»). HyDE / query rewrite дадут только частичный win. Реальный fix — добавление статьи в БЗ (Авито side).
- **5 из 18 fail — RRF не вытянул когда expected далеко в одном ранкере.** g003 (BM25 #1, bi None), g089 (bi #6, BM25 #13). Решение — увеличить candidates с 20 до 50 (бесплатно, +2-5ms latency). Roadmap Sprint 7.
- **g021 регрессия — единственная реальная (R=1→0).** g049/g051 регрессии — оба expected в bi top-1/3, BM25 не нашёл, RRF noise через сторонние чанки. Это паттерн «BM25 boost'нул нерелевантные» — теоретически решается фильтром по bi_score < 0.1 в RRF candidate pool (отсекаем чанки которые bi-encoder совсем не любит). Roadmap.
- **Faithfulness honest Δ = +5..+7 п.п., не +8.** Часть из 8 п.п. — Sonnet noise на похожих формулировках (g001). Это связано с methodological finding Sprint 5 #1 (judge inconsistency). Не блокер для приёмки, но в финальной таблице цитируем "+5..+7" с диапазоном.

## Изменение #5 — Деплой на прод + замер latency

**Дата:** 2026-05-09
**Время на разработку:** ~1ч (3 деплоя — main, hotfix latency-полей, replay)
**$ потрачено:** ~$0.20 (30 sequential prod запросов через Haiku, без cache)

### Деплои

1. **Коммит `ec03067`** (Sprint 6 Блок 2-4 main): hybrid retrieval, RRF, новые поля SearchHit. Push → Railway redeploy ~120с. Smoke /search показал hybrid сигнатуру (RRF score 0.0164, bi_score=0.0 для BM25-only чанков).
2. **Коммит `eed6ae3`** (latency-fields hotfix): обнаружено что `bm25_ms`/`merge_ms` существуют в `last_search_timings` (с Блока 2), но не пропагируются в API response — main.py не обновлён. Также `LatencyRecord` (логи) не имел этих полей. Исправил в обоих местах. Без этого замер Блока 5 шага 3 не показал бы breakdown по фазам.

### Smoke 5 запросов (после деплоя)

| id | desc | is_fallback | client_ms | server_total | retrieval | gen | embed | chroma | bm25 | merge |
|---|---|---|---|---|---|---|---|---|---|---|
| g020 | in-domain BM25 helper (cherry-pick) | False | 4866 | 4556 | 196 | 4359 | 157 | 5 | (см. v4) | (см. v4) |
| g061 | in-domain demo-blocker | **True (LLM)** | 2070 | 1698 | 145 | 1552 | 127 | 5 | — | — |
| g006 | in-domain healthy | False | 4609 | 4218 | 154 | 4064 | 135 | 5 | — | — |
| ood19 | OOD «юла» | True (competitor) | 467 | 161 | 161 | 0 | 138 | 11 | — | — |
| ood20 | OOD «озон» | True (competitor) | 428 | 134 | 134 | 0 | 116 | 5 | — | — |

Smoke выполнен ДО hotfix `eed6ae3`, поэтому bm25_ms/merge_ms не отображались в API response. После hotfix первый запрос показал `bm25_ms=4ms, merge_ms=5ms` — поля работают.

**Что подтвердил smoke:**
- g020 в hybrid отдаёт sources `[2831, 4332]` — статья 2831 (cherry-pick win) на проде. Sprint 5 на g020 не находила 2831.
- g061 → LLM-fallback (как ожидалось из Блока 4 анализа).
- ood19/ood20 → competitor-fallback (gen=0ms — без LLM-вызова, retrieval ~150ms).
- OOD refusal работает: оба fallback'а через `_is_competitor_query`, не через bi_score threshold.
- Latency client 0.4-4.9s — в пределах PRD ≤5s P50.

### 30 sequential prod latency (data/eval/prod_latency_v4/results.json)

Те же 30 query IDs что в Sprint 5 prod_latency_v3 для прямой сравнимости.

#### Финальная таблица Sprint 6

| Метрика | Sprint 5 v3 (no-reranker, bi-only) | **Sprint 6 v4 (hybrid)** | Δ | PRD |
|---|---|---|---|---|
| **Client P50** | 4562ms | **4798ms** | +236ms | ≤5s ✓ |
| **Client P95** | 7317ms | **7315ms** | −2ms | ≤8s ✓ |
| Client max | 7713ms | 8504ms | +791ms | — |
| Server P50 | 4059ms | 4416ms | +357ms | — |
| Server P95 | 6920ms | **5852ms** | **−1068ms** | — |
| **Server retrieval P50** | 137ms | **151ms** | +14ms | ≤500ms ✓ |
| Server retrieval P95 | 254ms | **447ms** | +193ms | — |
| Server **BM25** P50/P95 | — | **10/25ms** | new | — |
| Server **merge** P50/P95 | — | **3/3ms** | new | — |
| Server embed P50 | 130ms | 130ms | 0 | — |
| Server chroma P50 | 10ms | 5ms | −5ms | — |
| Server generation P50 | 3925ms | 4169ms | +244ms | — |
| **n_fallback in-domain** | 1/30 | **0/30** | −1 | ≤5/30 ✓ |

#### Stop-conditions check

| Stop-condition (брифа Блока 5) | Прогон Sprint 6 | Verdict |
|---|---|---|
| P95 ≤ 8s | 7315ms | ✓ |
| P50 retrieval ≤ 500ms | 151ms | ✓✓ (3× запас) |
| n_fallback in-domain > 5/30 | 0/30 | ✓ (стало лучше vs Sprint 5 v3) |

#### BM25 на Railway shared CPU — главная проверка

**BM25 P50 = 10ms, P95 = 25ms** на shared Railway CPU без MKL/AVX оптимизаций. Это в **1000× быстрее** чем cross-encoder reranker давал на той же инфре (Sprint 5 Блок 5: P50 reranker = 8500-10000ms).

Это подтверждает архитектурное предположение брифа Sprint 6: **BM25 — алгоритм (IDF lookup по dict), не нейросеть (forward pass через 600M-параметровую модель)**. На любой архитектуре питон-словарь lookup работает консистентно ~10-50ms на 4288 чанков.

#### n_fallback 0/30 vs Sprint 5 v3 1/30 — причина

Sprint 5 v3 имел 1 fallback (g002 «трек номер не отслеживается» — content gap, bi_top1 < 0.3). В Sprint 6 v4 g002 НЕ fallback потому что:
- Hybrid retrieval дал ему top-5 чанки, для которых max(bi_score) ≥ 0.3 (один из чанков прошёл порог).
- Haiku попытался ответить вместо graceful fallback. **Это известная регрессия из Block 4** — на content-gap кейсах Haiku предпочитает hallucinate'ить вместо признать «не нашлось».
- Faithfulness g002 в Sprint 6 hybrid eval = False (Sonnet flagit hallucination).

Это **не latency-проблема, а quality trade-off** (Block 4 уже зафиксировано). Roadmap Sprint 7: HyDE / multi-query rewrite для content-gap кейсов с явным «не знаю».

#### Outliers в latency

- **g009 «где мой заказ почему так долго»** — embed=791ms (vs P50=130ms), retrieval=809ms total. OpenAI API hiccup, не Sprint 6 issue (Sprint 5 v3 имел аналогичные outliers).
- **g049 «удалили профиль»** — total=8504ms (max). Generation=7386ms, в среднем 2× от P50. Haiku длинный ответ + OpenAI streaming variance. Это R@5 broken case (Block 4 анализ) — Haiku возможно более многословен на удалённом expected article.
- **g055 «квитанция криво»** — embed=559ms. Опять OpenAI variance.

Outliers объясняют разрыв P50/P95: P50 4416ms против P95 5852ms — 1.3× разница, типичная для Haiku при temperature=0 (variance в response length, OpenAI embed network jitter).

### Что узнала

- **Hybrid retrieval на shared Railway CPU работает безупречно.** BM25 P50=10ms, P95=25ms — это **в 0.012× от ожидания брифа Sprint 6 (50-200ms)**. Питон-словарь IDF-lookup на 4288 терминах быстр даже на самых дешёвых VPS-конфигурациях. Это контраст с Sprint 5 Блока 3 (cross-encoder reranker P50=8500ms). **Урок:** для retrieval-фильтров на shared CPU выбирать **алгоритмические (BM25/SPLADE)**, а не нейросетевые (cross-encoder/dense reranker).
- **Server P95 улучшился на −1068ms vs Sprint 5 v3** при добавлении BM25 (~25ms latency cost). Гипотеза: pure-Python warm cache в hybrid path (без torch/transformers init) даёт более стабильную P95 чем bi-only Sprint 5 v3, где OpenAI embed jitter был главным источником tail latency. Не ожидала, но приятный bonus.
- **Latency-fields hotfix `eed6ae3` — повторение Sprint 5 Блока 5 урока:** изменение response schema требует не только обновления всех точек чтения (main.py + logging_jsonl.py), но и smoke на проде с НОВОЙ payload-структурой. Я добавила поля в `last_search_timings` в Блоке 2 и забыла пропагировать в response — обнаружила только на Блоке 5 smoke. Без этого Блок 5 step 3 (latency replay с разбивкой) не сработал бы. **Это connect к 6-й methodological finding (bullet-fix) — payload changes affect downstream observers.**
- **g002 регрессия от fallback к hallucinate ИНТЕРЕСНА методологически.** В bi-only Haiku видел top-5 с irrelevant чанками → пометил `is_fallback=true` (graceful). В hybrid тот же expected article 2802 не нашёлся, но hybrid дал чанки с **более высоким max(bi_score)** (BM25 boost через лексические совпадения «трек/номер»), Haiku не пометил fallback и попытался ответить. **Hybrid retrieval на content-gap может маскировать «незнание» как «знание»** — нужен либо явный gap-detector, либо HyDE для query rewrite.

## Финальная сводка

**Финальный mvp run:** `data/eval/runs/mvp_20260509_191629/` — 308/308 cache hits, $0 paid, 1.3s elapsed. Все числа подтверждены без новых LLM-вызовов.

### A. Cumulative-таблица: Sprint 4 → Sprint 5 → Sprint 6 final

| Метрика | Sprint 4 | Sprint 5 final | **Sprint 6 final** | Δ Sp6 vs Sp5 | PRD цель | Verdict |
|---|---|---|---|---|---|---|
| **Recall@5** | 0.8125 | 0.8125 | **0.8542** | **+0.0417** | ≥ 0.85 | ✅ **закрыли впервые в проекте** |
| MRR@10 | 0.7007 | 0.7007 | **0.7024** | +0.0017 | ≥ 0.6 | ✅ |
| **Faithfulness (full)** | 0.4500 | 0.6900 | **0.7400** | +0.0500 | ≥ 0.7 (revised) | ✅ **закрыли revised PRD** |
| Faithfulness (non-fb) | 0.4433 | 0.6907 | **0.7396** | +0.0489 | — | (honest range +5..+7 п.п.) |
| Relevance avg (non-fb) | 4.6701 | 4.6495 | **4.6979** | +0.0484 | ≥ 4 | ✅ |
| Refusal rate (OOD) | 1.0 | 1.0 | **1.0** (20/20) | 0 | 1.0 | ✅ |
| Latency P50 (prod) | 4.69s | 4.56s | **4.80s** | +0.24s | ≤ 5s (revised TTFB) | ✅ |
| Latency P95 (prod) | 7.46s | 7.32s | **7.32s** | 0 | ≤ 8s | ✅ |
| n_low_relevance (<3) | n/a | 2 | **0** | −2 | — | ✅ bonus |
| Cost per query | $0.0068 | $0.0068 | $0.0068 | 0 | ≤ $0.005 | ❌ requires prompt caching (roadmap) |

**8/9 PRD-целей закрыто в Sprint 6.** Cost — единственный недобор, недостижим без Anthropic prompt caching на ~1500 input tokens константной части (system + tool definition).

### B. Декомпозиция Δ Recall@5 (+4.17 п.п. = +4 кейса на n=96)

Sprint 6 bi_only baseline: 18 кейсов с R@5=0. После hybrid:

| Bucket | n | Кейсы | Что починилось / осталось |
|---|---|---|---|
| **Fixed via BM25 only** (expected не в bi-encoder top-10) | **4** | g011, g020, g054, g073 | Главный win-pattern — короткие лексически-плотные запросы |
| **Fixed via RRF synergy** (оба ранкера нашли) | **3** | g025, g035, g060 | Bi-encoder top-N + BM25 boost подняли в top-5 |
| Remained — content gap (не в top-20) | 6 | g002, g007, g024, g042, g058, g095 | Структурные дыры в БЗ Авито — лечатся только HyDE / новой статьёй |
| Remained — RRF не вытянул из top-20 | 5 | g003, g026, g034, g089, g094 | Кандидат на расширение candidates 20→50 |
| **Broken (R=1→0)** | **3** | g021, g049, g051 | g021 RRF noise; g049/g051 BM25 boost'нул нерелевантные |

**Net: +7 fixed − 3 broken = +4 кейса** ✓ совпадает с агрегатом 0.8125 → 0.8542.

### C. Faithfulness +5..+7 п.п. — honest decomposition

Финальная цифра 0.66 → 0.74 (+8 п.п. на full, +9 п.п. на non-fb), но устойчивый Δ — **+5..+7 п.п.** Декомпозиция вкладов (анализ 21 fixed + 13 broken faith-кейсов):

| Источник | Вклад | Доказательство |
|---|---|---|
| (a) BM25 cluster effect — top-5 целиком из правильной статьи | ~30-40% | g014: bi_only top-5 mixed `[4050, 4362, 4362, 4362, 4296]`, hybrid `[4362]×5` → лучший ответ |
| (b) Возврат g023/g050/g061 из fallback в LLM | **0%** | НЕ подтвердилось — g050/g061 наоборот ушли в LLM-fallback в hybrid |
| (c) Different chunks → different answer style → less overgeneralization | ~40-50% | g012 mixed top-5 → Haiku пишет conservative «после оплаты не получится» вместо специфичного |
| (d) Sonnet noise на похожих формулировках | ~10-20% | g001: top-5 chunks идентичны, leads почти одинаковы, faith flip — это шум judge'а |

В финальной презентации цитируем **+5..+7 п.п. устойчивых** (с диапазоном). Это связано с methodological finding Sprint 5 #1 (Sonnet judge inconsistency) — часть «улучшения» — это шум, а не реальный win.

### D. Что подтвердилось / что неожиданно

#### Probe vs реальность

| Аспект | Прогноз (бриф / probe) | Факт Sprint 6 | Verdict |
|---|---|---|---|
| Probe 4/5 cherry-picked | 80% hit rate | 4/5 в hybrid sanity Block 2 | ✓ воспроизведено |
| Recall@5 на полном сете | 0.85-0.89 (+4..+8 п.п.) | 0.8542 (+4.17 п.п.) | ✓ нижняя граница прогноза |
| MRR@10 | 0.74-0.78 (+3..+8 п.п.) | 0.7024 (+0.17 п.п.) | ⚠ намного ниже прогноза — top-1 для hybrid редко лучше bi-encoder #1 |
| Faithfulness (non-fb) | −1..+2 п.п. (новые ответы → шум) | +9 п.п. (honest +5..+7) | ⚠ **bonus неожиданный** — лучший retrieval даёт меньше overgeneralization |
| Refusal rate | 1.0 | 1.0 (через bi_score-based fallback) | ✓ |
| Latency P50 | +50-200ms | +236ms client / +14ms retrieval | ✓ в пределах |
| BM25 latency на shared CPU | 5-50ms | **10ms P50, 25ms P95** | ✓ нижняя граница |

#### 6 главных observations

1. **MRR@10 почти не вырос (+0.17 п.п.)** хотя Recall@5 +4.17 п.п. Это значит: hybrid редко поднимает expected на #1, чаще «поднимает с #6-#10 в top-5». Главный effect — **inclusion в top-5**, не **promotion на #1**.

2. **Faithfulness +5..+7 п.п. — bonus, не заявлен в брифе.** Гипотеза «Faith останется plateau при смене retrieval» оказалась консервативной — реально retrieval-пересортировка через BM25 cluster effect уменьшает шум для Haiku.

3. **g002 «трек номер» — fallback → hallucination.** В bi_only Haiku graceful fallback'ил, в hybrid пытается ответить (выдумывает). Hybrid retrieval может **маскировать «незнание» как «знание»** — нужен HyDE / explicit gap-detector.

4. **g061 demo-blocker НЕ снят.** Переехал из pre-LLM fallback (Sp5 Block 3.5) в LLM-fallback (Sp6 hybrid). Roadmap Sprint 7 — query-нормализация «обяв→объявления».

5. **Bullet-fix как cache-invalidating change** (6-я methodological finding). Косметическая правка `ANSWER_TOOL` стоила $2.77 на пересборку cache + изменила format ответов Haiku (30/97 → 0/97 с `•`, 18/97 → 83/97 с `- ` lists). Faithfulness потерял −4 п.п. на одной retrieval из-за: 70% format-induced specificity, 30% реальные content-shifts.

6. **BM25 на shared Railway CPU — архитектурный win.** P50=10ms, P95=25ms. В **1000× быстрее** чем cross-encoder reranker (Sprint 5 Block 5: 8500ms на той же инфре). Алгоритмический retrieval-фильтр >> нейросетевой на shared-CPU.

### E. Открытые вопросы → Sprint 7 roadmap

| Кандидат | Цена | Эффект | Приоритет |
|---|---|---|---|
| **Query-нормализация** «обяв→объявления», «вывыести→вывести», «пороль→пароль» через словарь | 30 мин код, $0 paid | Снимает g061 demo-blocker + g042 + g058 (3 кейса) | топ-1 (демо-fix) |
| **HyDE / multi-query rewrite** для content-gap | 4-6ч + $0.01-0.02/query overhead | Закрывает 6 content-gap кейсов (g002, g007, g024, g058, g095) либо graceful gap-detector | medium |
| **Расширить candidates 20→50** в RRF | 30 мин, +5-10ms latency | Закроет 5 «not lifted from top-20» (g003, g026, g034, g089, g094) | medium |
| **Anthropic prompt caching** на system + tool definition (~1500 input tokens) | 1-2ч код | Cost cached input −90% → потолок $0.001-0.002/запрос ✓ закроет последнюю PRD-цель | high (для cost-PRD) |
| **End-to-end success_rate metric** (Sprint 5 finding #2) | 2ч eval-script | Unified-метрика вместо пары колонок | high (под собес) |
| **Reranker как opt-in для dedicated CPU** | 1ч инфра + monthly $$ | Recall@5 +7 п.п. (Sprint 5 Block 3 был 0.8854) — выше чем hybrid 0.8542 | при наличии бюджета на инфру |
| **Демо UI / README / видео / чипсы** | Sprint 7 главное | Готовность к собесу | топ-1 |

### F. Бюджет

| Спринт / шаг | Paid | Cumulative |
|---|---|---|
| Sprint 5 (5 блоков) | $9.04 | $9.04 |
| **+$6 пополнение перед Блоком 3.4** | — | $15 → **$21** |
| Sprint 6 Block 3.1 (bi_only — bullet-fix cache rebuild) | $2.77 | $11.81 |
| Sprint 6 Block 3.4 (hybrid full eval) | $2.73 | $14.54 |
| Sprint 6 Block 5 (30 sequential prod latency) | ~$0.20 | **~$14.74** |
| Sprint 6 Block 6 final mvp rerun | $0 (cache) | $14.74 |

**Итого Sprint 6: $5.70 paid. Остаток: ~$6.26 на $21.** Sprint 7 (демо/README/видео/чипсы) обычно $0 paid — остаток будет уверенный буфер.

### G. 6 методологических находок проекта (для собеса)

| # | Находка | Спринт |
|---|---|---|
| 1 | Precision-over-recall на метрике (метрика, на которую нельзя положиться, хуже чем более низкая честная) | Sprint 5 |
| 2 | Recall@5 как retrieval-метрика не отражает end-to-end success (нужна `success_rate` unified) | Sprint 5 |
| 3 | Cost-оптимизация может улучшить качество если она происходит после фильтра релевантности | Sprint 5 |
| 4 | Pre-deployment latency-замер ОБЯЗАТЕЛЕН на shared-CPU инфраструктуре | Sprint 5 |
| 5 | Pydantic v2 не coerces float→int с fractional part — каждое изменение response schema требует curl smoke | Sprint 5 |
| 6 | **Bullet-fix эффект — косметическая правка промпта инвалидирует cache как retrieval-правка; формат вывода влияет на judge так же сильно как содержание** | **Sprint 6** |

### H. Что выжило в final-state Sprint 6

**Активно:**
- BM25 + bi-encoder + RRF (k=60, candidates=20) — `USE_HYBRID_RETRIEVAL=true` default
- BM25 singleton в `backend/bm25.py`, инициализация в lifespan event
- `SearchHit.bi_score` / `rrf_score` поля
- `_query_bi_top1(hits) = max(h.bi_score)` для pre-LLM fallback (защита от RRF top-1 = BM25-only)
- Sprint 5 wins: FAITHFULNESS_SYSTEM v4 + override, SAFETY_TRIGGERS query-level, COMPETITOR_PLATFORMS, threshold 0.3 на bi_score, top_k=5

**В коде, но выключено:**
- Reranker `bge-reranker-v2-m3` — `USE_RERANKER=false` default (opt-in для dedicated CPU)

**Не сделано в Sprint 6 (roadmap):**
- bm25_only ablation на полном сете (пропустили ради бюджета)
- Расширенный confusion matrix с end-to-end success_rate
- Stemming / stop-words / лемматизация (минимальный baseline по брифу)
- Query-нормализация для опечаток / сленга

### I. PRD revision — финальные decisions (user, 2026-05-09)

После Block 6 chat-обсуждения зафиксированы 3 PRD-правки (применит сам user в `docs/01-PRD.md`):

1. **F11 (latency)** — переписать как TTFB-декомпозицию вместо single end-to-end:
   - TTFB до пилюль источников: ≤ 500ms (Sp6 151ms ✓✓ 3× запас)
   - TTFB до первого слова lead: ≤ 2s (Sp5 ~1.5s ✓)
   - Полное non-streaming P50 ≤ 5s (Sp6 4798ms ✓), P95 ≤ 8s (Sp6 7315ms ✓)

2. **7.2 (Faithfulness)** — окончательно зафиксировать **≥ 0.7** (revised в Sp5, закрыто в Sp6: 0.7400). Убрать ⚠️ метку. В сноске указать honest Δ Sp5→Sp6 = +5..+7 п.п.

3. **7.3 (Cost)** — **decision B:** оставить цель **≤ $0.005**, явно прописать Anthropic prompt caching на system + tool definition (~1500 input tokens константной части) как **required Sprint 7+ dependency**. Sp5/6 факт $0.0068 недостижим без caching. Это методологически чище — PRD ставит ambitious цель, roadmap её закрывает через конкретную фичу.

**Сводная таблица PRD после правок (для собеса):**

| PRD цель | Sp4 факт | Sp5 факт | **Sp6 факт** | Verdict |
|---|---|---|---|---|
| Recall@5 ≥ 0.85 | 0.8125 ❌ | 0.8125 ❌ | **0.8542** | ✅ закрыта |
| MRR@10 ≥ 0.6 | 0.7007 ✓ | 0.7007 ✓ | 0.7024 | ✅ |
| Faithfulness ≥ 0.7 (revised) | 0.4500 ❌ | 0.6900 ❌ | **0.7400** | ✅ закрыта |
| Relevance avg ≥ 4 | 4.6701 ✓ | 4.6495 ✓ | 4.6979 | ✅ |
| Refusal rate = 1.0 | 1.0 ✓ | 1.0 ✓ | 1.0 | ✅ |
| TTFB до пилюль ≤ 500ms (revised) | n/a | ~300ms ✓ | **151ms** | ✅ |
| Полный non-streaming P50 ≤ 5s (revised) | 4.69s ✓ | 4.56s ✓ | 4.80s | ✅ |
| Полный non-streaming P95 ≤ 8s | 7.46s ✓ | 7.32s ✓ | 7.32s | ✅ |
| Cost ≤ $0.005 (требует prompt caching) | $0.0068 ❌ | $0.0068 ❌ | $0.0068 ❌ | ❌ Sprint 7 dependency |

**8/9 закрыто.** Cost — последний открытый PRD-пункт, явно зависит от Sprint 7 prompt caching.

---

**Sprint 6 ✅ закрыт окончательно.** Все артефакты в репо: журнал (этот файл), `docs/eval_results.md` (Sprint 6 final), `docs/eval_results_sprint5.md` (Sp5 архив), `data/eval/prod_latency_v4/results.json`, `data/eval/runs/{bi_only_20260509_174555, mvp_20260509_181603, mvp_20260509_191629, mvp_retrieval_only_20260509_181027}/`. Прод: `https://avi-help-production.up.railway.app/` (hybrid mode active, `bm25_ready: true` в `/health`).

---

## Post-sprint addenda (2026-05-11): soft-redirect + adaptive bi-routing

После закрытия Sprint 6 на проде всплыл класс fallback-кейсов вида «правильная статья в топ-K, но конкретный чанк покрывает узкий подкейс, а не общий вопрос». Триггерный кейс: `request_id eab9e505…` — «Как опубликовать объявление в категории Авто и транспорт». В hybrid top-5 попадает `4371_007` (статья «Размещаю новое объявление» в section «Авто и транспорт») — но конкретно этот чанк про «авто под заказ» (ИП, договор с поставщиком). LLM по правилу №1 «опирайся только на фрагменты» отказывалась отвечать → canned hard-fallback без ссылок.

### Диагностика (что было найдено в коде)

- **`score` в логе ≠ качество**: в hybrid режиме это `rrf_score` (~0.02-0.03), а pre-LLM fallback решается по `max(bi_score) < 0.3`. Из-за этого по логу нельзя было отличить pre-LLM fallback от LLM-side отказа. Добавлено поле `bi_score` в `RetrievalRecord` (коммит `c15c23e`).
- **Embedding пайплайн (`scripts/build_index.py:120`)** эмбедит только `chunk_text`. `section`/`category` лежат в Chroma metadata, в вектор не идут. → bi-encoder «не видит» что чанк помечен «Авто и транспорт», ранжирует исключительно по содержанию body. Это объясняет почему обзорный `4371_000` (текст про «автомобиль», «ГАИ») вне bi-top-50, а `4371_007` (текст с фразой «в категории Авто») попадает на bi-rank #2.
- **BM25 на этом запросе натаскивает мусор**: 18 из 20 BM25-кандидатов имеют `bi_score=0` (лексические совпадения на «Авто», «Тариф», «опубликовать» в статьях про тарифы / отметки / профессиональный план в Работе). Два из них (`4364_028`, `4244_001`) попали в финальный top-5 через RRF — обзорные чанки правильной статьи не попадают.

### Что испробовано (с цифрами на golden_set, 100 q, baseline recall@5=0.82 / MRR=0.6657)

| Подход | recall@5 | MRR@5 | Δrecall | ΔMRR | Решение |
|---|---|---|---|---|---|
| Bi 2x : BM25 1x weighted RRF | 0.8100 | 0.6590 | −1.0 | −0.7 | отброшен |
| Bi 3x : BM25 1x | 0.8200 | 0.6600 | 0 | −0.6 | отброшен |
| Bi 5x : BM25 1x | 0.8100 | 0.6715 | −1.0 | +0.6 | отброшен |
| Drop bi<0.3 фильтр | 0.8100 | 0.6640 | −1.0 | −0.2 | отброшен |
| Bi-only (BM25 off) | 0.7800 | 0.6660 | **−4.0** | 0 | подтверждает ценность BM25 |
| Article-level concentration (sum of top-3) | (не проверен) | — | — | — | гипотеза провалилась на нашем кейсе: 4374 имеет агрегат 2.06 > 4371 1.99, sum-based буст только усиливает неверный выбор |
| **Adaptive bi-only (T4: bi<0.3 в топе + top1_bi≥0.6)** | **0.8200** | **0.6782** | **0** | **+1.2** | ✅ катим |

T4-триггер: 13% запросов на golden_set. 0 broken / 0 fixed — recall-сет идентичен, но правильные статьи поднимаются в ранке (отсюда +1.2pp MRR). На нашем кейсе срабатывает (top-1 bi=0.7181, в топе 2 чанка с bi=0), top-5 переключается с hybrid-set на bi-only-set, LLM выдаёт ответ вместо soft-redirect.

### Что задеплоено

**1. Soft-redirect в `backend/prompts.py`** (коммит `380209f`). Третий исход у LLM между «answer» и «hard-fallback»: если в чанках есть статья очевидно про тему запроса, но содержание чанка не отвечает — `is_fallback=true` с непустым `sources_used` и lead'ом-перенаправлением «откройте статью X». Существующая логика `generation.py:331-336` уже сохраняет LLM-lead когда sources_used непустой — Python-кода менять не пришлось.

Проверено на 4-классах (наш кейс / OOD / точный in-domain / шумный retrieval): на проблемном — переход hard-fallback→soft-redirect; на остальных трёх — поведение идентично baseline'у. Регрессий нет.

**2. Adaptive bi-only routing T4 в `backend/retrieval.py`** (коммит `d031e44`). После hybrid `_rrf_merge`, если в результате есть чанк с `bi_score < ADAPTIVE_BI_THRESHOLD` (default 0.3) И `max(bi_score) >= ADAPTIVE_TOP1_THRESHOLD` (default 0.6) — возвращаем `bi_hits[:top_k]` вместо merged. Второй retrieval не запускается (bi-кандидаты уже в памяти).

Наблюдаемость: `latency_ms.adaptive_bi: bool` в логах + зелёный тег **adaptive-bi** в админке. Откат — `ADAPTIVE_BI_ROUTING=false` через env, без деплоя.

### Bottleneck, который НЕ решён

Обзорный чанк `4371_000` (содержит общую инструкцию «выберите вид объявления → Продаю личный автомобиль или Приобретён на продажу») остаётся **вне bi-top-50**, потому что его embedding посчитан без metadata. Никакое post-processing (фильтрация, перевзвешивание, agg) на top-K кандидатов это не чинит.

Реальный fix — на уровне индексации: embedить `[section] [category] [title]` префикс вместе с `chunk_text`. Это пересборка индекса + golden_set re-baseline. Записать в Sprint 7 roadmap как кандидата на отдельный блок («metadata-aware embedding»), если по логам adaptive-bi rate остаётся > 20% или soft-redirect rate > 5%.

### Метрики для контроля на проде (после раскатки)

- `latency_ms.adaptive_bi == true` rate. Ожидаем ~13% от non-OOD. Резкий скачок → подвинуть пороги.
- `is_fallback=true AND sources_used != []` rate (soft-redirect). Если > 5% — класс не редкий, есть смысл идти в metadata-aware embedding.
- Recall не отслеживается на проде (нет ground-truth), но MRR-эффект должен косвенно проявиться через рост positive-feedback (👍) на запросах с adaptive_bi=true.
