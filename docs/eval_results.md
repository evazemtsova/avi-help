# Eval Results

**Дата:** 2026-05-09
**Sprint:** 5 final (после Блока 6 — финальная сводка)
**Eval-set:** 100 in-domain + 20 OOD
**Eval-runs (финал):** `data/eval/runs/mvp_20260509_153514/` (post-rollback, $0 paid из cache); `data/eval/prod_latency_v3/results.json` (30 sequential prod-curl, no-reranker top_k=5)

> Журнал блочных изменений Sprint 5 — `docs/sprint5_changes_log.md`. Этот документ — финальная сводка для собеса; журнал — диагностический трек блоков с метриками каждого шага.

## Конфигурация системы (Sprint 5 final)

- **Generator model:** `claude-haiku-4-5` (input $1/M, output $5/M)
- **Embeddings:** `text-embedding-3-small`, 1536 dim
- **Vector DB:** Chroma на Railway volume, 4288 чанков из 518 статей
- **Top-K retrieval:** 10 (для MRR@10), top-K в LLM: **5** (Sprint 5 Блок 5 final — после отката reranker'а top_k=3 терял контекст без фильтра релевантности)
- **Threshold pre-LLM fallback:** top-1 score < **0.3** (bi-encoder cosine scale; калибровка под reranker scale 0.55 откатилась вместе с reranker'ом)
- **Competitor-list refusal:** ON (38 padded-substring маркеров: юла/озон/wb/lamoda/яндекс маркет/али/ebay/мегамаркет/drom/лавка/amazon/джум) — добавлен в Блоке 3.5
- **Safety priming:** ON (триггеры в query, не retrieval-категория — Блок 2)
- **Faithfulness judge prompt:** v4 с override (`_HARD_DISQUALIFIERS` + `_SOFT_MARKERS`) — Блок 1
- **Reranker:** **OFF** (Sprint 5 Блок 5 final — `bge-reranker-v2-m3` cross-encoder откатили после reality-check на shared Railway CPU; код остался, включается env-переменной `USE_RERANKER=true`)
- **Judge model:** `claude-sonnet-4-6` (input $3/M, output $15/M), tool use
- **Stack:** FastAPI + Vite/React, прод `https://avi-help.vercel.app/` + `https://avi-help-production.up.railway.app/`

## Главная таблица — Sprint 5 final vs PRD

| Метрика | PRD цель | Sprint 4 baseline | **Sprint 5 final** | Δ vs Sprint 4 | Verdict |
|---|---|---|---|---|---|
| **Recall@5** | ≥ 0.85 | 0.8125 | **0.8125** | 0 | ❌ −0.04 (reranker не дожил до прода) |
| MRR@10 | ≥ 0.6 | 0.7007 | **0.7007** | 0 | ✅ +0.10 |
| **Faithfulness (full)** | ≥ 0.9 ⚠️ | 0.4500 | **0.6900** | **+0.2400** | ❌ −0.21 от PRD, но **+24 п.п. cumulative** (главный win Sprint 5) |
| Faithfulness (non-fb) | — | 0.4433 | **0.6907** | **+0.2474** | — |
| Relevance avg (non-fb) | ≥ 4 | 4.6701 | **4.6495** | −0.02 | ✅ +0.65 |
| Refusal rate (OOD) | 1.0 | 1.0 | **1.0** (20/20) | 0 | ✅ |
| Latency P50 (prod) | ≤ 4s | 4.69s | **4.56s** | −0.13s | ❌ +0.56s (но streaming-декомп интерпретация) |
| Latency P95 (prod) | ≤ 8s | 7.46s | **7.32s** | −0.14s | ✅ −0.68s |
| Cost per query (in-dom, gen) | ≤ $0.005 | $0.0068 | ~$0.0068 | 0 | ❌ +36% (без prompt caching недостижимо) |

**$ потрачено за весь Sprint 5 (paid):** **$9.04** (Блок 1 $1.04 + Блок 2 $0.14 + Блок 3 $2.91 + Блок 3.5 $0.022 + Блок 4 $2.47 + Блок 5 $2.46). Остаток $5.96 от $15 бюджета.

> ⚠️ PRD-цели **0.9 / ≤4s P50 / ≤$0.005** помечены под пересмотр — обоснование в секции «PRD revision» ниже. Главный win спринта — **Faithfulness +24.7 п.п. cumulative** через переписанный judge-prompt + сужение safety priming до query-триггеров (Блоки 1+2).

## Декомпозиция по блокам — какой блок какой Δ дал

| Блок | Изменение | Δ Recall@5 | Δ Faithfulness (non-fb) | Δ Relevance non-fb | Δ Cost | Стоило ($) | Сохранено в final? |
|---|---|---|---|---|---|---|---|
| 1 | переписан `FAITHFULNESS_SYSTEM` + override v4 | 0 | **+0.196** (0.4433 → 0.6392) | 0 | 0 | $1.04 | ✓ |
| 2 | `SAFETY_PRIMING` сужен до query-триггеров | 0 | **+0.052** (0.6392 → 0.6907) | −0.02 | 0 | $0.14 | ✓ |
| 3 | reranker `bge-v2-m3` + cand=20 (top-20 → top-5) | **+0.073** (0.8125 → 0.8854) | −0.034 | +0.04 | 0 | $2.91 | ❌ откат на Блоке 5 |
| 3.5 | refusal threshold + competitor-list | 0 | +0.007 | +0.04 | 0 | $0.022 | ✓ (только competitor-list) |
| 4 | top_k=3 после reranker | 0 | +0.037 (0.6629 → 0.7000) | −0.12 | **−15%** ($0.0068 → $0.00577) | $2.47 | ❌ откат вместе с reranker'ом |
| 5 | reality check на проде → откат reranker, top_k=3→5 | **−0.073** (0.8854 → 0.8125) | −0.009 | −0.08 | +15% ($0.00577 → $0.0068) | $2.46 | финальное состояние |

**Что выжило в final-state:** Блоки 1+2 (всё faithfulness-улучшение) + competitor-list из Блока 3.5. **Что не выжило:** Блоки 3+4 (reranker не работает на shared Railway CPU — P95=24s vs PRD ≤8s; после полного отката top_k=3 без фильтра релевантности теряет контекст → top_k=5 пришлось вернуть).

**Cumulative win Sprint 5: +24.7 п.п. Faithfulness** (Блоки 1+2). Остальные метрики — на уровне Sprint 4 baseline (главное retrieval-достижение Recall@5 +7.3 п.п. потеряно в Блоке 5, но это сознательный trade-off под latency PRD).

## Retrieval — разбивка финального run

### По категориям (n=96, content-gap excluded)

| Категория | n | R@5 | MRR@10 |
|---|---|---|---|
| Авито для бизнеса | 1 | 1.000 | 1.000 |
| Безопасность | 15 | 0.667 | 0.535 |
| Заказы с доставкой | 20 | 0.750 | 0.667 |
| Как опубликовать объявление | 2 | 0.000 | 0.083 |
| Мои объявления | 9 | 1.000 | 0.926 |
| Оплата | 10 | 0.800 | 0.617 |
| Отклонили объявление | 6 | 0.833 | 0.667 |
| Проблемы с объявлением | 6 | 1.000 | 0.783 |
| Продвинуть объявление | 6 | 0.833 | 0.767 |
| Профиль | 13 | 0.923 | 0.765 |
| Связаться с пользователем | 6 | 0.833 | 0.833 |
| Тарифы | 2 | 1.000 | 1.000 |

### По difficulty (n=96)

| Уровень | n | R@5 | MRR@10 |
|---|---|---|---|
| easy | 60 | 0.850 | 0.726 |
| medium | 30 | 0.800 | 0.712 |
| hard | 6 | 0.500 | 0.396 |

(hard = 6 потому что 4 content-gap исключены из расчёта.)

> Числа идентичны Sprint 4 baseline — естественно, retrieval = bi-encoder без reranker'а. На Блоке 3 (reranker on) Recall@5 был 0.8854 / MRR 0.7605, **+7.3 п.п. / +6.0 п.п.** соответственно.

## Latency декомпозиция (prod, 30 sequential)

`data/eval/prod_latency_v3/results.json` — финальный замер 30 sequential `/answer/sync` curl на Railway.

### Sprint 5 final (no-reranker, top_k=5)

| | Client | Server total | Server retrieval | Server generation |
|---|---|---|---|---|
| P50 | **4.56s** | 4.06s | **137ms** | 3.93s |
| P95 | **7.32s** | 6.92s | 254ms | 6.81s |
| max | 7.71s | 7.40s | — | — |
| n_fallback | 1/30 (g002 content-gap) | — | — | — |

Server retrieval breakdown P50: embed 130ms + chroma 10ms + rerank 0ms = ~140ms. **Generation доминирует** — 96% server-time'а.

### Сравнение по точкам spring 5 (та же golden-set 30, тот же seed)

| | Sprint 4 prod | Sprint 5 v2-m3+20 (Блок 5 stop) | Sprint 5 base+10 (variant 2) | **Sprint 5 final (no-reranker top_k=5)** | PRD |
|---|---|---|---|---|---|
| Client P50 | 4.69s | 12.73s | 5.74s | **4.56s** | ≤4s |
| Client P95 | 7.46s | **24.27s** | 9.66s | **7.32s** ✅ | ≤8s |
| Server retrieval P50 | ~500ms | 8855ms | 2197ms | **137ms** | — |
| Server rerank P50 | — | ~8500ms | 2010ms | **0ms** | — |
| n_fallback | — | 2 | 9 ⚠️ | 1 | — |

**Главный вывод по latency:** на shared Railway CPU без MKL/AVX оптимизаций cross-encoder reranker (даже бoлee быстрая bge-base) даёт **2000-2500ms inference на 10 кандидатов** — несовместимо с PRD ≤8s. Локально (Mac M-series) тот же reranker даёт +200-400ms — **40× прогноза**.

## Failure cases (Sprint 5 final, n_unfaithful=31, n_low_relevance=2)

### Прогресс по 18 худшим кейсам Sprint 4 (Recall@5=0)

Те же кейсы, тот же retrieval (bi-encoder без reranker'а): **списки идентичны Sprint 4** — все 18 кейсов с Recall@5=0 остались с Recall@5=0. Эти кейсы — главный аргумент для reranker'а на dedicated CPU в roadmap.

| id | query | expected | top-1 | Что починилось бы reranker'ом? |
|---|---|---|---|---|
| g002 | трек номер не отслеживается | 2802 | 4372 | ❌ (content gap, не в top-20) |
| g003 | как сделать возврат если заказ не подошёл | 4400 | 4308 | ✓ Блок 3 затащил в top-5 (но faith всё равно False) |
| g007 | купил наушники с авито доставкой | 2831, 4400 | 4331 | ✓ Блок 3 |
| g011 | курьер не приехал | 2462 | 1909 | ❌ (top-17 in top-20, reranker не вытянул) |
| g020 | приехал телефон со сколом | 2831, 4400 | 4332 | ❌ (top-14 in top-20) |

(Полный список 18 кейсов — в `data/eval/runs/mvp_20260509_153514/results.jsonl` фильтр по `recall_at_5=0`.)

### Прогресс по unfaithful-кейсам (Sprint 4: 55 → Sprint 5 final: 31, **−24 кейса**)

| Категория Блока 4 (Sprint 4) | Sprint 4 кол-во | После Блока 1 (judge rewrite) | После Блока 2 (safety triggers) | Финал |
|---|---|---|---|---|
| Buggy judge (`is_faithful=false` при «(ок)»-claims) | 4-6 | **0** ✓ — judge с явным правилом возвращает true; override v4 ловит pure pure-soft cases | 0 | 0 |
| Soft нит-пик (мягкие переформулировки) | ~12-15 | **−6** через few-shot examples | 0 | 0 |
| Safety boilerplate в lead'е | 2-3 (g007, g020) | 0 | **−2** ✓ — priming не сработал, lead по делу | 0 |
| Реальные галлюцинации (overgeneralization, wrong audience) | ~10 | 0 | 0 | **−10** *(остались — целевая аудитория Блока 3 reranker'а, но Блок 3 откатили)* |

(Конкретные id остались unfaithful: g001 «разбитый товар» — overgeneralization про «компенсацию»; g003 «возврат» — 15 дней применено к ПВЗ; g017 «отправить посылку» — выдуманные 48 часов; g041 «не приходит SMS» — pograничный кейс safety priming на login flow.)

### Случаи relevance < 3 (всего 2)

| id | score | причина |
|---|---|---|
| g002 «трек номер не отслеживается куда копать» | 2 | pre-LLM fallback (top-1 score 0.43, retrieval мимо) → генерик-перенаправление в чат, конкретики нет. |
| g100 «как переехать в другой город с авито» | 1 | content-gap; pre-LLM fallback. |

### OOD-кейсы где модель ответила «по теме» вместо отказа

**Нет таких.** Все 20/20 OOD получили `is_fallback=true`. 18 ловятся по threshold 0.3 на bi-encoder, 2 («юла», «озон») — по competitor-list (Блок 3.5).

## Sprint 5 outcomes vs predictions

В Sprint 4 Insights table предсказывали Δ от каждой потенциальной правки. Сводим что вышло:

| Правка | Прогноз Sprint 4 (insights) | Sprint 5 факт | Verdict |
|---|---|---|---|
| Переписать `FAITHFULNESS_SYSTEM` | +25-35 п.п. faithfulness, ~$1.6 paid | **+19.6 п.п.** non-fb (0.4433 → 0.6392), $1.04 paid | ⚠️ нижняя граница прогноза, дешевле |
| Cross-encoder reranker | Recall@5 +5-15 п.п., latency +150-250ms | **+7.3 п.п.** на eval ✓; **+8500ms на Railway shared CPU** ❌ (40× прогноза) | ⚠️ eval-выигрыш реальный, но latency несовместим с прод-инфрой |
| Сузить `SAFETY_PRIMING` | +10 п.п. faithfulness | **+5.15 п.п.** (на v4-baseline 0.6392, не на Sprint 4 0.4433) | ✓ как ожидалось |
| Top_k=3 после reranker | Cost −30% ($0.0068 → ~$0.0048) | **−15%** ($0.0068 → $0.00577) — недобор PRD на $0.00077 | ⚠️ system+tool ~1500 input tokens fixed → потолок $0.0058 |
| In-memory cache популярных запросов | Latency P50 на повторах −80% | Не делали (вынесено в roadmap Sprint 6+) | — |

**Главный поворот Sprint 5:** прогноз reranker'а как «главного выигрыша» сбылся на eval-метрике, но провалился на проде из-за инфраструктурного ограничения. Cost-цель PRD оказалась нереалистичной без prompt caching на любой архитектуре с tool use ≥1500 input tokens. Faithfulness-цель PRD ≥0.9 нереалистична на Sonnet-judge даже с переписанным promptом — Sonnet строгий по дизайну (см. methodological finding 1 ниже).

## Methodological findings (полный список Sprint 4 + Sprint 5)

### 1. LLM-judge inconsistency (Sprint 4 finding, починен в Блоке 1)

Sprint 4 baseline judge возвращал `is_faithful=false` даже когда в собственных `unsupported_claims` помечал каждый claim как «подкреплено» / «(ок)». Конкретный пример — кейс g008 («как отменить заказ»). Из tool-output Sonnet'а в `data/eval/runs/mvp_20260508_215230/results.jsonl`:

```json
{
  "is_faithful": false,
  "unsupported_claims": [
    "Откройте его в разделе «Заказы» и нажмите кнопку «Отменить заказ» — в чанках не упоминается именно такой порядок действий как единый шаг для всех случаев",
    "Если продавец ещё не передал товар курьеру (...) — это подкреплено чанком 3, ОК",
    "Если кнопки нет, значит продавец уже подтвердил заказ — подкреплено чанком 4, ОК",
    "Напишите в поддержку Авито (...) — подкреплено чанком 3, ОК",
    "Деньги вернутся (...) в течение 5 рабочих дней — подкреплено чанком 4, ОК",
    "Банк может не прислать уведомление об отмене — подкреплено чанком 4, ОК",
    "Способ отмены зависит от статуса заказа — общая фраза, не проверяем"
  ]
}
```

6/7 claims помечены как «подкреплено / не проверяем», 7-й — soft нит-пик. При этом финальный `is_faithful=false`. Гипотеза: Sonnet решает поле по первому впечатлению (видит много пунктов → flag false), потом подтверждает каждый, но boolean-поле не пересчитывается.

**Починено в Блоке 1** через два механизма:
1. Переписан `FAITHFULNESS_SYSTEM` с явным правилом *«is_faithful=true ⇔ нет hard claim'ов»* + 2 few-shot примера.
2. Страховочный override `_looks_soft` с `_HARD_DISQUALIFIERS` (10 паттернов: «не подкреплен», «корректна, но», «обобщен», «overgeneraliz», «адресован») и `_SOFT_MARKERS` (16 явных: `(ок)`, `подкреплено чанком`, `не проверяем`, `не противоречие`, `структурное упрощение`).

### 2. Precision-over-recall на метрике (Sprint 5 Блок 1, валидирован Блоком 3.5)

**«Метрика, на которую нельзя положиться, хуже чем более низкая честная метрика».**

В Блоке 1 при выборе override-логики judge'а: v1-override (faithfulness 0.6701, формально проходил критерий приёмки 0.65) flipping 4 из 5 override-кейсов в `is_faithful=true`, маскируя реальные галлюцинации g007/g014/g041. Декомпозиция Блока 6 «какой блок какой Δ дал» сломалась бы — Блок 2 (safety priming) «починил» бы кейсы которые уже были помечены как faithful. Выбран v4 (0.6392, на 1.1 п.п. ниже барa приёмки), raw метрика честная.

В Блоке 3.5 принцип валидирован в обратную сторону: первая итерация threshold=0.6125 была overcorrection — precision на refusal перевесил recall на success, 8 правильных in-domain CORRECT кейсов потеряны (включая 2 safety и demo-blocker g061 «VIP-объявления»). Вторая итерация (0.55 + competitor-list) вернула 5/8 кейсов в LLM, сохранив refusal_rate=1.0.

**Вывод:** precision-over-recall — правильный default, но требует валидации на конкретных кейсах. Слепо «строже всегда лучше» не работает.

### 3. Recall@5 как retrieval-метрика не отражает end-to-end success (Sprint 5 Блок 3.5)

Между retrieval и пользователем стоит pre-LLM fallback (threshold + competitor-list). Recall@5 измеряет **«было ли возможно ответить»** (URL в top-5), не **«дали ли мы ответ»**. В Блоке 3.5 iter#1 Recall@5=0.8854 формально не упал, но 8 in-domain CORRECT кейсов попали в pre-LLM fallback с reasoning «не нашлось точного ответа» — пользователь получил отказ при наличии правильной информации в индексе.

Для следующего roadmap-цикла нужна **end-to-end метрика**:

```
success_rate = (in-domain_correctly_answered + ood_correctly_refused) / total
```

где `in-domain_correctly_answered` = `recall@5=1 AND not is_fallback AND faithfulness AND relevance≥4`.

В Sprint 5 в качестве суррогата используем (`Recall@5` × `non-fallback ratio` × `non-fb relevance/5`) — но это не unified metric, а пара колонок которые приходится читать вместе.

### 4. Cost-оптимизация может улучшить качество если она происходит после фильтра релевантности (Sprint 5 Блок 4)

Top_k=3 без reranker — экономия за счёт качества (bi-encoder менее точный → top-3 могут пропустить нужный чанк). Top_k=3 после reranker — экономия + качество (+3.7 п.п. faithfulness, потому что reranker уже отфильтровал релевантное → меньше шума в подаче → меньше повод для overgeneralization).

В Sprint 5 final после отката reranker'а top_k=5 пришлось вернуть — без cross-encoder фильтра 3 чанков теряли контекст. Cost вернулся к Sprint 4 baseline.

**Урок для архитектуры:** правильная последовательность оптимизаций — сначала фильтр (reranker), потом усечение (top_k); инверсия даёт регрессию.

### 5. Pre-deployment latency-замер ОБЯЗАТЕЛЕН на shared-CPU инфраструктуре (Sprint 5 Блок 5)

Локально reranker `bge-v2-m3` давал +200ms (M-series, MKL/AVX/Apple Accelerate), на Railway shared CPU — +8500ms (40× прогноза). Бриф Блока 3 написал «локально retrieval ~5с — Блок 5 проверит на проде» — эта отложенная валидация стоила $5+ paid и день работы (3 деплоя + откат).

**Урок:** для любого ML-инференса в проде нужен smoke-замер на target hardware ДО merge в main. Приближённое правило: на shared-CPU без MKL/AVX cross-encoder forward pass на ~250 tokens — 400-450ms; на M-series — 100-200ms; на dedicated x86 с MKL — 150-200ms.

### 6. Pydantic v2 не coerces float→int с fractional part (Sprint 5 Блок 5 hotfix)

Коммит `97fef7e` (timing breakdown) добавил `embed_ms`/`chroma_ms`/`rerank_ms` в `latency_ms` через `round(x, 1)` (float). `AnswerResponse.latency_ms: dict[str, int]` — Pydantic strict mode валит на любом значении с `.5`. Баг существовал ~6 часов на проде, но не был замечен потому что после коммита через `/answer/sync` не было живых запросов до моего деплоя Блока 5.

**Урок:** каждое изменение response schema требует один curl smoke к **каждому** endpoint'у который его использует. И — Pydantic v2 default coercion НЕ permissive: float→int coerce только если значение целое (1934.0 OK, 1934.5 fail). Минимальный фикс — `int(round(x))` в источнике.

## PRD revision (открытые вопросы для финального документа)

### F11 (latency)

**Текущая формулировка:** «P50 end-to-end ≤ 4s, P95 ≤ 8s»
**Проблема:** со streaming SSE «end-to-end» не описывает UX — пользователь видит пилюли через 300ms, первое слово lead через 1.5s, полный ответ через 5s. P50=4.56s в этой модели не критично — пользователь уже читает с ~300ms.
**Предложение:** переписать F11 как декомпозицию TTFB:
- TTFB до пилюль источников: ≤ 500ms
- TTFB до первого слова lead: ≤ 2s
- Полное время (для non-streaming /answer/sync): P50 ≤ 5s, P95 ≤ 8s ✓ (current 4.56s / 7.32s)

### 7.2 (Faithfulness ≥ 0.9)

**Проблема:** недостижимо на Sonnet-judge даже с переписанным prompt'ом. Sonnet строгий по дизайну. Реалистичный потолок 0.80-0.85.
**Предложение:** ослабить до **≥ 0.7** (current Sprint 5 = 0.69, near-target). Альтернатива: формулировка «пропорция реальных галлюцинаций ≤ 0.15» (декомпозиция через ручной разбор unfaithful-кейсов — 70% false-positive judge / 26% real galls / 4% safety).

### 7.3 (Cost ≤ $0.005)

**Проблема:** недостижимо без Anthropic prompt caching. System (~600 tokens) + tool definition (~900 tokens) = ~1500 fixed input tokens = $0.0015 only от system+tool на запрос. Чанки + output добавляют $0.005+. Потолок без caching ~$0.0058 на текущей архитектуре.
**Предложение:** ослабить до **≤ $0.007** (current $0.0068, in-target) ИЛИ принять что цель достижима только с prompt caching (roadmap).

## Roadmap (Sprint 6+)

| Кандидат | Цена | Эффект | Приоритет |
|---|---|---|---|
| **Anthropic prompt caching** на system + tool definition (TTL 5 мин) | 1-2ч код, конфиг | Cost cached input −90% → потолок $0.001-0.002/запрос ✓ PRD 7.3 | топ-1 |
| **Reranker на dedicated CPU instance** (env-flag `USE_RERANKER=true`) | 1ч инфра + monthly $$ | Recall@5 +7.3 п.п. ✓ PRD 0.85; latency +200-400ms (терпимо на dedicated) | при наличии бюджета на инфру |
| **End-to-end success_rate metric** (methodological finding 3) | 2ч eval-script | Unified-метрика вместо пары колонок | high (под собес) |
| **Расширить retrieval top-K с 20 до 50** (для reranker-варианта) | 30 мин | Закрывает g011/g020-style кейсы (top-17 в bi-encoder) | only with reranker on |
| **Multi-query rewrite через Haiku** для коротких запросов | 4-6ч + +500ms latency | Закрывает g002-style content gaps | medium |
| **HyDE (Hypothetical Document Embeddings)** для длинных разговорных запросов | 3-5ч + +1.5s latency | Закрывает g020-style («телефон со сколом») | low (большое latency-cost) |
| **Query-нормализация** («обяв→объявления» и т.п.) через Haiku | 2-3ч + +200ms | Closes g061 demo-blocker «VIP-объявления» | medium (демо-фикс) |
| **In-memory cache популярных запросов** (TTL=24h) | 1-2ч | Latency P50 на повторах −80%; cost на повторах −100% | high (под продакшн нагрузку) |

## Воспроизводимость

```bash
# Полный прогон mvp (из кэша = бесплатно, ~1 сек)
backend/.venv/bin/python scripts/eval.py --config mvp

# Ablation baseline (без safety priming, тот же no-reranker)
backend/.venv/bin/python scripts/eval.py --config baseline

# Воспроизведение reranker-runs из журнала Sprint 5 Блока 3 (для аудита)
backend/.venv/bin/python scripts/eval.py --config mvp_with_reranker

# Прод latency 30 запросов (no-reranker, top_k=5)
# (см. data/eval/prod_latency_v3/results.json)
```

Кэш-файлы (~3.6 MB embeddings + ~210 KB LLM): `data/llm_cache.jsonl`, `data/embedding_cache.jsonl` (в `.gitignore`).
