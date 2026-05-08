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

### Сводка спринта

**Что сделано в сумме за Спринт 3:**

1. **17-компонентный React-фронт** (`frontend/src/components/`) поверх Vite + CSS-модули + `theme.css`. Никакого Tailwind/Next.js, всё на классическом CSS-подходе. React 19, lucide-react для иконок, react-markdown для тела секций.
2. **Дизайн по референсу Google AI Overview**: один inline-кластер источников после первого предложения лида + popover на клик (portal в body, fixed-positioning с flip), без дублирующей полоски пилюль. Бейджи источников унифицированы — серый кружок со скрепкой `Paperclip` для всех ссылок.
3. **API-проводка** через `api.js`: `getAnswer` (sync через `/answer/sync`), `streamAnswer` (SSE через `/answer`), `submitFeedback` (POST `/feedback`). Класс `ApiError` с типами `network/timeout/http/parse/warming/abort`. 30с timeout через `AbortController`, отдельная ветка для 503 → жёлтый «Бэкенд прогревается» плакат.
4. **SSE-стриминг** через `fetch + ReadableStream + TextDecoder` (без `EventSource` — он только GET). Собственный SSE-парсер с поддержкой `\n\n` и `\r\n\r\n`. `App.jsx` на `useReducer` (action-ы START/META/LEAD_DELTA/SECTION/DONE/SYNC_OK/ERROR/CLOSE), `AbortController` для cancel предыдущего стрима при новом запросе.
5. **Бэк-пейсинг SSE** (блок 3.5 после реального UX-замера): `await asyncio.sleep(0.02)` после `yield lead_delta`, `0.08` после `section`. Без этого Anthropic-пачки 5-10 событий бандлились uvicorn'ом в один TCP-segment → пользователь видел «бух весь параграф». Замер на проде: 25 дельт по 20мс gap, секции с 80мс gap.
6. **Streaming-polish UX** в стиле Google AI Overview: каждый delta-chunk лида рендерится отдельным `<span>` с CSS-анимацией `blur(4px)→0 + opacity 0→1` за 220мс (эффект «текст в фокус»); `SectionsSkeleton` (4 shimmer-полосы) на месте секций пока они генерятся; курсор-glyph `▍` (full-block character, мигает 0.9с). Один `<AnswerCard>` поверх перехода streaming→answer (без unmount/remount → нет повторного запуска `appear`-анимации).
7. **Edge cases** покрыты: пустой инпут (`disabled`), maxLength 200, network/timeout/503/fallback (через `ApiError` + `ErrorState`/`FallbackState`), CategoryGrid → авто-сабмит. Никаких mocks.js / DevPanel / console.log в финальном коде.
8. **Mobile-полировка**: 44px touch-targets на CategoryGrid/ErrorState/FallbackState; `overflow-wrap: anywhere` на `.lead` и `.section` против длинных URL; `<html lang="ru">`; ErrorState side margins через `width: calc(100% - 2 * var(--pad-x))`.
9. **Backend stub `/feedback`**: Pydantic-схема `FeedbackRequest` (`rating: ^(up|down)$`), статус 204, печать в stderr для дебага. JSONL-логирование оставлено на Спринт 4.
10. **Smoke 5/5 на проде** (curl): возврат денег / SMS-код безопасность / резюме / вход в аккаунт / out-of-domain — все категории отвечают релевантно, fallback срабатывает за 128мс без LLM-вызова.

**Цели PRD:**
- ✅ **G1** (working e2e RAG на проде) — выполнено, демо `https://avi-help.vercel.app/`
- ✅ **M5** (фронт-интеграция) — выполнено
- ✅ **M6** (деплой) — Vercel + Railway работают

**Ключевой UX-trade-off:** Реального стрима секций нет — Anthropic шлёт их одним блоком после закрытия tool_use, дробить массив объектов через partial-json-parser сложно. Закрыто скелетоном (Google-pattern) — пока секции готовятся, юзер видит shimmer вместо пустоты. Реальный per-char стрим секций — отдельная фича на Спринт 5 если важно.

**Заметки по блокам ниже** — детальные Сделал/Получил/Важно для каждого блока в порядке выполнения.

### Заметки

**Блок 1 — Декомпозиция прототипа в React:**
- Сделал: 17 компонентов в `frontend/src/components/` (Header, Tabs, Hero, SearchInput, AnswerCard, Section, SourcePill+SourceList, ExpandButton, FeedbackButtons, LoadingState, ErrorState, FallbackState, CategoryGrid, SupportBlock, Footer, ScrollTopButton, Toast, DevPanel) + `App.jsx` стейт-менеджер + `theme.css` с CSS-переменными + `mocks.js` с 4 фикс-вариантами (success-short / success-long / fallback / error) + `utils/date.js` (formatLastmod c русской плюрализацией) + `lib/toast.js` (pub-sub).
- Получил: `npm run build` 459ms, 1770 модулей, JS 221 KB / 70 KB gzip, CSS 17 KB / 4 KB gzip; `npm run lint` чистый; dev-сервер поднимается на `localhost:5174`. Mobile-first вёрстка: padding 20px, 1 колонка категорий, шрифт инпутов 16px (Safari не зумит); desktop через `@media (min-width: 720/1024/1280)` расширяет до 4 колонок и `pad-x: 40px`.
- Важно: (1) **mocks.js + DevPanel — временные**, удалить целиком в блоке 2 при подключении `api.js`, иначе риск что демо случайно покажет fake-ответ из словаря. (2) **`SourcePill` цвет буквы — hash от категории**, не один primary как в прототипе — пилюли визуально разделяются когда их несколько в ряд. (3) Markdown в `Section` пока самописный (`**bold**` + списки `- `) — в блоке 2 заменю на `react-markdown` чтобы корректно рендерить `section.body` от LLM. (4) **CSS-модули** выбраны над глобальным CSS: scope-изоляция, нет рантайм-зависимости (vs styled-components), переменные дизайн-токенов в одном `theme.css`.

**Блок 1.5 — UI-фиксы по референсу Google AI Overview:**
- Сделал: переделал источники на «как у Google» — один inline-кластер `[<буква категории>] <название первой статьи> +N` после первого предложения лида (компонент `SourceCluster`); клик открывает `SourcePopover` (320px, portal в body, fixed-positioning с flip когда не помещается, закрытие на Escape/scroll/resize/click-outside) со списком всех источников кластера, каждая карточка — целиком кликабельный `<a target="_blank">` с badge + title (clamp 2 строками) + категория · обновлено N мес назад + иконка ↗. Удалил дублирующую полоску пилюль под лидом и старый `SourceMarker`/`SourcePill`. Также: скрыл декоративные табы на ≤480px, кнопка «Поиск» в disabled теперь голубая с opacity 0.55 (не серая), placeholder инпута укорочен на ≤480px через `useMediaQuery`-хук («Например: возврат денег» вместо длинного).
- Получил: build 152ms, JS 225 KB / 71 KB gzip (+3 KB к до-фиксов блока 1), CSS 19.5 KB / 4.3 KB gzip; lint clean.
- Важно: (1) **`useSyncExternalStore` для подписок** (`useMediaQuery`, `lib/sourcePopover`) — react-hooks/set-state-in-effect lint-правило в React 19 запрещает синхронный setState из useEffect; это идиоматичный путь без лишних рендеров. (2) **Поповер позиционируется через прямой `ref.current.style`** в `useLayoutEffect`, не через React state — нет лишнего рендер-цикла между измерением и финальным placement'ом; на смену кластера используется `key={clusterId}` для принудительного ремаунта DOM-узла, чтобы не мигало старой позицией. (3) **`data-source-marker` атрибут** на пилюле кластера — `pointerdown` listener в SourcePopover проверяет `closest("[data-source-marker]")` и не закрывает поповер, когда тапаешь по самому маркеру (иначе будет race: pointerdown→close→click→open).

**Блок 2 — Подключение реального API через /answer/sync:**
- Сделал: `frontend/src/api.js` — `getAnswer(query, { signal, top_k })` через POST `/answer/sync`, 30-секундный timeout через `AbortController`, класс `ApiError` с типами `network`/`timeout`/`http`/`parse`/`warming`/`abort`, отдельная ветка для 503 → `type: "warming"`; нормализация ответа (`article_url`→`url`, дефолты для `section`/`lastmod`/`is_fallback`). `Section` теперь рендерится через `react-markdown` с маппингом `p/ul/ol/li/strong/em/a/code` (default schema без raw HTML — безопасно), ссылки `target="_blank" rel="noopener noreferrer"`. `ErrorState` получил вариант `warming` (жёлтый фон `--color-warn-bg`, иконка `Loader`, текст «Бэкенд только что разогрелся после простоя…»). `App.jsx` переключён на живой fetch: loading → `answer`/`fallback`/`error` по `is_fallback` и `err.type`, retry через `lastQueryRef` (последняя query сохранена даже после очистки инпута), защита от двойного сабмита через `view.kind === "loading"` early return. Удалил `mocks.js` и `DevPanel.jsx`/`.module.css` — никаких фейковых ответов в коде.
- Получил: 3/3 sanity-запроса на проде через curl: (1) «как вернуть деньги» → `is_fallback: false`, лид + 3 секции (Остаток денег в кошельке / Деньги за объявление или заказ / Как проверить баланс), 2 источника (Частые вопросы / Заказы с доставкой), `latency_ms.total = 6937`; (2) «как сварить борщ» → `is_fallback: true`, типовой лид «По этому запросу не нашлось…», 0 секций, 0 источников, 190мс (pre-LLM fallback по low score, как и заявлено в Спринте 2); (3) «звонят и просят код из смс» → лид начинается с «Никогда не сообщайте код из смс никому…» (safety priming сработал на категории «Профиль», статья 4221), 1 источник. Build: JS 339 KB / 106 KB gzip (+35 KB gzip к блоку 1.5 — это `react-markdown` + remark + unified), CSS 20 KB / 4.5 KB gzip. Lint clean.
- Важно: (1) **CORS allowed_origins на бэке** = `http://localhost:5173,https://avi-help.vercel.app`. Локальный `npm run dev` должен запускаться именно на 5173 — если порт занят (например, висит старый Vite), Vite берёт 5174 и запросы к прод-API режутся CORS-ом. На Vercel-домене всё ок. Альтернатива для локалки — поднять локальный uvicorn на :8000 и направить `VITE_API_BASE_URL=http://localhost:8000` (там CORS по дефолту). (2) **react-markdown bundle overhead +35 KB gzip** — терпимо для 60-секундного первого визита, но если в Спринте 5 надо ужать (PRD G1 «<8 сек» — это про LLM-latency, не про bundle, всё равно стоит мониторить mobile metrics) — варианты `marked` (~10 KB) или вернуться к самописному. (3) **На проде раз в первый запрос после тишины срабатывает 503** — Chroma init на холодном Railway. Mы это явно отлавливаем как `type: "warming"` с мягким жёлтым плакатом. Retry через 30 сек обычно даёт 200. (4) **bundle 339 KB JS — не блокер для G1**, но Vercel прогревает edge-cache, и реальный first-paint на mobile 4G ~1с после прогрева.

**Блок 3 — SSE-стриминг через POST /answer:**
- Сделал: `streamAnswer(query, callbacks)` в `frontend/src/api.js` через `fetch + ReadableStream + TextDecoder` (без `EventSource` — он только GET, не умеет POST с body); собственный SSE-парсер с поддержкой `\n\n` и `\r\n\r\n` (на случай прокси-переноса CRLF), пропуск SSE-комментов `:`, опциональный пробел после `data:`. Колбэки `onMeta` / `onLeadDelta` / `onSection` / `onDone` / `onError` + опции `signal` (внешний AbortSignal) и `top_k`. `App.jsx` переписан на `useReducer` (action-ы START/META/LEAD_DELTA/SECTION/DONE/SYNC_OK/ERROR/CLOSE) — лид аккумулируется через `lead + action.text`, секции пушатся в массив, источники из `meta` сохраняются и могут быть перезаписаны финальными из `done`. Отдельный `streamCtrlRef` в `useRef` хранит `AbortController` текущего стрима — на новый запрос вызывается `streamCtrlRef.current.abort()` до старта следующего, на unmount — cleanup. View-rendering: `streaming` с `lead === ""` → `LoadingState` (stage `thinking`/`writing` зависит от того, пришла ли уже meta), `streaming` с непустым лидом → `AnswerCard streaming` (мигающий курсор в конце лида, `FeedbackButtons` скрыты до done), на DONE при `is_fallback=true` и пустых sources → `FallbackState` с накопленным лидом. Тумблер `VITE_USE_SYNC=1` оставляет старый sync-путь через `getAnswer` (для отладки UI без stream-парсера) — по умолчанию stream.
- Получил: 3/3 stream sanity-запроса на проде показывают ожидаемую последовательность:
  - **«как вернуть деньги»**: meta @ 256ms (4 sources, is_fallback=false) → первая lead_delta @ 1534ms («Спо») → 23 deltas пачками по 1-10 символов → 3 sections и done @ 4057ms (3 sources after dedup, 543 output_tokens, model claude-haiku-4-5).
  - **«как сварить борщ»**: meta @ 287ms (sources=0, is_fallback=true) → 1 lead_delta с типовым сообщением → done @ 287ms (pre-LLM fallback, мгновенно). Здесь между мета и done нет промежуточных deltas — после первой dispatch'ит `kind: "fallback"`.
  - **«звонят с поддельной ссылкой»**: meta @ 495ms (4 sources) → первая delta @ 2413ms («Ав» — safety priming сработал, лид начинается с «Авито никогда не…») → 35 deltas → 2 секции и done @ 5006ms. Проверил, что `sources_used=2 / sources=1` (LLM сослался на 2 chunk_id из одной статьи, бэк дедуплицирует по `article_id`).
  - Build: JS 341 KB / 107 KB gzip (+1 KB к блоку 2 — компактный stream-парсер), CSS 20 KB / 4.5 KB gzip. Lint clean.
- Важно: (1) **`AbortController` cancel при новом запросе** — `streamAnswer` ловит `AbortError` и шлёт `onError({ type: "abort" })`, reducer этот тип игнорирует (return state) — старый стрим тихо умирает, новый стартует с чистого state через `START`. Без этого старые `lead_delta`-ивенты дописывались бы в новый ответ. (2) **Safari mobile streaming buffering** — бэк уже шлёт `X-Accel-Buffering: no` и первое событие `meta` ~300 байт (4 sources × ~70 байт), этого хватает чтобы Safari не накапливал. Если в реальном тесте на iPhone (Блок 5) увидим задержку >2с до первого `meta` — добавлю padding на бэке: `:padding: <2KB пробелов>\n\n` перед первым SSE-событием. **Со стороны фронта обходов нет** — только серверная инициатива. (3) **На fallback-запросе видна короткая «вспышка»** AnswerCard streaming с типовым лидом за ~250ms до переключения на FallbackState на DONE. Не критично визуально, но если сделать UX чище — в reducer на META при `is_fallback=true && sources=[]` сразу dispatch'ить `FALLBACK_PRE` и не накапливать лид. Оставил, эффект <300ms незаметен. (4) **Источник-кластер появляется только когда есть первое предложение лида** (`renderLeadWithCluster` ищет первую `[.!?]\s` и вставляет `SourceCluster`). До этого пользователь видит только LoadingState. Это значит TTFB для пилюли источников ≈ TTFB первой lead_delta = 1.5-2с, а не 250-500ms как было бы при полоске под лидом. Компромисс осознанный — ради дизайн-фикса 1.5 (только inline-кластер, без дублирования). Если в Блоке 4/5 пользователь захочет «источники сразу» — можно добавить мини-индикатор в LoadingState («Найдено N источников»). (5) **Тумблер `VITE_USE_SYNC=1`** в `.env.local` переключает на `/answer/sync`. Удобно когда нужно дебажить UI без race condition'ов стрима.

**Блок 3.5 — Стриминг-polish и UI-выравнивания (после первого UX-прогона блоков 1-3):**
- Сделал: (а) **Запушила всё что висело локально** — Спринт 3 блоки 1-3 не были закоммичены, прод отдавал старый минимальный UI Спринта 0; коммиты `8a3a3a7` (фронт целиком) + `d012ccb` (фикс корневого `.gitignore`: правило Python `lib/` ловило `frontend/src/lib/`, добавила исключение). (б) **Бэк-пейсинг SSE** — Anthropic SDK выдаёт `content_block_delta` пачками 5-10 событий per HTTP-chunk, uvicorn в одном tick'е event-loop'а бандлил socket-writes в один TCP-segment → пользователь видел «бух весь параграф» вместо печати. Замер на проде через python: было 5 TCP-чанков с дельтами 0мс внутри пачки. Добавила `await asyncio.sleep(0.02)` после `yield lead_delta` и `await asyncio.sleep(0.08)` после `yield section` — после фикса 25 дельт по 20мс gap, секции с 80-85мс gap. Заголовок `Cache-Control` дополнен `no-transform`. (в) **AnswerCard remount fix** — при DONE state менялся streaming→answer, в App.jsx это были два разных условных блока с `<AnswerCard>` → React размонтировал и монтировал заново → CSS `appear` keyframe (350мс fade-in) запускался повторно («обновление»). Заменила на один `<AnswerCard>` с условным `answer` source и `streaming={view.kind === "streaming"}`. Также: `isLong` (fade + кнопка «Развернуть») отключила пока streaming=true — иначе при пересечении 600 знаков посреди стрима хвост секций схлопывался. (г) **Lead chunk fade-in** — reducer теперь хранит `leadChunks: string[]` параллельно с `lead`, каждый delta-chunk рендерится отдельным `<span>` с CSS-анимацией `opacity 0+blur(4px) → 1+blur(0)` за 220мс. Эффект «текст приходит в фокус» как у новых ChatGPT/Gemini. Bold-разметка во время стрима не парсится — редкое явление в лидах. (д) **`SectionsSkeleton`** — 4 анимированные shimmer-полосы 92/84/75/68% (background-position infinite linear), показывается пока `streaming && sections.length === 0` — светятся в паузу ~1.7с между последней `lead_delta` и первой `section`, дальше плавно подменяются реальными секциями с fade-in (`sectionAppear: opacity 0+translateY 8px → 1+0`, 320мс). (е) **Курсор-glyph** — заменила пустой `<span>` 2px-палочку на `<span>▍</span>` full-block character. Цвет `--color-accent`, мигание `blink 0.9s steps(2,start) infinite`. Условие отрисовки `streaming && answer.lead` — на fallback с пустым лидом не появляется. (ж) **Выравнивание ширины** — `--content-max: 644px` → `640px` (= `--hero-search-max`), `.card`/`.wrap` max-width теперь `calc(var(--content-max) + 2 * var(--pad-x))`. Видимый текст в карточке = 640px = ширине инпута, визуально стыкуются как одна колонка. (з) **Бейджи источников унифицированы** — раньше первая буква категории на цветном фоне (палитра 6 цветов через hash), теперь у всех серый кружок со скрепкой (`Paperclip` из lucide). Убрала путаницу «что значит буква П».
- Получил: на проде через python sniff `+2124ms first lead_delta → 25 deltas с gap 19-22мс → 4313ms first section → gap 85ms → done @ 4481ms` — пейсинг работает идеально. Build: JS 342 KB / 107 KB gzip, CSS 21.5 KB / 4.8 KB gzip. Все коммиты: `8a3a3a7`, `d012ccb`, `479dc34` (бэк-пейсинг), `489ebc9` (remount fix), `82d0aaf` (chunk-fade + skeleton + cursor glyph), `8edb6c6` (выравнивание ширины), `b615ecf` (paperclip badges).
- Важно: (1) **Дельты в лиде стримятся реально, секции — НЕТ** (приходят целиком после tool_use закрыт). Прошлый агент сознательно решил не дроблить sections (sliding-парсер по массиву JSON сложнее). UX-trade-off закрыт скелетоном — пока секции готовятся, пользователь видит shimmer вместо пустоты, в момент готовности секции плавно проявляются. Реальный per-char стрим секций — отдельная фича в Спринте 5 если важно. (2) **Стоимость пейсинга**: ~0.5с к total latency (25 дельт × 20мс), TTFB не меняется. (3) **Корневой `.gitignore`** был сгенерён для Python и содержал `lib/` (под venv). Это съедало `frontend/src/lib/`. Исключение `!frontend/src/lib/` зафиксировано — на будущее не наступать. (4) `prefers-reduced-motion: reduce` поддержан во всех новых анимациях (chunk, skeleton, section, cursor) — отключаются.

**Блок 4 — Фидбек 👍/👎 + edge cases:**
- Сделал: бэк — добавила stub-ручку `POST /feedback` (status 204, печать в stderr с rating, sources_used, query[:80] для дебага), Pydantic-схема `FeedbackRequest` валидирует `rating: ^(up|down)$`, длины полей ограничены (query 500, answer_text 20K, sources_used 20 элементов). Спринт 4 заменит на запись в JSONL + хеш IP. Фронт — `submitFeedback({query, answer_text, sources_used, rating})` в `api.js` с 6с timeout, swallows все ошибки (404/network/timeout) → возвращает bool, UI не зависит от ответа. `App.handleRate` собирает payload (`answer_text` = lead + sections.title + sections.body склеенные), пробрасывается через `AnswerCard.onRate` в `FeedbackButtons`. Сам `FeedbackButtons` уже умел toggle `rated` state и `disabled` обе кнопки после клика — только подключила колбэк. Edge cases — все уже были закрыты в блоках 2-3, проверила: пустой инпут (`disabled={!v.trim()}` в SearchInput), maxLength=200, сетевая/timeout/503/fallback (ApiError + ErrorState/FallbackState), CategoryGrid → `pickAndShow` авто-сабмит. Mocks/DevPanel/console.log — `grep` чисто, в коде ничего не осталось.
- Получил: curl на проде `POST /feedback` → **HTTP 204** (`content-type: application/json`, `server: railway-edge`). Build: JS 343 KB / 107 KB gzip (+0.5 KB к блоку 3.5), CSS 21.5 KB / 4.8 KB gzip. Lint clean. Коммит `07d07c7`.
- Важно: (1) **На фронте silent-fail при ошибке /feedback** — это спецификация блока 4 (заглушка пока на бэке). Сейчас бэк отвечает 204, но если в Спринте 4 валидация сменится и начнёт давать 422 на каких-то запросах — UI всё равно покажет «отправлено», только лог потеряется. Не баг, осознанный trade-off. (2) **answer_text склейка** — `lead\n\nsection.title\nsection.body` — формат удобный для последующего LLM-judge или ручной разметки в Спринте 4 eval. Bold-разметку `**...**` не вычищаем — пусть остаётся как есть, judge её игнорирует. (3) **maxLength=200 vs backend max_length=500** — фронт жёстче бэка осознанно: 200 символов хватает на любой осмысленный support-вопрос, не даём пользователю писать роман в надежде на LLM-обзор. Backend держит 500 как запас на случай если когда-нибудь сделаем «расширенный режим». (4) **Edge cases требуют ручной проверки** в DevTools: Network offline → ErrorState retry; «как сварить борщ» → FallbackState (вычитал в логе блока 2: pre-LLM fallback по low score). Финальный smoke-чеклист соберём в блоке 5.

**Блок 5 — Mobile polish + smoke на проде:**
- Сделал: код-аудит мобильных паттернов и точечные фиксы (`06d89fe`). (а) **Touch targets 44px** — `CategoryGrid .itemBtn` 36→44, `ErrorState .retry` 36→44, `FallbackState .supportLink` 36→44 (Apple HIG требует минимум 44px). 16 категорийных чипсов — главный сценарий демо, должны тапаться без промахов. (б) **`overflow-wrap: anywhere`** в `AnswerCard .lead` и `Section .section` — длинный URL или непереносимое слово (chunk_id, доменный термин) не должен ломать layout на 375px-viewport iPhone SE. (в) **`<html lang>`** en→ru для accessibility/SEO. (г) `font-size: 16px` на input — уже было, Safari не зумит. (д) Hover-стили (17 правил) **оставила** — sticky hover на тачах терпим, оборачивать всё в `@media (hover: hover)` — оверкилл для MVP; UI после тапа выглядит «нажатым», что скорее помогает чем мешает. Smoke 5/5 на проде через curl — все запросы из плана прошли успешно (см. ниже).
- Получил: **5 smoke-запросов на `/answer/sync`** — все валидные:
  - **«как вернуть деньги»** → 2 секции, 2 источника (Частые вопросы / Заказы с доставкой), 4.1с total.
  - **«звонят и просят код из смс»** → safety priming в лиде («Никогда не сообщайте код…»), 2 секции, 1 источник (Профиль), 5.1с.
  - **«как опубликовать резюме»** → 3 секции, источник «Составить резюме» из «Мои объявления», 4.5с.
  - **«не получается войти»** → 3 секции, источник «Другие проблемы при входе» из «Профиль», 4.7с.
  - **«как сварить борщ»** → `is_fallback: true`, 0 секций, 0 источников, **128мс** (pre-LLM fallback по low score, токены не тратим).
  - Build: JS 343 KB / 107 KB gzip, CSS 21.5 KB / 4.8 KB gzip. Lint clean.
- Важно: (1) **Реальный mobile-test остаётся за пользователем** — Chrome DevTools toggle device, плюс желательно живой iPhone/Android. Я могу проверить layout-математику и smoke на API, но визуальный тест keyboard-overlap, scroll-performance, SourceCluster+Popover на тач — только глазами. (2) **Slow 3G троттлинг** — bundle 107 KB gzip, на 400 kbps первый paint ~3с, потом всё кэшируется. Это терпимо. SSE-стрим уязвим к реальному jitter — но `X-Accel-Buffering: no` на бэке + chunk-парсер на фронте умеют работать с потерянными границами `\n\n`. (3) **Хост-prefix demo-вопросов**: 4 in-domain из 5 ответили без fallback'а; «как опубликовать резюме» — попал чётко в статью 2195, content gap из Спринта 1 («как разместить объявление» в общем виде ничего не находит) обходится конкретной формулировкой. На демо лучше использовать конкретные категории. (4) **Latency P50 ≈ 4.5с end-to-end** vs PRD цель ≤4с — со стримингом это «время до полного ответа», а TTFB до пилюль источников ~300мс и до первого слова лида ~1.5-2с. PRD F11 требует переписать (отмечено в Документация требует правок).

### Блокеры

- _пока пусто_

---

## Спринт 4 — Eval и логи (M7, S2)

**Статус:** не начат
**Цель:** G3 закрыт цифрами в репо, G4 виден из логов токенов, есть из чего смотреть failure cases.

### Задачи

#### Eval

- [ ] Golden-set: 30–50 вопросов руками, для каждого эталонные `article_url`
- [ ] 10 out-of-domain вопросов для refusal rate
- [ ] Кэш LLM-вызовов в `data/llm_cache.jsonl` по хешу `(model, prompt_hash)`
- [ ] Скрипт `scripts/eval.py --config <name>`
- [ ] Метрики retrieval: Recall@5, MRR@10
- [ ] Метрики generation: faithfulness и relevance через Sonnet-judge с tool use
- [ ] Refusal rate на out-of-domain
- [ ] Конфиги: `mvp` (Haiku), `baseline` (без промпт-усиления)
- [ ] `scripts/compare.py` → `docs/eval_results.md` с финальной таблицей

#### Логи

- [ ] Структурированное логирование в JSONL (timestamp, query, retrieval со скорами, ответ, latency по шагам, токены, стоимость, хеш IP, фидбек)
- [ ] `GET /admin/logs` за `X-Admin-Token`
- [ ] `GET /admin/logs.jsonl` за `X-Admin-Token`
- [ ] `POST /feedback` пишет в лог-систему
- [ ] Хеширование IP с солью

### Цели по метрикам (из PRD)

- Recall@5 ≥ 0.85: _результат_
- MRR@10 ≥ 0.6: _результат_
- Faithfulness ≥ 0.9: _результат_
- Relevance avg ≥ 4: _результат_
- Refusal rate = 1.0: _результат_
- Latency P50 ≤ 4 сек: _результат_
- Latency P95 ≤ 8 сек: _результат_
- Cost per query ≤ $0.005: _результат_

### Заметки

- _пока пусто_

### Блокеры

- _пока пусто_

---

## Спринт 5 — Оформление и stretch

**Статус:** не начат
**Цель:** G5 — все артефакты на месте, демо-ссылка работает, в репо есть таблица сравнений конфигов.
**Принцип:** пункты сверху вниз по приоритету. Если время поджимает — режем снизу.

### Must (оформление)

- [ ] README с архитектурной диаграммой
- [ ] README: метрики из eval, стоимость на 1k и 1M запросов
- [ ] README: инструкция запуска
- [ ] Страница `/about` или раздел в README: «что бы я сделал на 6-й день / на 30-й день»
- [ ] 3–5 готовых демо-вопросов
- [ ] Финальный прогон чеклиста готовности (PRD раздел 10)

### Should (если останется время)

- [ ] S1. Стриминг ответа (SSE) — текст по словам
- [ ] S3. Reranker — bge-reranker или второй проход через LLM по top-20
- [ ] S4. Кэш ответов на популярные запросы

### Stretch-эксперименты (каждый = +1 пункт на собесе)

- [ ] Haiku vs Sonnet vs Opus на eval-сете (~30 мин с кэшем)
- [ ] Ablation по `chunk_size` 300/600/1000 (~1 ч)
- [ ] HyDE как опциональный шаг (~1.5 ч)
- [ ] Multi-query expansion (~1 ч)

### Заметки

- _пока пусто_

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
