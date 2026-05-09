# План разработки: А-Помощь

**Связанные документы:** `01-PRD.md`, `02-TDR.md`, `03-ML-System-Design.md`
**Срок:** 5 дней до демо
**Бюджет:** $15 на API

## Как пользоваться этим документом

- Каждый спринт — законченная вертикаль с проверяемым выходом.
- Внутри спринта задачи в порядке выполнения, с зависимостями.
- По ходу работы:
  - меняем `Статус` спринта (`не начат` → `в работе` → `готов`),
  - проставляем `[x]` в чек-боксах,
  - в `Заметки` пишем что поменялось vs план, что узнали, какие решения приняли,
  - в `Блокеры` — что мешает двигаться и как обходим.
- Если решение из PRD/TDR пересмотрено — фиксируем здесь и заводим запись на правку соответствующего дока.

---

## Глобальные блокеры и решения

_Сюда выносим то, что касается всего проекта (закончился бюджет API, упал Railway, переехали с Chroma на Qdrant и т.п.)._

- _пока пусто_

## Документация требует правок

- **PRD 4.4 и TDR 2.6** — после Спринта 1 факты разошлись с описанием API: реальная иерархия резолвится через `parentId` в каталоге, а не через `categoryId/sectionId` из `/api/1/article`; все 518 статей имеют `url` (PRD заявлял «1 без URL»); `alias` в ответе article API всегда `null`. Детали в Заметки Спринта 1.
- **ML System Design 2.3** — прогноз размера индекса 42 MB пересмотреть до 68 MB после фактической индексации.
- **PRD F11 (latency)** — метрика «P50 end-to-end ≤ 4 сек» устарела со streaming. Со SSE релевантна декомпозиция: TTFB до пилюль источников (~300ms на проде), TTFB до первого слова лида (~1.5с — Haiku + tool use partial JSON), полное время (P50 5.4с / P95 ~8с на in-domain). Переписать F11 под три отдельные цели вместо одной end-to-end.
- **PRD 7.3 (стоимость)** — «cheap: $0.001–0.002» переписать под фактический setup: **$0.003–0.006 без reranker** (5 чанков ~3700 input + ~400–700 output на Haiku), **$0.001–0.003 с reranker** (top-3 после rerank, ~2200 input). Текущая реализация без reranker даёт $0.0064 на in-domain.
- **PRD 7.2 (Faithfulness ≥ 0.9)** — помечено ⚠️ под пересмотр после Спринта 4 (см. сноску в PRD). Декомпозиция в `docs/eval_results.md` показала: 70% потерь — false-positive judge, 26% — реальные галлюцинации, 4% safety boilerplate. Реалистичный потолок ≈0.80–0.85 после переписывания `FAITHFULNESS_SYSTEM` в Спринте 5. Финальное решение по таргету — после этого.

---

## Спринт 0 — Скелет и инфра

**Статус:** ✅ готов
**Цель:** к концу спринта на Vercel-ссылке открывается интерфейс, при сабмите приходит mock-ответ от живого Railway. Все грабли деплоя пойманы на пустом каркасе.

### Задачи

- [x] Репозиторий: папки `frontend/`, `backend/`, `data/`, `scripts/`, `docs/`
- [x] PRD, TDR, ML System Design, этот план положены в `docs/`
- [x] FastAPI-скелет с `/health` и заглушками `/search`, `/answer`
- [x] Локальный прогон бэка: `uvicorn` поднимается, `/health` отвечает
- [x] Vite + React скелет, html-прототип положен как `frontend/public/legacy-prototype.html` (референс)
- [x] Локальный прогон фронта: `npm run dev` показывает минимальный UI
- [x] End-to-end локально: фронт стучится в `localhost:8000`, получает заглушку
- [x] Railway-проект для бэка, persistent volume подключён (`/data`)
- [x] Vercel-проект для фронта
- [x] Домены работают: `https://avi-help.vercel.app`, `https://avi-help-production.up.railway.app`
- [x] Env-переменные: `VITE_API_BASE_URL` (Vercel), `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`ADMIN_TOKEN` (Railway)
- [x] End-to-end на проде: Vercel → Railway, заглушка возвращается
- [x] Проверка persistent volume на Railway: создан тестовый файл, рестарт, файл на месте (тот же timestamp)
- [x] CORS сужен до `localhost:5173` + `avi-help.vercel.app`
- [x] Тестовые volume-ручки удалены из кода

### Заметки

- **Домены отличаются от того, что в TDR.** TDR упоминает `avi-help-api.up.railway.app`, по факту имя сервиса — `avi-help-production.up.railway.app`. Поправить TDR при следующей правке (не критично).
- **Python 3.12 в venv через Homebrew.** Системный Python 3.13 на маке не используем — алиас `python3` → `python3.12` живёт в `.zshrc`. Алиас перебивает venv: `which python` показывает путь алиаса, не venv. Внутри venv использовать `python` без тройки или прямой путь `.venv/bin/python`. На Railway зафиксировано через `runtime.txt` → `python-3.12`.
- **Railway monorepo gotcha.** Railpack не понимает корень репо без `requirements.txt`. Решение: в Settings → Source → Root Directory поставить `backend`. Без этого билд падает с `Railpack could not determine how to build the app`.
- **Два environment автоматом.** Railway сразу создал `cheerful-analysis` и `focused-freedom`. Второй удалён через Settings → Danger Zone, чтобы GitHub не копил красные крестики на странице Deployments.
- **Тестовые ручки `/admin/test-volume-write` и `/admin/test-volume-read`** были временными для проверки persistent volume — удалены из `main.py` после успешной проверки. `VOLUME_PATH = "/data"` оставлен как константа для Chroma в Спринте 1.
- **Минимальный UI на React** (поле ввода + fetch к `/answer`) — для Спринта 0 хватает. Полноценный UI из прототипа собираем в Спринте 3.

### Блокеры

- _пока пусто_

---

## Спринт 1 — Данные и индекс (M1, M2)

**Статус:** ✅ готов
**Цель:** локально работает Chroma с 518 статьями, можно вручную дёрнуть похожие чанки по запросу. Покрытие ≥98% (G2) проверено.

### Задачи

- [x] Скрипт парсера на `httpx + asyncio + Semaphore(8)`
- [x] Получение каталога через `/api/1/getCatalog`, выборка `typeId=4` (518 id)
- [x] Дёрганье `/api/1/article` на каждый id, сохранение в `data/articles_raw.jsonl`
- [x] Парсер HTML-фрагмента из `body` через BeautifulSoup
- [x] Разбор структурных тегов: `<headline>`, `<spoiler>`, `<tabset>`, `<factoid>`
- [x] Структурный chunker: ~5200 чанков по ~250 токенов
- [x] Резолв `categoryId`/`sectionId` в человекочитаемые названия из каталога
- [x] Финальный артефакт `data/articles.jsonl` с метаданными (`article_id`, `article_url`, `title`, `category`, `section`, `lastmod`, `chunk_text`)
- [x] Edge case: статья без URL — лог + пропуск
- [x] Артефакт `articles.jsonl` закоммичен в репо
- [x] Скрипт индексации: embeddings через `text-embedding-3-small`
- [x] Chroma на диске, payload каждого чанка с метаданными
- [x] Проверка: ручной запрос к Chroma возвращает осмысленные чанки
- [x] Покрытие ≥98% (≥510 из 518) — посчитано и зафиксировано

### Метрики на выходе

- Количество статей в `articles.jsonl`: **518** (100% покрытие, цель ≥510 выполнена)
- Количество чанков: **4288** (после cap; до cap было 5046)
- Размер индекса (MB): **68 MB** (sqlite 45 MB + HNSW 23 MB)
- Стоимость индексации ($): **$0.0224** (1 122 096 токенов × $0.02/1M)
- Время полного парсинга: **4.9s** (PRD заявлял 1–2 мин — оказалось радикально быстрее)

### Заметки

**Технические решения по чанкингу:**

- **Cap `MAX_CHUNKS_PER_ARTICLE = 50`** на статью. Без cap артикл 2924 «Какими товарами интересуются покупатели» давал 614 чанков (12% всего индекса) — длинные tab-блоки со списками товаров по 6 городам. После cap 2924 = 1.2% индекса. Cap сработал на 8 статьях (2924, 4321, 4243, 4220, 4266, 4234, 2095, 4307). Берём первые N — это вступление + первая категорийная вкладка.
- **Заголовок статьи добавляется в начало каждого чанка** (`<title>\n<header>\n<body>`). Усиливает retrieval (запрос матчится по слову из title) и спасает короткие статьи на 1 параграф от попадания в <100 токенов.
- **Иерархия сплитов:** `<headline>` → секция; >400 токенов → split по параграфам; параграф один и >400 → split по предложениям; предложение одно (плоская таблица) → hard-split по токенам. Hard-split сработал на 11 чанках (списки товаров без пунктуации).
- **Префиксы спецблоков inline:** `[Раскрывающийся блок: <title>]` для spoilers, `[Важно: ...]` для factoids, `[Вкладка: <name>]` для tabset (каждая вкладка отдельным чанком).
- **`section` опционален** (None у 68 статей из 518 — они висят прямо под категорией без секции). Это нормальная структура каталога, не баг — обработано явно.

**Метрики vs прогноз:**

- Парсинг 4.9s vs прогноз 1–2 мин (PRD 4.4). Сетевая задержка из РФ оказалась минимальной.
- Стоимость $0.0224 vs прогноз $0.025 (ML-design 2.3). Очень точное попадание после применения cap.
- Размер индекса 68 MB vs прогноз 42 MB (ML-design 2.3). Расхождение из-за HNSW-индекса Chroma — embeddings + sqlite metadata + отдельный HNSW. На Railway 8GB volume это всё ещё <1%.
- Время индексации 2:11 (131s) vs прогноз 3–5 мин — быстрее.
- Распределение токенов: P50=279, P95=411, P99=461, max=524 — внутри требований (P50 200–300, P95 ≤500).

**Расхождения с PRD/TDR:**

- **`categoryId/sectionId` в `/api/1/article` ≠ catalog node id.** На 518 статей всего 3 уникальных значения у каждого поля — это что-то внутреннее (видимо, owner team). PRD 4.4 и TDR 2.6 говорили «резолвим через каталог» — реально иерархия только через `parentId` в catalog node. Каждая нода каталога: `id, parentId, title, url, typeId, isInfoPage`. typeId 1=категория, 2=секция, 4=статья.
- **Все 518 статей имеют `url` в каталоге** — PRD 4.4 утверждал «1 без URL». В текущей версии данных это не подтверждается. URL формат `/articles/{id}`, всегда выводимый.
- **`alias` в ответе `/api/1/article` всегда `null`** для всех 518. Использовать его для построения URL невозможно. Берём `url` из catalog node.
- **68 из 518 статей (13%) не имеют секции** — висят на категории напрямую. PRD/TDR говорили о фиксированной иерархии «категория → секция → статья» — реально секция опциональна.

**Content gap (не баг retrieval, а структура БЗ Авито):**

- На запрос «как разместить объявление» retrieval возвращает фуззи top-3 (адреса для объявлений, временно снять, разместить вакансию). Канонический кандидат — статья 4371 «Размещаю новое объявление» — не попала в top-10.
- Причина: в support.avito.ru **нет универсальной статьи «как опубликовать объявление с нуля»**. Категория «Как опубликовать объявление: самые важные советы» существует, но статьи в ней привязаны к доменам (Авто, Путешествия, Недвижимость). Article 4371 содержательно — про спецификации авто-полей (Указать VIN, Заменить автомобиль, Авто под заказ).
- Sanity-варианты подтверждают: «как опубликовать первое объявление» начинает попадать в правильную категорию, «как подать объявление» вытаскивает «Пройти модерацию» с куском «Подать объявление пошагово».
- На самом саппорте Авито поиск тоже размытый — это структура контента, не RAG-баг. План: для eval-набора Спринта 4 формулировать запросы про размещение конкретно по категориям; в Спринте 2 рассмотреть промпт-фоллбэк «если top-3 разбежались по категориям — отвечать «выберите категорию» + перечень».

### Блокеры

- _пока пусто_

---

## Спринт 2 — Retrieval и Generation (M3, M4)

**Статус:** ✅ готов
**Цель:** через curl на проде задаёшь вопрос — получаешь осмысленный JSON с цитатами. G1 фактически достигнут на уровне API.

### Задачи

- [x] Ручка `/search`: запрос → embedding → Chroma top-K → JSON со списком чанков и скорами
- [x] Системный промпт для генерации (правила цитирования, отказ на out-of-domain, fallback)
- [x] Tool use схема: `lead`, `sections[]`, `sources_used[]`
- [x] Ручка `/answer`: retrieval → контекст → Claude Haiku → парсинг tool use
- [x] Валидация: все `sources_used` есть в выданных чанках
- [x] Постпроцессинг: при ссылке на несуществующий чанк — лог + fallback
- [x] Промпт-усиление по категории «Безопасность» (top-3 чанка из категории → предупреждение про SMS)
- [x] Fallback при низких скорах retrieval (стартовый порог 0.3)
- [x] Флаг `MODEL=sonnet` для будущих сравнений (через env `MODEL`, дефолт `claude-haiku-4-5`)
- [x] Проверка на проде: 5–10 ручных запросов через curl, ответы осмысленные
- [x] Streaming SSE для `/answer` + non-streaming `/answer/sync` (вытащено из Спринта 5 S1)
- [x] Bootstrap Chroma на Railway volume через GitHub release + `BOOTSTRAP_CHROMA_URL` env (вытащено из ранее не описанной задачи деплоя)

### Решения, которые надо зафиксировать по ходу

- [x] Финальный `chunk_size` — оставлен как был в Спринте 1 (структурный, после cap=50 чанков на статью); ablation в Спринте 5
- [x] Финальный `top-K` для retrieval — **5** по умолчанию
- [x] Финальный порог отсечения — **0.3** на top-1 score (подтверждён эмпирически: OOD `0.263`, in-domain ≥ `0.485`)
- [x] Стартовая модель — **Haiku** (`claude-haiku-4-5`)

### Заметки

**Блок 1 — Retrieval:**
- Сделал: модуль `backend/retrieval.py` (`SearchHit`, `search`, `embed_query`, `get_chroma_collection`, `warmup`) + ручка `/search` с pydantic-валидацией; cwd-независимый резолв пути к Chroma (`CHROMA_PATH` env → `<repo>/data/chroma`).
- Получил: latency `/search` 190–500ms на тёплом, 1.4s на холодном (init OpenAI client); 3 sanity-запроса из Спринта 1 воспроизводятся 1-в-1, content gap «как разместить объявление» подтверждён.
- Важно: один outlier OpenAI embedding на 5.7s в ручных пробах → поставил `OpenAI(timeout=8.0, max_retries=1)`. Без таймаута P95 спорадически уезжал бы за 6 секунд.

**Блок 2 — Generation:**
- Сделал: `backend/generation.py` + `backend/prompts.py`, ручка `/answer` через Anthropic tool use (`tool_choice` форс), валидация sources_used, pre-LLM fallback на `top-1 < 0.3`, safety-priming по категории «Безопасность» в топ-3.
- Получил: ~$0.0034 за запрос в среднем (5 запросов, 2 в pre-LLM fallback) → $3.4 за 1k, $3.4k за 1M, в пределах цели PRD ≤$0.005; latency 180–268ms на pre-LLM fallback, 2.8–6s на LLM-пути; нет invented chunk_id; на «как опубликовать первое объявление» модель сама ставит is_fallback=true и при этом даёт валидную секцию + источники — паттерн «грамотная неуверенность», подсветить на демо.
- Важно: safety-priming по category="Безопасность" не сработал на «звонят и просят код из смс» (retrieval вернул «Профиль», статья «Что-то с телефоном или смс»). Модель угадала, но это удача — TODO для Спринта 4: расширить триггер по ключевым словам запроса (код / sms / звонят / ссылка / перевод), false negatives здесь хуже false positives.

**Блок 3 — Streaming (SSE):**
- Сделал: `generate_stream` (AsyncAnthropic + partial-json-parser для дельт лида), ручка `/answer` → `StreamingResponse(text/event-stream)` с `Cache-Control: no-cache` и `X-Accel-Buffering: no`; non-streaming перенесён в `/answer/sync`; pre-LLM fallback и safety-priming работают по тем же правилам, что и в блоке 2.
- Получил: TTFB meta = 308ms, первый lead_delta = 1842ms; safety-кейс «звонят с поддельной ссылкой» начинает lead с шаблона из `SAFETY_PRIMING` (топ-3 категория Безопасность); CORS preflight 200, заголовки на месте; `/answer/sync` без регрессий; OOD-запросы дают 3 события (meta+lead_delta+done) с `usage: 0/0`.
- Важно: TTFB после `meta` ≈ 1.5с против цели ≤1с — задержка Haiku до момента, когда partial-JSON содержит непустое поле lead, не дефект парсинга. Стратегия стрима: дельты лида (через `partial-json-parser`) + целые секции после закрытия tool_use, не дроблю массив sections (sliding-парсер по массиву усложнил бы код без UX-выигрыша). Если TTFB критичен — варианты для Спринта 5: ручной парсер по сырому JSON `"lead": "...`, либо text-output без tool use со вторым structured-call.

**Блок 4 — Деплой на прод:**
- Сделал: bootstrap-логика в `main.py` (download tar.gz из `BOOTSTRAP_CHROMA_URL` если `/data/chroma` пуст, идемпотентно); GitHub release `chroma-v1` с архивом 44 MB (sha256 `d21e08d5…`); commit + push → Railway auto-deploy; накатили env `CHROMA_PATH=/data/chroma` и `BOOTSTRAP_CHROMA_URL=…/chroma-v1/chroma.tar.gz`; CORS уже сужен с Спринта 0.
- Получил: 4/4 prod-ручки проходят с первого опроса; на 5 in-domain запросах `/answer/sync` — avg 5502ms, P50 5444ms, max 7863ms; usage 18955 in / 2632 out → **$0.00642/запрос**, экстраполяция 1k=$6.4, 1M=$6.4k; SSE на проде даёт 32 события на safety-кейсе (lead начинается с предупреждения про SMS).
- Важно: (1) **Self-healing бутстрап** — `data/chroma/` остаётся в `.gitignore`, артефакт лежит как public GitHub release; если volume сломается, индекс восстановится сам при следующем рестарте. Управляется через env, ноль ручного аплоада. (2) **Метрика latency P50≤4с устарела со streaming** — со SSE надо мерить в декомпозиции: TTFB до пилюль (~300ms), TTFB до первого слова (~1.5с), полное время (P50 5.4с / P95 ~8с). Со streaming пользователь видит пилюли через 300ms — на UX это не «5 секунд тишины». (3) **Стоимость $0.0064/запрос (in-domain)** — на остаток бюджета $15 = ~2330 запросов; для собеса (демо + eval ~100 запросов) хватает многократно. Оптимизация через reranker + кэш — Спринт 5. (4) **P95 на 5 запросах нерепрезентативен** — запрос #2 (safety, 7.7с) единичная точка; нормальный замер P95 будет на eval-сете 30–50 запросов в Спринте 4.

### Блокеры

- _пока пусто_

---

## Спринт 3 — Фронт и интеграция (M5, M6)

**Статус:** ✅ готов
**Цель:** G1 в чистом виде — открыл Vercel-ссылку, спросил, получил ответ. Демо можно показывать.
**Демо:** https://avi-help.vercel.app/

### Задачи

- [x] `getAnswer(query)` заменён на `fetch(/api/answer)` — `frontend/src/api.js`, POST `/answer/sync`
- [x] Парсинг ответа API в существующую структуру `{lead, source, sections}` — нормализация в `api.js` (`article_url`→`url`, рекорды source/section/lastmod как есть)
- [x] Пилюли источников: реальная категория Авито + `lastmod` («обновлено N мес назад») — `SourceCluster` + `SourcePopover` подключены к живым данным
- [x] Стейт ошибки сети — читаемое сообщение (`ErrorState` с типами `network`/`timeout`/`http`/`parse`/`warming`, retry через `lastQueryRef`)
- [x] Стейт «retrieval ничего не нашёл» — отдельный визуал (`FallbackState`), срабатывает на `is_fallback: true`
- [x] CORS прогнан, фронт→бэк работает — 3/3 sanity-запроса на проде curl-ом успешны; allowed_origins содержит `avi-help.vercel.app`
- [x] Кнопки фидбека 👍/👎 — POST в заглушку `/feedback` (бэк-stub отвечает 204; полное JSONL-логирование в Спринте 4)
- [x] Проверка с мобильного устройства — DevTools mobile-аудит (44px touch targets, overflow-wrap, ErrorState side margins на узком viewport); ручной DevTools-прогон подтверждён пользователем
- [x] Финальный деплой, ссылки работают — Vercel автодеплой из main, прод стабилен на `https://avi-help.vercel.app/`, бэк на `https://avi-help-production.up.railway.app/`

### Сводка

- React + Vite + CSS-модули, 17 компонентов; без Tailwind/Next.js/TypeScript.
- Дизайн по Google AI Overview: один inline-кластер источников + portal-popover, серые скрепка-бейджи у всех ссылок.
- SSE через `fetch + ReadableStream` (без `EventSource` — он только GET); pacing на бэке через `asyncio.sleep` против Anthropic-SDK batching.
- Streaming-polish: chunk fade-in (blur+opacity per delta) + `SectionsSkeleton` shimmer + cursor glyph `▍`. Реальный стрим секций не сделан — закрыт скелетоном.
- `/feedback` bare-stub (204), JSONL-логирование — Спринт 4.
- Smoke 5/5 на проде по всем категориям; OOD-fallback 128мс без LLM-вызова.

### Заметки

**Блок 1 — Декомпозиция прототипа в React:**
- Сделал: 17 React-компонентов, `App.jsx` стейт-менеджер, `theme.css` с CSS-переменными, mocks для отладки.
- Получил: build 459мс, JS 70 KB gzip; mobile-first вёрстка ≤480 → 1 кол / ≥1024 → 4 кол.
- Важно: mocks.js + DevPanel — временные, удалить в блоке 2 (риск показать fake на демо).

**Блок 1.5 — UI по референсу Google AI Overview:**
- Сделал: переделала источники на inline `SourceCluster` + portal-`SourcePopover`, без дублирующей полоски пилюль под лидом.
- Получил: JS +3 KB gzip к блоку 1, lint clean.
- Важно: `useSyncExternalStore` для подписок (React 19 запрещает синхронный setState из useEffect); `data-source-marker` атрибут чтобы pointerdown не закрывал popover на самом маркере (race close→open).

**Блок 2 — Подключение реального API через /answer/sync:**
- Сделал: `api.js` (`getAnswer`, `ApiError` с типами network/timeout/http/parse/warming/abort), react-markdown в Section, удалила mocks.js + DevPanel.
- Получил: 3/3 sanity-curl на проде; bundle +35 KB gzip от react-markdown.
- Важно: первый запрос после простоя = 503 warming (Chroma cold init на Railway), ловим как `type:"warming"` с жёлтым плакатом; локальный Vite на :5174 режется CORS'ом (allowed_origins только :5173).

**Блок 3 — SSE-стриминг через POST /answer:**
- Сделал: `streamAnswer` через fetch+ReadableStream; `App.jsx` на useReducer + AbortController; кластер источников появляется после первого предложения лида.
- Получил: TTFB первой дельты ~1.5с, полный ответ ~4с in-domain, pre-LLM fallback ~290мс.
- Важно: AbortError на новом запросе reducer должен **игнорировать** (return state) — иначе старые `lead_delta` дописываются в новый ответ.

**Блок 3.5 — Стриминг-polish и UI-выравнивания:**
- Сделал: бэк-пейсинг через `asyncio.sleep(0.02)` после `yield lead_delta`; один `<AnswerCard>` поверх streaming→answer (нет remount-вспышки); chunk fade-in + skeleton + cursor glyph; align card width = input width 640px; paperclip-бейджи.
- Получил: на проде дельты с gap 20мс, секции 80мс — пейсинг работает идеально; коммиты `8a3a3a7..b615ecf`.
- Важно: Anthropic SDK даёт пачки 5-10 событий per HTTP-chunk (источник буфера, не наш баг); реального стрима секций нет, закрыт skeleton-pattern Google; root `.gitignore` был Python-шаблоном и съедал `frontend/src/lib/` (исправлено `!frontend/src/lib/`).

**Блок 4 — Фидбек 👍/👎 + edge cases:**
- Сделал: бэк-stub `/feedback` (Pydantic, 204, печать в stderr); фронт `submitFeedback` с silent-fail; проводка handleRate → AnswerCard.onRate → FeedbackButtons.
- Получил: curl POST /feedback на проде → HTTP 204; коммит `07d07c7`.
- Важно: silent-fail на /feedback — это спецификация (бэк-stub до Спринта 4); `answer_text` склеивается как `lead + sections.title + body` для будущего LLM-judge.

**Блок 5 — Mobile polish + smoke на проде:**
- Сделал: 44px touch targets (CategoryGrid/ErrorState/FallbackState), `overflow-wrap: anywhere` на лиде/секциях, `lang="ru"`, ErrorState side margins через `width: calc(100% - 2 * var(--pad-x))`.
- Получил: smoke 5/5 на проде — 4 in-domain отвечают релевантно с источниками, OOD «борщ» fallback 128мс без LLM.
- Важно: реальный device-test (визуальный keyboard-overlap, тач-таргеты на живом iPhone) — за пользователем; PRD F11 (P50 ≤4с end-to-end) устарела со стримингом — переписать в декомпозиции TTFB-метрик (отмечено в «Документация требует правок»).

### Блокеры

- _пока пусто_

---

## Спринт 4 — Eval и логи (M7, S2)

**Статус:** ✅ готов
**Цель:** G3 закрыт цифрами в репо, G4 виден из логов токенов, есть из чего смотреть failure cases.

### Задачи

#### Eval

- [x] Golden-set: **100** вопросов руками, для каждого эталонные `article_url` (расширили с 30–50 после прикидки покрытия 16 категорий)
- [x] **20** out-of-domain вопросов для refusal rate (расширили с 10 — по 2 на жанр)
- [x] Кэш LLM-вызовов в `data/llm_cache.jsonl` по хешу `(model, messages, tools, temperature, system)` + параллельно embedding-кэш `data/embedding_cache.jsonl` (для скорости повторных прогонов)
- [x] Скрипт `scripts/eval.py --config <name>` (флаги: `--limit`, `--ood`, `--no-cache`, `--outdir`)
- [x] Метрики retrieval: Recall@5, MRR@10 (с разбивкой по категории и difficulty; content-gap исключены из расчёта)
- [x] Метрики generation: faithfulness и relevance через Sonnet-judge с tool use (`claude-sonnet-4-6`, `--no-judge` для отключения)
- [x] Refusal rate на out-of-domain (через `is_fallback` от модели)
- [x] Конфиги: `mvp` (Haiku + safety-priming), `baseline` (без safety-priming, для ablation в Спринте 5)
- [x] `docs/eval_results.md` с финальной таблицей метрик vs цели, ablation, failure cases, декомпозицией faithfulness и methodological finding (отдельный `compare.py` не понадобился — eval.py пишет summary.json, ablation сделан двумя прогонами с разными `--config`)

#### Логи

- [x] Структурированное логирование в JSONL (`backend/logging_jsonl.py`: ts, request_id, query, retrieval со скорами, is_fallback, model, usage, cost_usd, latency, ip_hash; при ошибке — error_type/error_msg; запись через FastAPI BackgroundTasks)
- [x] `GET /admin/logs?date=&limit=&kind=requests|feedback` за `X-Admin-Token`
- [x] `GET /admin/logs.jsonl?date=&kind=` за `X-Admin-Token` (FileResponse, скачивание)
- [x] `POST /feedback` пишет в `feedback_{date}.jsonl`, фолбэк-id из хеша query+ts если без request_id
- [x] Хеширование IP с солью (`LOG_IP_SALT`, SHA-256 первые 16 hex; без соли — не логируем)

### Цели по метрикам (из PRD)

- Recall@5 ≥ 0.85: **0.8125** ❌ −0.04 (open question Sprint 5: reranker → ожидаем +5-15 п.п.)
- MRR@10 ≥ 0.6: **0.7007** ✅
- Faithfulness ≥ 0.9: **0.4433** ❌ −0.46 (open question Sprint 5: убрать SAFETY_PRIMING +10 п.п. + reranker + переписать judge-prompt)
- Relevance avg ≥ 4: **4.6701** ✅
- Refusal rate = 1.0: **1.0** (20/20) ✅
- Latency P50 ≤ 4 сек: **4.69 сек** ❌ +17% (open question Sprint 5: streaming-декомп + кэш популярных запросов)
- Latency P95 ≤ 8 сек: **7.46 сек** ✅
- Cost per query ≤ $0.005: **$0.0068** in-domain gen-only ❌ +36% (open question Sprint 5: top_k=3 после reranker)

### Заметки

**Блок 1 — Golden-set (100 + 20):**
- Сделал: `data/eval/golden_set.jsonl` 100 in-domain + `data/eval/ood_set.jsonl` 20 OOD; источники — `legacy-prototype.html` CategoryGrid, `catalog_map.json`, `articles.jsonl`; все expected_article_urls резолвятся в `articles.jsonl`, спец-маркер `notes: резюме-работа` для 5 запросов о работе/резюме без отдельной catalog-категории.
- Получил: 100/20 строк, all валидации passed; распределение по bucket'ам ровное (Реклама −1, Связь +1 из-за content-gap g069 «телефон поддержки»→«Связаться с пользователем»); difficulty 60/30/10; safety 6, content-gap 4 (g046, g069, g093, g100), опечаток 10, длинных >100 симв 16; OOD по 2 на 10 жанров.
- Важно: стиль строчный без точки в конце, slang-лексика в каждом 5-м (бабки, обяв, обяву, лк, слила, не пускает, молчит); опечатки настоящие (плучения, сколко, верниите, выделние, пороль) — будем мерить retrieval на user-style формулировках, а не на учебных.

**Блок 2 — Кэш + eval + retrieval-метрики:**
- Сделал: `backend/llm_cache.py` (Anthropic `CachedAnthropic` drop-in + embedding-кэш в `data/embedding_cache.jsonl`), `scripts/eval.py` (--config mvp/baseline, --limit, --ood, --no-cache); фикс `generation.py._normalize_sections` — Haiku иногда возвращает `sections` как JSON-string или ломаный JSON, теперь graceful fallback в []; кэш-стат `cost_paid` vs `cost_rate` различает реально потраченное от рейт-эквивалента.
- Получил: первый прогон 120 запросов = $0.6755 (внутри $0.40-0.80 цели), повторный = $0.0000 / 0.9с (≪60с цели); **Recall@5=0.8125** (n=96, цель ≥0.85 — недобор 0.04), **MRR@10=0.7007** (цель ≥0.6 ✓); OOD refusal **20/20=1.0** (✓); content-gap 2 из 4 ушли в is_fallback (g069, g100), 2 (g046, g093) дали best-effort ответ.
- Важно: 18 worst-Recall-cases — почти все «семантически близкие, но не та статья» (g020 «телефон со сколом» → «Меня обманули» вместо «Приехал повреждённый товар» / g034 «слила доступ → сменить пароль» → «Профиль взломали» вместо «Установить надёжный пароль»); это типичный кандидат для reranker'а в Спринте 5 — baseline без него по дизайну, дельту меряем там.

**Блок 3 — LLM-judge (faithfulness, relevance) + refusal rate:**
- Сделал: `claude-sonnet-4-6`-judge внутри `scripts/eval.py` — два tool-use вызова (faithfulness `is_faithful`+`unsupported_claims`, relevance `score 1-5`+`reasoning`); judge идёт через `CachedAnthropic` (повторный прогон бесплатный), флаг `--no-judge` для прогонов без него; refusal rate считается из `is_fallback` на OOD; стоимость judge выводится отдельной строкой.
- Получил: judge на 100 in-domain × 2 вызова = $1.62 paid / 200 misses, ~10 минут; **faithfulness 0.45** (full) / 0.44 (non-fallback, n=97) — цель ≥0.9 МАССОВЫЙ НЕДОБОР; **relevance avg 4.63** (full) / 4.67 (non-fallback) — цель ≥4 ✓; **refusal rate 1.0** (20/20) ✓; 55/100 unfaithful из них 53 с конкретными unsupported_claims.
- Важно: faithfulness низкая по 3 причинам: (1) reranker отсутствует → retrieval тащит «семантически близкие» статьи, модель отвечает по ним и обобщает → Sonnet ловит «overgeneralization» (например, g003 «15 дней возврата» применено и к ПВЗ хотя только для домашней доставки); (2) `SAFETY_PRIMING` дописывает в lead boilerplate про «не сообщайте код из SMS» — Sonnet корректно флагит как unsupported (g007); (3) Sonnet строгий — нит-пикает мягкие переформулировки. Все 3 причины — вход в Спринт 5 (reranker должен поправить retrieval, safety-priming можно сузить, judge можно ослабить через явные правила).

**Блок 4 — JSONL-логирование + admin-ручки + фидбек:**
- Сделал: `backend/logging_jsonl.py` (Pydantic схемы `RequestLogEntry`/`FeedbackLogEntry`, `hash_ip` через `LOG_IP_SALT`, atomic-ish append с фолбэком в stderr); `main.py` — `request_id=uuid4` на `/answer`+`/answer/sync` (в SSE прокинут через первое `meta`-событие, в sync — поле `request_id` в `AnswerResponse`), запись в `requests_{date}.jsonl` через `BackgroundTasks` (sync) и inline после стрима (SSE), error-путь логируется отдельно; `/feedback` пишет в `feedback_{date}.jsonl`, fallback-id `fb-{sha256(query+ts)[:16]}` если фронт не прислал request_id; admin-ручки `GET /admin/logs?date=&limit=&kind=` (JSON) и `GET /admin/logs.jsonl?date=&kind=` (FileResponse) за `X-Admin-Token`; фронт (api.js + App reducer) ловит `request_id` из meta/sync и шлёт обратно.
- Получил: локальный sanity 5 запросов через curl → ровно 5 строк в `requests_{date}.jsonl`, IP захеширован (16 hex), все поля валидны; SSE-curl полного стрима (21 событие) → 6-я строка в логе с `endpoint=/answer`; `/feedback` с `request_id` → строка в `feedback_{date}.jsonl`; без токена `/admin/logs` → 401, с токеном → JSON со счётчиком и items, `.jsonl`-вариант отдаёт raw-файл; прод-curl SSE→/feedback с тем же request_id отрабатывает 204; fallback `fb-…`-id работает когда `request_id` не пришёл.
- Важно: `LOG_PATH` дефолтит на `<repo>/data/logs` локально, на Railway нужно явно `LOG_PATH=/data/logs` чтобы логи лежали на persistent volume; без `LOG_IP_SALT` `ip_hash=null` (по дизайну — без соли хеш реверсится перебором IPv4); SSE-лог пишется ИНЛАЙНОМ в генераторе (BackgroundTasks в SSE стартует только после закрытия стрима = после генератора, что эквивалентно); словил баг во фронте — `onMeta({sources, is_fallback})` деструктуризацией ронял `request_id` до dispatch, фидбек уходил без id и бэк подставлял `fb-…`-fallback; фикс одной строкой в `App.jsx`.

**Блок 5 — Финальный прогон + ablation + prod latency + eval_results.md:**
- Сделал: финальный mvp-прогон из кэша 1.2с / $0.00 paid; ablation `--config baseline` (без `SAFETY_PRIMING`) — 213с, $0.43 paid (только новые safety-кейсы); 30 sequential prod-curl на `/answer/sync` для P50/P95 latency; `docs/eval_results.md` с таблицами целей, разбивками retrieval/judge, ablation, failure-cases, insights for Sprint 5; обновил «Цели по метрикам» в плане реальными числами.
- Получил: **Recall@5=0.8125** ❌, **MRR@10=0.7007** ✅, **Faithfulness=0.4433** ❌, **Relevance=4.67** ✅, **Refusal=1.0** ✅, **prod P50=4.69с** ❌ (+17%), **P95=7.46с** ✅, **cost/query=$0.0068** in-domain ❌ (+36%); **ablation: baseline без safety-priming → faithfulness +10 п.п.** (0.44 → 0.54), retrieval идентичен, refusal не пострадал.
- Важно: главный кандидат для Спринта 5 — reranker, должен закрыть Recall@5 + снять основные unfaithful-overgeneralizations (model отвечает по неправильным «семантически близким» чанкам); SAFETY_PRIMING можно убрать целиком или сузить до явных query-триггеров (не retrieval-категории) — отыграем +10 п.п. faithfulness без потери refusal; faithfulness target 0.9 нереалистичен на этом judge-промпте даже с лучшим retrieval — Sonnet нит-пикает, нужно переписать FAITHFULNESS_SYSTEM с явным правилом «не флагь мягкие переформулировки если факт верен».

**Блок 5.5 — Декомпозиция faithfulness + methodological finding:**
- Сделал: ручной разбор 10 unfaithful-кейсов из mvp с привязкой к чанкам, категоризация 27 unsupported_claims; нашла отдельный self-contradiction glitch judge'а (g008/g019 — Sonnet помечает каждый claim как «(ок)/подкреплено», но возвращает is_faithful=false); добавила в `eval_results.md` секцию «Methodological finding: LLM-judge inconsistency» с буквальной цитатой tool-output'а g008; переписала «Insights for Sprint 5» в 3-колоночную таблицу Insight/Цена/Эффект; пометила в `docs/01-PRD.md` Faithfulness-target ≥0.9 как ⚠️ под пересмотр со сноской на findings.
- Получил: распределение 27 claims = 70% false-positive judge / 26% реальная галлюцинация / 4% safety boilerplate; реалистичный потолок faithfulness без переписывания judge ≈0.70, с переписанным judge ≈0.80–0.85, цель ≥0.9 нереалистична на этом judge.
- Важно: топ-1 «бесплатное» улучшение для Спринта 5 — переписать `FAITHFULNESS_SYSTEM` (30 мин работы → +25-35 п.п. faithfulness на тех же ответах); цифра 0.45 в репо без этой декомпозиции выглядит как «50% галлюцинаций», что неверно — реальных hallucinations 26% claims.

### Итоговая summary Спринта 4

**Что построено:**
- Eval-фреймворк (`backend/llm_cache.py` + `scripts/eval.py`) — полный прогон 100+20 запросов воспроизводим, повторный = 0$; конфиги `mvp` / `baseline` для ablation; LLM-judge на Sonnet через тот же кэш; разбивка по категории и difficulty.
- Golden-set (100 in-domain + 20 OOD) на user-style формулировках с опечатками и slang'ом — `data/eval/{golden_set,ood_set}.jsonl`.
- Структурированное JSONL-логирование запросов и фидбека (`backend/logging_jsonl.py`) с `request_id`-связкой, IP-хешем, atomic-append, фолбэком в stderr; admin-ручки `GET /admin/logs?date=&kind=&limit=` и `GET /admin/logs.jsonl?date=&kind=` за `X-Admin-Token`; всё на проде.
- `docs/eval_results.md` — главный артефакт спринта для собеса.

**Что узнали:**
- ✅ `MRR@10=0.70`, `Relevance=4.67`, `Refusal=1.0`, `Latency P95=7.5с` — выполнены.
- ❌ `Recall@5=0.81` (vs 0.85), `Faithfulness=0.44` (vs 0.9), `P50=4.7с` (vs 4с), `Cost=$0.0068` (vs $0.005) — недобор.
- Ablation `baseline` без safety-priming: faithfulness **+10 п.п.** (0.44→0.54), retrieval идентичен, refusal не пострадал.
- Декомпозиция faithfulness 0.45: 70% потерь — false-positive judge (нит-пик + buggy is_faithful), 26% — реальные галлюцинации, 4% — safety boilerplate. Реалистичный потолок ≈0.80–0.85 после Спринта 5, ≥0.9 нереалистично.
- Methodological finding: Sonnet-judge возвращает is_faithful=false при claims, помеченных в собственном выводе как «(ок)»/«подкреплено» — отдельный buggy паттерн, не свойство ответов.

**Открытые вопросы → Спринт 5:**
- Reranker `bge-reranker-v2-m3` (топ-1 ROI: Recall@5 +5-15 п.п. + Faithfulness через корректные чанки).
- Переписать `FAITHFULNESS_SYSTEM` (топ-1 «бесплатно»: +25-35 п.п. за 30 мин).
- Сузить `SAFETY_PRIMING` до query-триггеров.
- Top_k=3 после reranker (cost −30%).
- Финальное решение по PRD-таргету Faithfulness — после переписывания judge'а.
- PRD F11 (P50 ≤4с) переписать в декомпозицию TTFB-метрик под streaming.

### Блокеры

- _пока пусто_

---

## Спринт 5 — Технические улучшения по итогам Спринта 4

**Статус:** ✅ готов
**Цель:** довести метрики Sprint 4 baseline до целей PRD путём 4 раздельно измеряемых правок. Главный артефакт — `docs/sprint5_changes_log.md` с декомпозицией «какое изменение что дало».
**Принцип:** один блок = одна правка = один замер = одна запись в журнал. Без исключений.

> Оформление (README, демо-вопросы, чеклист готовности, stretch-эксперименты) перенесено в Спринт 6 — этим спринтом не занимаемся.

### Задачи

- [x] Блок 0 — Подготовка журнала и baseline-снимок
- [x] Блок 1 — Переписать FAITHFULNESS_SYSTEM (judge rewrite + страховочный override) ⚠️ faithfulness 0.6392 на non-fb — на 1.1 п.п. ниже барa приёмки 0.65, обсуждение трейд-оффа
- [x] Блок 2 — Сузить SAFETY_PRIMING до query-триггеров
- [x] Блок 3 — Cross-encoder reranker `bge-reranker-v2-m3` (top-20 → top-5)
- [x] Блок 3.5 — Refusal threshold calibration (0.0 → 0.6125)
- [x] Блок 4 — top_k=3 после reranker (cost/latency) ⚠️ cost $0.00577 — не дотянул до PRD ≤$0.005 на $0.00077, нужно prompt caching (roadmap)
- [x] Блок 5 — Деплой на прод + замер latency ⚠️ reranker откатили (P95=24s на shared CPU → base+10 → Recall@5 пробил stop) → final state = Sprint 4 retrieval + Sprint 5 Блоки 1+2 generation
- [x] Блок 6 — Финальный прогон + декомпозиция + апдейт `eval_results.md`

### Заметки

**Блок 0 — Подготовка журнала:**
- Сделал: создал `docs/sprint5_changes_log.md` со структурой из брифа (Baseline-таблица + failure cases по 5 группам с привязкой к блокам-починщикам + 4 пустых секции изменений + Финальная сводка).
- Получил: Sprint 4 baseline зафиксирован цифрами; failure cases распределены — buggy judge (g008, g019) и нит-пик (g001, g006, g012) → блок 1; safety boilerplate (g007, g020) → блок 2; реальные галлюцинации (g003, g011, g014, g017) и bad retrieval (g002, g020) → блок 3.
- Важно: цель Faithfulness ≥0.9 в журнале явно помечена ⚠️ — финальное решение по таргету откладывается на блок 6 после всех замеров; реалистичный потолок 0.80–0.85 принят как ожидание.

**Блок 1 — Переписан FAITHFULNESS_SYSTEM + override:**
- Сделал: переписан judge-промпт с явным правилом is_faithful, правилом про overgeneralization и двумя few-shots; добавлен страховочный override `_looks_soft` с hard-disqualifier'ами и узкими soft-маркерами; новый режим `--rerun-judge-only [--from-run] [--ids] [--limit]` в `scripts/eval.py` восстанавливает stub'ы hits/result из `results.jsonl` и пересчитывает только judge.
- Получил: Faithfulness (non-fb) 0.4433 → **0.6392** (+19.6 п.п.); g008/g019 ушли (через промпт + override), g006 ушёл, g005 ушёл (override на пустом списке); 22 unfaithful-кейса исчезли (55 → 33); Recall/MRR/Relevance/Refusal без изменений (cache hit на relevance, retrieval не трогали); $1.04 paid вместо $1.6 ожидавшихся.
- Важно: критерий приёмки блока ≥0.65 на non-fb недотянут на 1.1 п.п. — выбран trade-off между v1-override (0.6701, но 4 false-positive override flipped реальные hallucinations g007/g014/g041 в true) и v4 (0.6392, override строго по явным маркерам, raw метрика честная). Sprint 4 baseline 0.4433 в ретроспективе тоже был занижен — судья ложно флагил ~22 кейса. Стоп для обсуждения какой override фиксировать.

**Блок 2 — SAFETY_PRIMING на query-триггеры:**
- Сделал: переписан `_needs_safety_priming(query, hits)` с frozenset-триггерами (22 паттерна с word-boundary через ведущий пробел для « звонит»/« звонят») и анти-триггеров (13: access recovery «сменить пароль» + коды посылок «код получения»); ablation `baseline` lambda обновлена под новый signature.
- Получил: Faithfulness (non-fb) 0.6392 → **0.6907** (+5.15 п.п. vs Блок 1, +24.7 п.п. vs Sprint 4) — выше барa приёмки 0.65; Recall/MRR/Refusal без изменений; g007/g020 ушли (lead'ы без SMS-boilerplate, ответ по делу — «обратитесь в полицию» / «отказаться при доставке»); $0.14 paid (cache hit на 297 из 310 вызовов — большинство ответов не менялись).
- Важно: word-boundary через padded substring (ведущий пробел в триггере + padding query) дешевле regex и поймал 5 false-positive «как позвонить продавцу» на sanity ДО запуска paid eval; g041 «не приходит смс с кодом для входа» остался false (в брифе не целевой) — отказ от анти-триггера «не приходит код» сознательный против overfitting на одиночный кейс.

**Блок 3 — Cross-encoder reranker bge-reranker-v2-m3:**
- Сделал: установил `sentence-transformers` (тянет torch); добавил в `backend/retrieval.py` lazy-init `CrossEncoder` через `get_reranker()` (graceful degradation на bi-encoder если модель не загрузилась); `search()` стал двухступенчатым (Chroma top-20 → reranker → top_k); `warmup()` догружает модель на старте; новый `--config mvp_no_reranker` для ablation; временный `RETRIEVAL_THRESHOLD=0.0` потому что reranker sigmoid scores группируются в полосе 0.5±0.1 (Блок 4 откалибрует).
- Получил: **Recall@5 0.8125 → 0.8854 (+7.29 п.п.)** — закрыта PRD-цель ≥0.85; **MRR@10 0.7007 → 0.7605 (+5.98 п.п.)**; Faithfulness (non-fb) 0.6907 → 0.6562 (−3.45 п.п. от reranker, но cumulative vs Sprint 4 +21.3 п.п.); Refusal rate 1.0 → 0.9 (ood19/ood20 «конкуренты» прошли — побочка `THRESHOLD=0.0`); Relevance +0.04; $2.91 paid (полный rerun, 320 misses из 320).
- Важно: 3 целевых cherry-picked failure cases (g002, g011, g020) НЕ починились — g002 expected URL вообще не в top-20 (content gap), g011/g020 на позициях 14–17 в top-20 но reranker не вытянул в top-5 (короткие/разговорные запросы дают неинформативные logits около 0). Демо-frustration «телефон со сколом» сохранится. Faith-регрессии на g005/g007/g019 — известный side effect правильной retrieval-инвариантности (новые top-5 → новые формулировки ответа → Sonnet находит новые hard claims). Стоп-условия не пробиты, локальная latency ~5с — Блок 5 проверит на проде.

**Блок 3.5 — Refusal threshold calibration (две итерации):**
- Сделал: iteration #1 threshold 0.6125 single-mechanism — был overcorrection, 8 in-domain CORRECT в fallback включая 2 safety и demo-blocker g061; iteration #2 → competitor-list (38 padded-substring маркеров: юла/озон/wb/lamoda/я.маркет/ali/ebay/мегамаркет/drom/лавка/amazon/джум) + threshold понижен до 0.55 в `apply_config('mvp')` и `baseline`.
- Получил: **Refusal rate 1.0** ✓ через 2 механизма (ood19/ood20 ловятся через competitor, остальные 18 OOD через threshold); Recall@5=0.8854 ✓ без изменений; vs iteration #1: Relevance full 4.19→**4.39** (+0.20), n_non_fallback 82→**89** (7 in-domain вернулись в LLM), faithfulness full 0.75→0.70 (искусственный fallback-bonus уменьшился на меньшем числе fallback'ов — это правильно). 5/8 целевых in-domain CORRECT прошли (g025/g032/g036/g052/g055), 3 остались в fallback (g023, g050, g061 — top-1 ниже 0.55); $0.022 paid (288/291 cache hits).
- Важно: g061 demo-blocker НЕ починен (top-1 0.510 < 0.55) — нужна query-нормализация «обяв→объявления» в roadmap; iteration #1→#2 — пример что precision-over-recall (Блок 1 валидированный принцип) требует валидации на конкретных кейсах, слепо «строже всегда лучше» не работает; зафиксированы 2 методологические находки спринта в `sprint5_changes_log.md` Финальная сводка.

**Блок 4 — top_k=3 после reranker:**
- Сделал: `backend/main.py` AnswerRequest top_k default 5→3; `scripts/eval.py` slice `hits[:5]` → `hits[:3]` в вызове `generation.generate`. Retrieval по-прежнему возвращает top_k=10 для метрики MRR@10.
- Получил: **Cost per query $0.0068 → $0.00577 (−15%)** недобор PRD на $0.00077; **Faithfulness non-fb +3.7 п.п. (0.6629→0.7000)**; **Latency локально prod-like P50 6068→5148ms (−15%) P95 9199→7143ms (−22%)** — ожидание −10% превышено; Recall@5/MRR@10/Refusal без изменений ✓; Relevance non-fb −0.12 (минор регрессия); input tokens avg 3985→3353 (−16%), output 514→483 (−6%); $2.47 paid (полный rerun, 271/291 misses).
- Важно: PRD-цель cost $0.005 нереалистична на текущей архитектуре — system_prompt (~600) + tool definition (~900) = ~1500 токенов фиксированный input + ~750 чанки + ~500 output → потолок $0.0058 без prompt caching; roadmap-кандидат — Anthropic prompt caching на system+tool (TTL 5 мин, −90% cached input). Cumulative cost/latency-эффект Sprint 5 — весь от блока 4 (reranker нейтрален по cost, добавляет +1.5s к retrieval компенсируется −19% generation).

**Блок 5 — Деплой на прод + reality check (полный путь v2-m3 → base+10 → откат):**
- Сделал: 3 деплоя за день — (1) v2-m3+20 как было; (2) base+10 (Variant 2) + hotfix Pydantic int_from_float в `last_search_timings`; (3) откат reranker `USE_RERANKER=false` + threshold 0.55→0.3 + top_k 3→5; финальный eval rerun из cache ($0 paid, 308/308 hits).
- Получил: P95 24.27s (v2-m3) → 9.66s (base+10, Recall@5 пробил stop 0.80<0.83) → **7.32s ✓ PRD ≤8s**; финальный Recall@5 0.8125 = Sprint 4 baseline (reranker не дожил), **Faithfulness 0.6907** на non-fb (+24.7 п.п. от Блоков 1+2), Refusal 1.0 ✓, Cost ~$0.0068 (top_k=5 вернул input avg 3985); $2.46 paid за base+10 eval.
- Важно: главный win Sprint 5 — Faithfulness через judge rewrite + safety priming (Блоки 1+2, независимы от reranker). Reranker оставлен в коде как opt-in opt-flag на dedicated CPU; Блок 4 cost/latency-выигрыш потерян вместе с reranker'ом (top_k=3 без фильтра релевантности теряет контекст). Two методолог. находки добавлены в журнал: pre-deployment latency-замер на target hardware ОБЯЗАТЕЛЕН, и Pydantic v2 не coerces float→int с fractional part — каждое изменение response schema требует curl smoke на ВСЕ endpoints его использующие.

**Блок 6 — Финальная сводка + апдейт `eval_results.md`:**
- Сделал: заполнил Финальную сводку в `sprint5_changes_log.md` (cumulative-таблица + декомпозиция по блокам + 5 методологических находок + roadmap); переписал `eval_results.md` целиком под Sprint 5 final (главная таблица, latency-декомпозиция в 4 точках, failure cases, predictions vs outcomes, PRD revision секция, roadmap Sprint 6+).
- Получил: финальные цифры зафиксированы — Recall@5/MRR/Refusal/Latency P95/Relevance ✓ либо на baseline; Faithfulness +24.7 п.п. cumulative win; всего $9.04 paid за весь спринт (остаток $5.96 от $15 бюджета).
- Важно: PRD-revision открыта по 3 пунктам (F11 latency → streaming-декомпозиция, 7.2 Faithfulness ≥0.7 вместо ≥0.9, 7.3 Cost ≤$0.007 вместо ≤$0.005 ИЛИ только через prompt caching как roadmap); реранкер оставлен в коде opt-in под `USE_RERANKER=true` на dedicated CPU; топ-1 roadmap-кандидат для Sprint 6 — Anthropic prompt caching на system+tool (~1500 input tokens fixed) для попадания в cost-цель.

### Блокеры

- _пока пусто_

---

## Открытые вопросы (решаем по ходу)

_Из PRD раздел 9 + добавляем своё._

- [ ] Конкретный threshold для retrieval fallback (стартовая гипотеза 0.3)
- [ ] Финальный `chunk_size` (стартово 600, ablation после прогона eval)
- [ ] Делать ли ablation с `text-embedding-3-large`, если стартовый MVP покажет Recall@5 > 0.9
- [ ] На eval-наборе в Спринте 4 переформулировать общие запросы про размещение под конкретные категории (например, вместо «как разместить объявление» → «как опубликовать объявление о квартире», «как подать объявление о работе»). Причина — content gap в БЗ Авито (см. Заметки Спринта 1), не размытость запроса.
- [ ] **Реальный стрим секций** (per-char через расширение partial-json-parser на массив объектов) vs текущий skeleton-pattern Google AI Overview. Сейчас закрыто скелетоном — UX'но норм, но если рекрутер на демо спросит «почему секции прыгают целиком» — есть готовый рассказ про trade-off (см. Заметки Спринт 3 блок 3.5). Делать только если останется время на Спринте 5.
- [ ] **Расширить safety-priming триггер** по ключевым словам запроса (код / sms / звонят / ссылка / перевод), не только по category top-3 retrieval (TODO из блока 2 Спринта 2 — на «звонят и просят код из смс» категория «Профиль» возвращается, не «Безопасность», safety-priming угадал по другой логике). Делать в Спринте 5 после eval, чтобы померить false positives/negatives.
- [ ] **Sticky-hover на тач-устройствах** — 17 hover-стилей не обёрнуты в `@media (hover: hover)`. Терпимо, но если на eval/Спринте 5 будет окно — оборачиваю одним проходом по всем `*.module.css`.
- [ ] **bundle 343 KB JS / 107 KB gzip** — в основном `react-markdown` + `remark` + `unified` (~35 KB gzip). Если на mobile metrics увидим медленный first paint на Slow 3G — варианты: `marked` (~10 KB) или вернуться к самописному markdown-рендеру.
- [ ] **PRD F11 (latency) переписать** под streaming-декомпозицию — отмечено в «Документация требует правок» в начале файла. P50 4.5с end-to-end больше не релевантно как единая метрика.
