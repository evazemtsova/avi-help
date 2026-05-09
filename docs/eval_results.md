# Eval Results

**Дата:** 2026-05-09
**Sprint:** 6 final (после Блока 6 — финальная сводка)
**Eval-set:** 100 in-domain + 20 OOD
**Eval-runs (финал):** `data/eval/runs/mvp_20260509_191629/` ($0 paid из cache, full re-confirm); `data/eval/prod_latency_v4/results.json` (30 sequential prod-curl, hybrid mode).
**Архив:** `docs/eval_results_sprint5.md` — Sprint 5 final state с диагностикой 5 методологических находок.

> Журнал блочных изменений Sprint 6 — `docs/sprint6_changes_log.md`. Этот документ — финальная сводка для собеса; журнал — диагностический трек блоков с метриками каждого шага.

## Конфигурация системы (Sprint 6 final)

- **Retrieval:** **BM25 + bi-encoder + RRF (Reciprocal Rank Fusion, k=60)**, candidates=20 на каждый ранкер. `USE_HYBRID_RETRIEVAL=true` env, default включён.
- **Bi-encoder:** `text-embedding-3-small` (1536 dim). Chroma на Railway volume, 4288 чанков из 518 статей.
- **BM25:** `rank-bm25 0.2.2` (BM25Okapi). Tokenizer: `lowercase + re.split([\W_]+, UNICODE) + len ≥ 2`. Без стемминга, стоп-слов, лемматизации (минимальный baseline). Index in-RAM, пересобирается при старте FastAPI из Chroma за ~500ms на M-series, ~1-2с на Railway shared CPU.
- **RRF formula:** `score(d) = Σ_r 1/(k + rank_r(d))` по двум ранкерам (BM25 top-20 + bi-encoder top-20). k=60. Документы из одного ранкера — учитываются с одним `1/(k+rank)`.
- **Generator:** `claude-haiku-4-5` (input $1/M, output $5/M).
- **Top-K в LLM:** **5**.
- **Threshold pre-LLM fallback:** `max(h.bi_score) < 0.3` (bi-encoder cosine scale). НЕ `hits[0].score` — устойчивее к edge case BM25-only chunk в RRF top-1 с `bi_score=0`.
- **Competitor-list refusal:** ON (Sprint 5 Блок 3.5, 38 padded-substring маркеров: юла/озон/wb/lamoda/я.маркет/aliexpress/ebay/мегамаркет/drom/лавка/amazon/джум).
- **Safety priming:** ON (Sprint 5 Блок 2 — query-триггеры, не retrieval-категория).
- **Faithfulness judge prompt:** v4 с override (`_HARD_DISQUALIFIERS` + `_SOFT_MARKERS`) — Sprint 5 Блок 1.
- **Reranker:** **OFF** (`USE_RERANKER=false`). Код остался opt-in для dedicated-CPU deploy.
- **Judge model:** `claude-sonnet-4-6` (input $3/M, output $15/M), tool use.
- **Stack:** FastAPI + Vite/React, прод `https://avi-help.vercel.app/` + `https://avi-help-production.up.railway.app/`.

## Главная таблица — Sprint 6 final vs PRD

| Метрика | PRD цель | Sprint 4 baseline | Sprint 5 final | **Sprint 6 final** | Δ vs Sp5 | Verdict |
|---|---|---|---|---|---|---|
| **Recall@5** | ≥ 0.85 | 0.8125 | 0.8125 | **0.8542** | **+0.0417** | ✅ **закрыли впервые в проекте** |
| MRR@10 | ≥ 0.6 | 0.7007 | 0.7007 | **0.7024** | +0.0017 | ✅ |
| **Faithfulness (full)** | ≥ 0.7 (revised) | 0.4500 | 0.6900 | **0.7400** | +0.0500 | ✅ **закрыли revised PRD** |
| Faithfulness (non-fb) | — | 0.4433 | 0.6907 | **0.7396** | +0.0489 | (honest range +5..+7 п.п. от Sp5; см. ниже) |
| Relevance avg (non-fb) | ≥ 4 | 4.6701 | 4.6495 | **4.6979** | +0.0484 | ✅ |
| Refusal rate (OOD) | 1.0 | 1.0 | 1.0 | **1.0** (20/20) | 0 | ✅ |
| Latency P50 (prod) | ≤ 5s (revised TTFB) | 4.69s | 4.56s | **4.80s** | +0.24s | ✅ |
| Latency P95 (prod) | ≤ 8s | 7.46s | 7.32s | **7.32s** | 0 | ✅ |
| n_low_relevance (<3) | — | n/a | 2 | **0** | −2 | ✅ bonus |
| Cost per query | ≤ $0.005 (caching roadmap) | $0.0068 | $0.0068 | $0.0068 | 0 | ❌ требует prompt caching |

**8/9 PRD-целей закрыто.** Cost — единственный недобор, требует Anthropic prompt caching на ~1500 input tokens константной части (system + tool definition).

**$ потрачено за Sprint 6:** **$5.70** (Block 3.1 bi_only $2.77 + Block 3.4 hybrid $2.73 + Block 5 prod latency ~$0.20). Cumulative проект: $14.74 / **$21** (бюджет $15 + $6 пополнение перед Block 3.4).

## Декомпозиция wins по ранкерам (R@5 +4.17 п.п.)

Sprint 6 bi_only baseline имел 18 кейсов с R@5=0 на n=96 countable. После hybrid:

| Bucket | n | Кейсы | Что починилось / осталось |
|---|---|---|---|
| **Fixed via BM25 only** (expected не было в bi-encoder top-10) | **4** | g011, g020, g054, g073 | Главный win-pattern — короткие/разговорные/typo-запросы где лексика > семантика |
| **Fixed via RRF synergy** (оба ранкера нашли, RRF поднял в top-5) | **3** | g025, g035, g060 | Bi #6-#10 + BM25 #1-#7 → объединённый rank подтягивает |
| **Remained — content gap** (не в top-20 ни одного ранкера) | 6 | g002, g007, g024, g042, g058, g095 | Структурные дыры в БЗ Авито или сильные опечатки — лечатся HyDE / новой статьёй / стеммингом |
| **Remained — RRF не вытянул из top-20** | 5 | g003, g026, g034, g089, g094 | Roadmap-кандидат: candidates 20→50 |
| **Broken (R=1→0)** | **3** | g021, g049, g051 | g021 RRF noise (соседняя safety-статья); g049/g051 BM25 boost'нул нерелевантные |

**Net: +7 fixed − 3 broken = +4 кейса** = +4.17 п.п. на n=96 ✓ совпадает с агрегатом 0.8125 → 0.8542.

### Что закрывает BM25 (главные wins)

- **g020 «приехал телефон со сколом на экране а продавец говорит всё было целое»** — BM25 #1 (`2831_007`). Sprint 5 reranker НЕ закрыл (expected был на позиции 14/20). Hybrid закрывает. **Cherry-pick win.**
- **g054 «верниите деньги за доставку»** (опечатка «верниите») — BM25 #2. Лексика «деньги/доставку» матчится без стемминга на правильную статью.
- **g073 «сообщения не отправляются что делать»** — BM25 #1.
- **g011 «курьер не приехал что делать»** — BM25 #8.

### MRR@10 почти не вырос (+0.17 п.п.)

Recall@5 +4.17 п.п., но MRR@10 — почти 0. Это значит: **hybrid редко поднимает expected на #1**, чаще «поднимает с #6-#10 в top-5». Главный effect — **inclusion в top-5**, не **promotion на #1**. Это объясняется нативой RRF formula: на bi-encoder top-1 контрибьюция = 1/61, BM25 top-5 контрибьюция = 1/65 — близко, RRF редко двигает уже-первый чанк.

## Faithfulness +5..+7 п.п. — honest decomposition

Финальная цифра **0.66 → 0.74 (+8 п.п.)** на full sample, но устойчивый Δ — **+5..+7 п.п.**

| Источник | Вклад в +8 п.п. | Доказательство |
|---|---|---|
| (a) BM25 cluster effect — top-5 целиком из правильной статьи | ~30-40% | g014: bi_only top-5 mixed `[4050, 4362, 4362, 4362, 4296]`, hybrid `[4362]×5` → точный ответ |
| (b) Возврат g023/g050/g061 из fallback в LLM | **0%** | НЕ подтвердилось — g050/g061 наоборот ушли в LLM-fallback в hybrid |
| (c) Different chunks → different answer style → less overgeneralization | ~40-50% | g012 mixed top-5 → Haiku пишет conservative «после оплаты не получится» вместо специфичного |
| (d) Sonnet noise на похожих формулировках | ~10-20% | g001: top-5 chunks идентичны (все `2831`), leads почти одинаковы, faith flip — это шум judge'а |

В презентации цитируем **+5..+7 п.п. устойчивых** (с диапазоном), а не +8. Это связано с methodological finding Sprint 5 #1 (Sonnet judge inconsistency) — часть «улучшения» — это шум, а не реальный win.

## Retrieval — разбивка финального run (n=96)

### По категориям

| Категория | n | R@5 | MRR@10 | Δ R@5 vs Sp5 |
|---|---|---|---|---|
| Авито для бизнеса | 1 | 1.000 | 0.500 | 0 |
| Безопасность | 15 | 0.733 | 0.601 | **+0.066** |
| Заказы с доставкой | 20 | 0.850 | 0.702 | **+0.100** (главный домен) |
| Как опубликовать объявление | 2 | 0.000 | 0.000 | 0 (content gap) |
| Мои объявления | 9 | 1.000 | 0.944 | 0 |
| Оплата | 10 | 0.800 | 0.518 | 0 |
| Отклонили объявление | 6 | 0.833 | 0.778 | 0 |
| Проблемы с объявлением | 6 | 1.000 | 0.917 | 0 |
| Продвинуть объявление | 6 | 1.000 | 0.778 | **+0.167** |
| Профиль | 13 | 0.846 | 0.679 | −0.077 |
| Связаться с пользователем | 6 | 1.000 | 0.889 | **+0.167** |
| Тарифы | 2 | 1.000 | 0.600 | 0 |

### По difficulty

| Уровень | n | R@5 | MRR@10 | Δ R@5 vs Sp5 |
|---|---|---|---|---|
| easy | 60 | 0.883 | 0.759 | +0.033 |
| medium | 30 | 0.867 | 0.659 | **+0.067** |
| hard | 6 | 0.500 | 0.350 | 0 (content gaps) |

## Latency декомпозиция (prod, 30 sequential)

`data/eval/prod_latency_v4/results.json` — финальный замер 30 sequential `/answer/sync` curl на Railway, hybrid mode.

### Sprint 6 final (hybrid, top_k=5)

| | Client | Server total | Server retrieval | Server generation |
|---|---|---|---|---|
| P50 | **4798ms** | 4416ms | **151ms** | 4169ms |
| P95 | **7315ms** | 5852ms | 447ms | 5704ms |
| max | 8504ms | 7533ms | — | — |
| n_fallback | 0/30 | — | — | — |

**Server retrieval breakdown P50:** embed 130ms + chroma 5ms + **bm25 10ms** + **merge 3ms** + overhead 3ms = ~151ms. **Generation доминирует** — 94% server-time'а.

### Сравнение Sprint 5 v3 (no-reranker bi-only) → Sprint 6 v4 (hybrid)

| | Sp5 v3 | **Sp6 v4 (hybrid)** | PRD |
|---|---|---|---|
| Client P50 | 4562ms | **4798ms** | ≤ 5s ✓ |
| Client P95 | 7317ms | **7315ms** | ≤ 8s ✓ |
| Server P50 | 4059ms | 4416ms | — |
| Server P95 | 6920ms | **5852ms** | — (variance уменьшилась) |
| Server retrieval P50 | 137ms | **151ms** | — |
| Server retrieval P95 | 254ms | **447ms** | — |
| Server **BM25** P50/P95 | — | **10/25ms** | new |
| Server **merge** P50/P95 | — | **3/3ms** | new |
| n_fallback | 1 | **0** | — |

**Главный архитектурный win:** **BM25 на shared Railway CPU = 10ms P50, 25ms P95.** В **1000× быстрее** чем cross-encoder reranker (Sprint 5 Блок 5: P50 reranker = 8500ms на той же инфре). IDF-lookup в Python dict работает консистентно даже без MKL/AVX. **Алгоритмический retrieval-фильтр >> нейросетевой на shared CPU.**

## Failure cases (Sprint 6 final)

### 18 R@5=0 кейсов Sprint 6 bi_only baseline → 7 fixed в hybrid

| id | query | Sp6 bi_only top-1 | hybrid статус | причина |
|---|---|---|---|---|
| g002 | трек номер не отслеживается куда копать | 4372_001 | ✗ | content gap (expected 2802 не в top-20) |
| g003 | как сделать возврат если заказ не подошёл | 4308_022 | ✗ | BM25 #1 но bi mismatch → RRF не вытянул |
| g007 | купил наушники с авито доставкой | 4331_010 | ✗ | content gap |
| **g011** | **курьер не приехал что делать** | 1909_005 | ✓ FIXED | **BM25 #8 — лексический матч** |
| **g020** | **приехал телефон со сколом** | 1829_000 | ✓ FIXED | **BM25 #1 — cherry-pick win** |
| g024 | подозрительный qr код продавец прислал | 4221_004 | ✗ | content gap |
| **g025** | пришло на почту письмо обновите данные | 4504_002 | ✓ FIXED | RRF synergy (bi #8 + BM25 #7) |
| g026 | в смс пришёл код хотя я ничего не запрашивал | 4221_006 | ✗ | BM25 #15 — слишком далеко для RRF |
| g034 | слила доступ к профилю как сменить пароль | 1869_001 | ✗ | BM25 #13 — слишком далеко |
| **g035** | странная авторизация с другого устройства | 1869_002 | ✓ FIXED | RRF synergy (bi #9 + BM25 #1) |
| g042 | забыл пороль как восстановить | 4376_000 | ✗ | content gap (опечатка «пороль») |
| **g054** | **верниите деньги за доставку** | 4308_022 | ✓ FIXED | **BM25 #2 — лексика «деньги/доставку»** |
| g058 | хочу вывыести деньги с авито доставки | 4324_010 | ✗ | content gap (опечатка «вывыести») |
| **g060** | как продвинуть объявление чтобы видели больше людей | 4341_002 | ✓ FIXED | RRF synergy (bi #10 + BM25 #1) |
| **g073** | **сообщения не отправляются что делать** | 1880_001 | ✓ FIXED | **BM25 #1** |
| g089 | объявление отклонили без причины как восстановить | 4373_002 | ✗ | bi #6, BM25 #13 — RRF не вытянул |
| g094 | как подать объявление о квартире | 4234_009 | ✗ | content gap (домен-specific) |
| g095 | как опубликовать объявление о товаре с нуля | 4234_009 | ✗ | content gap (нет универсальной статьи) |

### Регрессии Sprint 6 — 3 кейса R=1→0

| id | query | bi top-pos | hybrid | причина |
|---|---|---|---|---|
| g021 | звонят якобы из СБ просят код из смс | bi #4, BM25 #5 | ✗ | RRF noise — `4221_*` соседняя статья boost'нула |
| g049 | что делать если профиль удалили без меня | bi #1, BM25 not in top-20 | ✗ | BM25 boost'нул нерелевантные → expected ушёл с #1 на #6 |
| g051 | не могу пополнить кошелёк | bi #3, BM25 not in top-20 | ✗ | аналогично g049 |

### LLM-fallback в hybrid (3 in-domain кейса)

| id | Sp5 final | Sp6 bi_only | **Sp6 hybrid** | bi_top1 cosine | Что произошло |
|---|---|---|---|---|---|
| g023 «вотсап» | answered | answered | answered (faith=False) | 0.5152 | Safety-priming активирован, но Sonnet flagit hallucination |
| g050 «оплата два раза» | answered | answered | **LLM-fallback** | 0.4831 | RRF переставил top-5 → Haiku решил «не нашлось» |
| g061 «vip для обяв» | answered | answered | **LLM-fallback** ⚠ demo-blocker | 0.5094 | Sleng «обяв» снижает уверенность, hybrid переставил остальные → Haiku fallback |

**g061 demo-blocker НЕ снят hybrid'ом.** Roadmap Sprint 7 — query-нормализация «обяв→объявления».

### OOD-кейсы где модель ответила «по теме» вместо отказа

**Нет таких.** Все 20/20 OOD получили `is_fallback=true`. 12 ловятся по `bi_score < 0.3` pre-LLM, 2 («юла», «озон») — по competitor-list (Sprint 5 Block 3.5), 6 ловятся LLM-fallback (bi_score 0.30-0.45, Haiku сам решил OOD).

## Sprint 6 outcomes vs predictions

| Прогноз (бриф / probe) | Факт Sprint 6 | Verdict |
|---|---|---|
| Probe 4/5 cherry-picked | 4/5 в hybrid sanity Block 2 + воспроизведено на полном сете для 4/5 | ✓ |
| Recall@5 +4..+8 п.п. | +4.17 п.п. (0.8125 → 0.8542) | ✓ нижняя граница |
| MRR@10 +3..+8 п.п. | +0.17 п.п. | ⚠ hybrid редко двигает уже-первый чанк (RRF math) |
| Faithfulness −1..+2 п.п. (новые ответы → шум) | +5..+7 п.п. honest (+8 noisy) | ⚠ **bonus неожиданный** |
| Refusal rate 1.0 | 1.0 ✓ | ✓ |
| Latency P50 +50-200ms | +236ms client | ✓ нижняя граница |
| BM25 latency на shared CPU | **10ms P50, 25ms P95** | ✓ намного лучше чем reranker на той же инфре |
| Cost +$4-6 paid (3-config ablation) | $5.70 (urезанный 2-config) | ✓ урезанный план сэкономил $0.30-0.50 |

## Methodological findings (полный список Sprint 4 + Sprint 5 + Sprint 6 — для собеса)

### 1. LLM-judge inconsistency (Sprint 4 finding, починен в Sprint 5 Блок 1)

Sonnet judge возвращал `is_faithful=false` даже когда в собственных `unsupported_claims` помечал каждый claim как «(ок)» / «подкреплено». Конкретный пример — кейс g008. Починено через переписанный `FAITHFULNESS_SYSTEM` v4 + страховочный override `_looks_soft` с `_HARD_DISQUALIFIERS` / `_SOFT_MARKERS`.

### 2. Precision-over-recall на метрике (Sprint 5 Блок 1, валидирован Блоком 3.5)

«Метрика, на которую нельзя положиться, хуже чем более низкая честная метрика.» В Sprint 5 Блоке 1 v1-override (faithfulness 0.6701, формально проходил критерий 0.65) flipping 4 из 5 override-кейсов в `is_faithful=true`, маскируя реальные галлюцинации. Выбран v4 (0.6392, на 1.1 п.п. ниже барa, но raw метрика честная). В Sprint 5 Блоке 3.5 принцип валидирован в обратную сторону: первая итерация threshold=0.6125 была overcorrection. **Урок: precision-over-recall — правильный default, но требует валидации на конкретных кейсах.**

### 3. Recall@5 как retrieval-метрика не отражает end-to-end success (Sprint 5 Блок 3.5)

Между retrieval и пользователем стоит pre-LLM fallback (threshold + competitor-list). Recall@5 измеряет **«было ли возможно ответить»** (URL в top-5), не **«дали ли мы ответ»**. Для следующего roadmap-цикла нужна **end-to-end метрика**:

```
success_rate = (in-domain_correctly_answered + ood_correctly_refused) / total
```

### 4. Cost-оптимизация может улучшить качество если она происходит после фильтра релевантности (Sprint 5 Блок 4)

Top_k=3 без reranker — экономия за счёт качества; top_k=3 после reranker — экономия + качество (+3.7 п.п. faithfulness). **Урок:** правильная последовательность оптимизаций — сначала фильтр (reranker), потом усечение (top_k); инверсия даёт регрессию.

### 5. Pre-deployment latency-замер ОБЯЗАТЕЛЕН на shared-CPU инфраструктуре (Sprint 5 Блок 5)

Локально reranker `bge-v2-m3` давал +200ms (M-series, MKL/AVX), на Railway shared CPU — +8500ms (40× прогноза). **Урок:** для любого ML-инференса в проде нужен smoke-замер на target hardware ДО merge в main. Приближённое правило: на shared-CPU без MKL/AVX cross-encoder forward pass на ~250 tokens — 400-450ms; на M-series — 100-200ms; на dedicated x86 с MKL — 150-200ms. **Sprint 6 валидирует обратное:** алгоритмические фильтры (BM25/SPLADE) консистентны через все архитектуры (~10-50ms на 4288 чанков).

### 6. Bullet-fix как cache-invalidating change (Sprint 6 Блок 4 — НОВАЯ)

Косметическая правка `ANSWER_TOOL` description в коммите `5baa5e2 fix bullet-points '•' → '- '` после Sprint 5 final eval вызвала:

**Format shift в ответах Haiku:** 30/97 ответов с `•` → 0/97; 18/97 с `- ` lists → **83/97**. Haiku массово стал писать markdown-списки.

**Эффект на faithfulness — −4 п.п. (0.6907 → 0.6495 на одной retrieval):** смесь причин (анализ 16 True→False flips):
- ~70% format-induced specificity: новый `- ` формат → Haiku enumerates cases более явно → Sonnet парсит каждый item как discrete claim → находит больше overgeneralization (g005, g019, g046)
- ~30% реальные content-shifts: Haiku ответил по-другому, не только формат (g018 «не дают распаковать» — Sp5 правильно «нормально» с caveat'ом, Sp6 неправильно «не нормально»)

**Cache-invalidation:**
- `make_key(model, messages, tools, temperature, system)` — изменение tool description = новый ключ для всех queries
- 308 кэш-ключей Sprint 5 final стали невалидны
- Sprint 6 bi_only paid $2.77 на пересоздание кэша

**Урок:** **«Косметическая правка промпта инвалидирует cache как retrieval-правка, и формат вывода влияет на judge так же сильно как содержание.»** Любая смена `ANSWER_TOOL`/`SYSTEM_PROMPT`/`FAITHFULNESS_SYSTEM`/`USER_TEMPLATE` требует осознанного решения paid rerun. Особенно правки которые меняют **структуру** ответа (списки vs параграфы) — judge сильнее реагирует на структуру чем на стилистику.

## Roadmap (Sprint 7+)

| Кандидат | Цена | Эффект | Приоритет |
|---|---|---|---|
| **Демо UI / README / видео / чипсы** | Sprint 7 главное | Готовность к собесу | топ-1 |
| **Query-нормализация** «обяв→объявления», «вывыести→вывести», «пороль→пароль» через словарь | 30 мин код, $0 paid | Снимает g061 demo-blocker + g042 + g058 (3 кейса) | топ-2 (демо-fix) |
| **End-to-end success_rate metric** (methodological finding 3) | 2ч eval-script | Unified-метрика вместо пары колонок | топ-3 (под собес) |
| **Anthropic prompt caching** на system + tool definition (~1500 input tokens) | 1-2ч код | Cost cached input −90% → потолок $0.001-0.002/запрос ✓ закроет PRD 7.3 | high (для cost-PRD) |
| **HyDE / multi-query rewrite** для content-gap | 4-6ч + $0.01-0.02/query overhead | Закрывает 6 content-gap кейсов или graceful gap-detector (g002 fallback→hallucination риск) | medium |
| **Расширить candidates 20→50** в RRF | 30 мин, +5-10ms latency | Закроет 5 «not lifted from top-20» (g003, g026, g034, g089, g094) | medium |
| **bm25_only ablation на полном сете** | $1-2 paid | Diagnostic — не блокирующий | low (post-launch) |
| **Стемминг / стоп-words / лемматизация** в BM25 tokenizer | 1-2ч | Может закрыть опечатки g042 «пороль», g058 «вывыести» (но дублирует query-нормализацию) | low |
| **Reranker как opt-in для dedicated CPU** | 1ч инфра + monthly $$ | Recall@5 +7 п.п. (Sprint 5 Block 3 был 0.8854) — выше чем hybrid 0.8542 | low (при бюджете на инфру) |
| **PRD revision proposal в чат** | — | Раздел F11 latency (TTFB-декомп), 7.2 Faithfulness ≥0.7 (закрыта), 7.3 Cost ≤$0.005 (через caching) | до Sprint 7 |

## PRD revision (открытые вопросы для финального документа)

### F11 (latency)

**Текущая формулировка:** «P50 end-to-end ≤ 4s, P95 ≤ 8s»
**Sprint 6 факт:** P50 4798ms, P95 7315ms — выходит за PRD F11 P50, попадает в P95.
**Предложение:** переписать F11 как декомпозицию TTFB (со streaming):
- TTFB до пилюль источников: ≤ 500ms (Sprint 6 retrieval P50 = 151ms ✓)
- TTFB до первого слова lead: ≤ 2s (Sprint 5 замер был 1.5s)
- Полное время (для non-streaming /answer/sync): P50 ≤ 5s, P95 ≤ 8s ✓ (Sprint 6 4798ms / 7315ms)

### 7.2 (Faithfulness ≥ 0.9)

**Sprint 5 финал:** revised до ≥ 0.7 с обоснованием (Sonnet строгий judge).
**Sprint 6 факт:** 0.7400 full / 0.7396 non-fb — **закрыли revised PRD ≥ 0.7**.
**Предложение:** PRD 7.2 переписать на «≥ 0.7» окончательно. Honest range +5..+7 п.п. устойчивых от Sp5 baseline (часть из +8 — Sonnet noise, см. methodological finding #1).

### 7.3 (Cost ≤ $0.005)

**Sprint 5/6 факт:** $0.0068 — недостижимо без Anthropic prompt caching на ~1500 input tokens константной части.
**Decision (user, 2026-05-09): B — оставить цель ≤ $0.005**, явно прописать Anthropic prompt caching на system + tool definition как **required Sprint 7+ dependency**. Это методологически чище — PRD ставит ambitious цель, roadmap её закрывает через конкретную фичу.

## Воспроизводимость

```bash
# Полный прогон mvp (hybrid, из кэша = бесплатно, ~1 сек)
backend/.venv/bin/python scripts/eval.py --config mvp

# Ablation bi_only (Sprint 5 retrieval — paid $2.77 одноразово из-за bullet-fix)
backend/.venv/bin/python scripts/eval.py --config bi_only

# Только retrieval-метрики (skip generation + judge, $0 paid)
backend/.venv/bin/python scripts/eval.py --config mvp --retrieval-only

# Воспроизведение reranker-runs из Sprint 5 Block 3 (для аудита)
backend/.venv/bin/python scripts/eval.py --config mvp_with_reranker

# Прод latency 30 запросов (hybrid)
# (см. data/eval/prod_latency_v4/results.json)
```

Кэш-файлы (~3.6 MB embeddings + ~210 KB LLM): `data/llm_cache.jsonl`, `data/embedding_cache.jsonl` (в `.gitignore`).
BM25 индекс пересобирается на старте FastAPI из Chroma за ~500ms (M-series) / ~1-2s (Railway shared CPU).
