# TDR: А-Помощь — техническое решение

**Статус:** Draft v9
**Автор:** [я]
**Дата:** 2026-05-07
**Связанные документы:** `01-PRD.md`, `03-ML-System-Design.md`, `04-Plan.md` (будет позже)

**Изменения v9:**
- **Парсер: переход с playwright на JSON API** (раздел 2.6, 1.3, 10). Найден внутренний API `support.avito.ru/api/1/article` и `/api/1/getCatalog`, отдающий тот же HTML-фрагмент с теми же тегами (`<headline>`, `<spoiler>`, `<tabset>`, `<factoid>`), но в JSON-обёртке. Проверено: 40 параллельных запросов с конкуррентностью 8 — все 200, ~25 мс на запрос, без auth и rate-limit. Стек парсера: `httpx` + `asyncio` + `Semaphore(8)`. Время полного парсинга: 1–2 минуты вместо 30–60. Chunker (BeautifulSoup) — без изменений.
- **Объём контента:** 518 статей (фактический `typeId=4` из catalog API), не ~705 как считалось из sitemap. Sitemap включал ещё категории и разделы. Прикидка чанков: ~5200 (вместо ~6000), индекс ~42 MB.
- Раздел 6.3 (обновление): GitHub Actions раз в неделю снова возможен (нет Chromium, образ помещается в CI). Но IP-блокировка для серверов вне РФ остаётся — нужна VPS в РФ.
- Раздел 10 (риски): убраны риски «playwright тайм-аутит», «Авито банит локальный IP» — их больше нет. Добавлен риск «API внутренний, может измениться» с явной митигацией (playwright-фолбэк за ~2 часа).
- Раздел 6.1 (что где живёт): размер `articles.jsonl` пересчитан под фактический объём.

**Изменения v8:**
- Парсер: playwright это default, не fallback (раздел 2.6, 1.3, 10). После анализа реальных страниц подтверждено: support.avito.ru — это SPA, `requests + bs4` отдаёт пустой каркас (~3KB вместо ~90KB). Никакого «попробуем requests, если не сработает — playwright» — сразу playwright.
- Уточнена прикидка числа чанков: ~6000 на 705 статей (после анализа структуры реальных страниц), не ~3500 как считалось ранее (разделы 2.2, 6.1, 7.5). Объём индекса ~50MB вместо ~5MB.
- Стратегия chunking в кратком описании (раздел 7.4) обновлена — теперь учитывает реальную структуру support.avito.ru с тегами `<headline>`, `<spoiler>`, `<tabset>`. Детали в ML System Design.
- Раздел 0 и 1.1 — фронт описан как Vite + React (а не «статичный»).
- Раздел 6.4 — формулировка про Railway-план приведена в соответствие с актуальным (8GB, не $5 Hobby).
- Раздел 7.1 — гипотезы про latency Haiku/Sonnet помечены как требующие подтверждения в eval.
- Раздел 10 — риски «сломанный HTML» заменён на актуальные риски парсинга через playwright (тайм-ауты, блокировки).

**Изменения v7:**
- Обновлены домены деплоя: фронт `https://avi-help.vercel.app`, бэк `https://avi-help-api.up.railway.app`.

**Изменения v6:**
- Reranker зафиксирован как MUST-компонент (раздел 2.5, 7.2). Feature flag `USE_RERANKER` остаётся, но его назначение — A/B-сравнение в eval и дебаг, не «отключим если медленно».
- Embeddings: явный отказ от локальных моделей (BGE-M3, multilingual-e5) из-за слабого качества на русском справочном контенте. Используем OpenAI text-embedding-3-small. Локальные эмбеддеры — только в roadmap, после fine-tune под домен.

**Изменения v5:**
- Уточнён реальный план Railway: 8GB RAM, 8 vCPU, 100GB shared disk (не дефолтный $5 Hobby, как я предполагал ранее).
- Снят тревожный тон вокруг памяти reranker (~700MB на 8GB-плане это <10%).
- В обосновании выбора embeddings уточнено: BGE-M3 локально жизнеспособен на текущем плане, отказались по другим причинам (cold start, валидация на русском). Не из-за RAM.
- Снят пункт «Fly.io как план Б» — Railway даёт достаточный запас.

**Изменения v4:**
- Переименование папок репозитория: `web/` → `frontend/`, `api/` → `backend/`. URL-пути API (`/api/answer` и т.п.) остались без изменений.

**Изменения v3:**
- Фронт переписываем на Vite + React (раздел 2.7). Статичный html на Vercel — плохая идея на практике; Vite-проект Vercel понимает из коробки.
- Структура `frontend/` обновлена под стандартное Vite-дерево (раздел 3).
- Env-переменная фронта переехала в `VITE_API_BASE_URL` (раздел 6.2).

**Изменения v2:**
- Добавлен раздел 5 — структурированное логирование запросов/ответов в JSONL. Это MUST.
- Логируем: timestamp, query, retrieval-список с скорами, ответ, latency по шагам, токены, стоимость, хеш IP, фидбек.
- Эндпоинты `GET /admin/logs` и `GET /admin/logs.jsonl` для просмотра, защита через `X-Admin-Token`.
- Privacy: IP хешируется с солью, чанки в логах не пишем (только id/title).
- `POST /feedback` теперь часть лог-системы, а не отдельная SHOULD-фича.

---

## 0. Кратко

FastAPI-бэкенд на Railway, Vite + React фронт на Vercel, Chroma как векторная БД на диске Railway. Парсинг через внутренний JSON API support.avito.ru (`httpx + asyncio`) — однократный скрипт с локальной машины, результат коммитится в репо. Все технические решения принимаются из расчёта на 5 дней разработки и бюджет $15 на API.

## 1. Архитектура системы

### 1.1. Компоненты (логические)

```
┌─────────────────┐      ┌──────────────────┐
│  Vercel         │ HTTPS│   Railway        │
│  (Vite + React  │─────▶│   FastAPI        │
│   bundle)       │      │   Chroma (диск)  │
└─────────────────┘      └────────┬─────────┘
                                  │
                                  ▼ HTTPS
                         ┌──────────────────┐
                         │  OpenAI API      │
                         │  (embeddings)    │
                         └──────────────────┘
                                  │
                                  ▼ HTTPS
                         ┌──────────────────┐
                         │  Anthropic API   │
                         │  (Claude Haiku)  │
                         └──────────────────┘

Off-line (один раз на локальной машине):
┌─────────────────┐
│ scripts/        │
│ parse_sitemap → │
│ parse_articles →│
│ build_index     │
└────────┬────────┘
         │ commit
         ▼
   data/articles.jsonl   ←  индексируется при старте API
```

### 1.2. Поток запроса (online)

1. Пользователь печатает вопрос → жмёт «Спросить» в UI на Vercel.
2. Браузер делает `POST /answer` на Railway-домен (с CORS-разрешением для Vercel-домена).
3. FastAPI-хендлер:
   - валидирует ввод (длина, не пустой);
   - получает embedding запроса через OpenAI (~150ms);
   - делает `chroma.query(top_k=20)` (~10ms, локально на диске);
   - **если включён reranker** — переупорядочивает 20 чанков, оставляет 5 топовых (~200ms на CPU);
   - формирует промпт: системка + 5 чанков + вопрос пользователя;
   - вызывает Claude Haiku 4.5 (~2–4 сек, стриминг);
   - постпроцессинг: парсит ответ в `{lead, sections, sources}`;
   - возвращает JSON в браузер.
4. UI парсит ответ → подставляет в существующую карточку прототипа.

### 1.3. Поток индексации (offline)

1. `scripts/fetch_catalog.py` → `POST https://support.avito.ru/api/1/getCatalog` с `{}` → возвращает 604 узла (16 категорий + 70 разделов + 518 статей). Сохраняем в `data/catalog.json` для построения иерархии «категория / раздел / статья».
2. `scripts/parse_articles.py` → асинхронно через `httpx + asyncio + Semaphore(8)` дёргает `POST /api/1/article` с `{"id": <id>}` для каждой из 518 статей. Из ответа берём `title`, `body` (HTML-фрагмент с `<headline>`, `<spoiler>`, `<tabset>`, `<factoid>`), `categoryId`, `sectionId`, `alias`. Парсим `body` через BeautifulSoup. Резолвим `categoryId/sectionId` в человекочитаемые названия через каталог. Пишем в `data/articles.jsonl`.
3. `scripts/build_index.py` → читает `articles.jsonl` → режет на чанки по стратегии из ML System Design → embeddings через OpenAI batch → пишет в `data/chroma/` (sqlite-файл).
4. Railway деплой → API при старте читает `data/chroma/` с диска (volume mount).

**Время на полный парсинг:** **1–2 минуты** на все 518 статей (~25 мс на запрос при конкуррентности 8). Это разовая операция, делается с локальной машины. Подробнее про API — раздел 2.6.

### 1.4. Что НЕ в архитектуре (намеренно)

- Нет очередей (Redis Queue, RabbitMQ) — синхронный API достаточен, нагрузки нет.
- Нет отдельной БД для логов — Postgres на Railway добавим только если делаем S2 (логи фидбека). Иначе логи в stdout.
- Нет CDN перед API — фронт уже на Vercel CDN, API не отдаёт статику.
- Нет authentication — публичное демо.

## 2. Технологический стек и обоснование

### 2.1. Бэкенд: Python 3.11 + FastAPI

**Почему Python:**
- Все ML/RAG-библиотеки нативно живут здесь (chromadb, sentence-transformers, openai, anthropic).
- Я уверенно пишу на Python.

**Почему FastAPI** (а не Flask/Django):
- Нативная поддержка async — нужно для стриминга ответа от Claude и параллельных вызовов.
- Pydantic-валидация запросов — бесплатные схемы для request/response.
- OpenAPI-спека генерится сама → удобно показать на собесе и тестировать через `/docs`.

### 2.2. Векторная БД: Chroma (на диске)

**Альтернативы рассматривал:**
- Qdrant Cloud free tier — добавляет внешнюю зависимость и сетевой хоп.
- Pinecone — платный.
- Qdrant on Railway — отдельный контейнер, сложнее деплой.
- pgvector — нужен Postgres, оверхед под маленький объём.
- FAISS — нет персистентности из коробки, надо пилить.

**Выбираю Chroma** потому что:
- Sqlite-бэкенд = один файл на диске, легко бэкапить и переносить.
- Метаданные хранятся рядом (JSON-payload у каждого вектора) — не нужна вторая БД.
- Объём данных небольшой: ~5200 чанков × 1536 dim × 4 байта ≈ 32MB эмбеддингов + ~10MB на текст и метаданные ≈ **~42MB на диске**. Sqlite справится играючи.
- Нативно на Python, никаких внешних сервисов.

**Минус, который принимаю:** Chroma не масштабируется на десятки миллионов векторов — но это вообще не наша задача. В roadmap «через 1–2 месяца» переезжаем на Qdrant/pgvector.

### 2.3. Embeddings: OpenAI text-embedding-3-small

**Альтернативы:**
- OpenAI text-embedding-3-large — в 6x дороже, прирост качества 1–2% на этой задаче не оправдывает.
- BGE-M3 / multilingual-e5-large локально — **отказались**. По опыту работают плохо на русском справочном контенте (формальный язык, специфичная лексика домена), retrieval-качество ниже text-embedding-3-small. RAM на 8GB-плане позволяет, но качество не оправдывает.
- Cohere multilingual — отдельный аккаунт и оплата.

**Выбираем text-embedding-3-small** потому что:
- 1536 измерений, $0.02/1M токенов — копейки.
- Хорошо работает на русском (multi-lingual из коробки, проверено на похожих задачах).
- Тот же провайдер что у меня уже есть API-ключ — на одну зависимость меньше.
- Нет cold-start-проблемы.

**Когда стоит вернуться к локальным моделям:** только при наличии собственного fine-tuned-эмбеддера, обученного на парах (вопрос пользователя → статья БЗ). Это roadmap-пункт «через 3–6 месяцев», после сбора реальных логов. До этого — OpenAI.

### 2.4. Генеративная модель: Claude Haiku 4.5

**Цены на момент написания (проверены в web):**
- Haiku 4.5: $1 / $5 за 1M input/output токенов.
- Sonnet 4.6: $3 / $15.
- Opus 4.7: $5 / $25.

**Выбираю Haiku 4.5 по дефолту** потому что:
- Быстрее в 2–3 раза — критично для UX (P50 ≤4 сек).
- В 3 раза дешевле Sonnet — в 5 раз дешевле Opus.
- На простой задаче «суммировать 5 чанков и ответить по ним» — близкое качество к Sonnet (по бенчмаркам Anthropic).

**Sonnet оставляю как опцию через query-параметр** `?model=sonnet`:
- Полезно для сравнения в eval.
- На собесе можно показать «вот что меняется на разных моделях».

**Не делаю:** Opus как опцию. Для саммари по чанкам — оверкилл, на собесе хочется показать здравый смысл, а не дороже-значит-лучше.

### 2.5. Reranker: bge-reranker-v2-m3

**Решено:** reranker — обязательный компонент пайплайна (MUST). См. подробное обоснование в 7.2.

**Зачем нужен:**
- Cosine similarity на embeddings часто промахивается — два чанка могут быть «похожи по словам», но один отвечает на вопрос, другой нет.
- Reranker берёт топ-20 от retrieval, считает crossencoder-score «вопрос ↔ чанк» и переупорядочивает. Качество retrieval растёт на 5–15% (померяем точно в eval, ML System Design).

**Почему именно bge-reranker-v2-m3:**
- Multilingual, хорошо работает на русском.
- Маленький (~600–700MB), запускается на CPU за ~150–250ms на 20 чанков.
- Open-source, без API-вызовов = ноль дополнительной latency через сеть.

**Feature flag** `USE_RERANKER` (default: `true`):
- Нужен для A/B-сравнения «с reranker / без» в eval.
- Нужен для дебага инцидентов на проде (отключить без редеплоя).
- НЕ нужен для «выключим если памяти не хватит» — на 8GB-плане запас.

### 2.6. Парсер: httpx + внутренний JSON API

**Решено:** парсим через внутренний JSON API support.avito.ru. Стек: `httpx + asyncio + Semaphore(8) + BeautifulSoup`.

**Почему не requests/curl на публичные страницы:**
- support.avito.ru — это SPA на React. Сырой HTML это пустой каркас (`<div id="app"></div>`, ~3KB), весь контент рендерится JS на клиенте.
- Параметр `?_escaped_fragment_=` (упомянутый в `<noscript>` страницы) не работает — отдаёт тот же пустой каркас. Проверено.

**Почему не playwright (как было в v8):**
В network-логах SPA обнаружен внутренний JSON API:
- `POST /api/1/getCatalog` с `{}` → весь каталог: 16 категорий + 70 разделов + 518 статей.
- `POST /api/1/article` с `{"id": <id>}` → JSON со всеми полями статьи: `title`, `body` (HTML-фрагмент), `categoryId`, `sectionId`, `alias`, `isActive`.

`body` содержит **тот же** HTML, что мы анализировали через DevTools — те же `<headline>`, `<h2>`, `<h3>`, `<div class="spoiler">`, `<div class="tabset">`, `<div class="factoid">`, таблицы. Класса `.smart-article` нет (его навешивает React-обёртка), но **структура внутри идентична**, чанкер на BeautifulSoup работает без изменений.

**Что подтверждено вручную:**
- 1 одиночный запрос: 200 OK, body 5606 символов.
- Каталог: 200 OK, ровно 518 статей с `typeId=4` (1 без URL — обработаем как edge case).
- 4 серии по 10 параллельных запросов на разных id (40 запросов всего): **40/40 = 200**, среднее ~25 мс на запрос, 10 параллельных за 175–356 мс. Без 4xx, 5xx, rate-limit.

**Преимущества vs playwright:**
- Скорость: ~25 мс на запрос вместо ~3–5 сек. Полный парсинг **1–2 минуты** вместо 30–60.
- Никакого Chromium (300 MB). Меньше зависимостей, проще деплой парсера в CI если понадобится.
- Структурированный JSON-ответ с `categoryId`/`sectionId` — категория источника берётся напрямую, без скрейпа сайдбара.

**Скрипт парсинга:**

```python
import asyncio, httpx
from bs4 import BeautifulSoup

BASE = "https://support.avito.ru"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Origin": BASE,
    "Referer": f"{BASE}/",
}

async def fetch_catalog(client: httpx.AsyncClient) -> list[dict]:
    r = await client.post(f"{BASE}/api/1/getCatalog", json={})
    r.raise_for_status()
    return r.json()["result"]

async def fetch_article(client, sem, item) -> dict:
    async with sem:
        r = await client.post(f"{BASE}/api/1/article", json={"id": item["id"]})
        r.raise_for_status()
        return r.json()["result"]

async def main():
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
        catalog = await fetch_catalog(client)
        # Строим иерархию для path в метаданных
        node_by_id = {n["id"]: n for n in catalog}
        articles = [n for n in catalog if n["typeId"] == 4]

        results = await asyncio.gather(
            *(fetch_article(client, sem, a) for a in articles),
            return_exceptions=True
        )

    for raw in results:
        if isinstance(raw, Exception):
            log_error(raw)
            continue
        # body — HTML-фрагмент, парсим тем же чанкером (см. ML System Design)
        soup = BeautifulSoup(raw["body"], "lxml")
        ...
```

**Запуск с локальной машины** (не из Railway/CI):
- Авито блокирует серверы вне РФ — это свойство среды, не парсера. С playwright или с `httpx` — одинаковая проблема, нужен RU-IP.
- Локальная машина в РФ решает это в одну строчку.

**Чек-лист стабильности:**
- Перед массовым парсингом — один пробный запрос из чистого `httpx` (без cookie из браузера, только наши headers). Если 200 — погнали. Если 403 → добавляем правдоподобный `User-Agent` от современного Chrome (как в коде выше).
- 518 параллельных не делаем — потенциально DDoS. Держим `Semaphore(8)`, проверено стабильно.

### 2.7. Фронт: Vite + React

**Решено:** портируем существующий html-прототип на React + Vite.

**Почему не оставляем статичный html:**
- Vercel заточен под фреймворки (Next.js, Vite, SvelteKit, Astro). Деплой «просто папки с html» работает плохо — нужны костыли с `vercel.json`, rewrites, и чаще ломается на ровном месте.
- Vite-проект Vercel определяет автоматически, деплой в одну команду.
- Для будущих доработок (стриминг ответа, кеш на клиенте, состояние «история запросов») React даёт нормальную модель state-менеджмента вместо ручных манипуляций с DOM.

**Почему Vite, а не Next.js:**
- Next.js — это SSR + API routes. У нас бэкенд отдельным сервисом на Railway, SSR не нужен (контент динамический и закрыт CORS-ом для прямого fetch с сервера). API routes дублировали бы FastAPI.
- Vite — чистая статика, собирается в `dist/`, Vercel выкладывает CDN-ом.
- Меньше магии = меньше сюрпризов на проде.

**Стек:**
- `vite@latest` с шаблоном `react`.
- TypeScript — да, просто чтобы не путаться в shape ответа от API. Не догма, можно и JS.
- Стили: переносим существующий CSS из html-прототипа в `index.css` как есть. Никакого Tailwind/styled-components — стили уже работают.
- Нет роутера (одна страница). Нет state-менеджера (всё через `useState`).
- Fetch: нативный `fetch`, без axios/react-query.

**Что портируем из прототипа** (`ativo-help__6_.html`):
- Поиск с AI-overview-карточкой → компонент `<SearchBox>` + `<AnswerCard>`.
- Логика разворачивания длинных ответов → состояние `expanded` в `useState`.
- Кнопки фидбека → компонент `<FeedbackButtons>`, шлёт `POST /feedback`.
- Все CSS-стили без изменений.

**Что выкидываем при портации:**
- Объект `mockAnswers` → заменяется на `fetch('/api/answer')`.
- Функция `getAnswer(query)` → асинхронный handler в `<App>`.
- `addEventListener('keydown')` → `onKeyDown` пропс.

**Время на портацию:** 3–4 часа. План в Day 4 (см. `04-Plan.md`).

### 2.8. Деплой: Vercel (фронт) + Railway (бэк)

**Vercel:**
- Бесплатный тариф достаточен.
- Auto-deploy из git push.
- HTTPS из коробки, CDN.

**Railway:**
- Текущий план: 8GB RAM, 8 vCPU, 100GB shared disk.
- Этого с большим запасом хватает: индекс ~42MB, reranker ~700MB, FastAPI + Chroma + всё остальное ~300MB. Запас ~7GB используется только если будем держать локальные embedding-модели (см. 7.7).
- Auto-deploy из git, env-переменные через UI.
- Persistent volume = индекс и логи не теряются при редеплое.

**Почему не Fly.io / AWS Lambda / Cloud Run:** Railway уже оплачен, ресурсов с большим запасом, постоянно работающий контейнер избавляет от cold-start-ов на пути запроса.

## 3. Структура репозитория (monorepo)

```
avito-rag/
├── README.md                  ← архитектурная диаграмма + ссылки на демо
├── docs/
│   ├── 01-PRD.md
│   ├── 02-TDR.md
│   ├── 03-ML-System-Design.md
│   └── 04-Plan.md
├── frontend/                  ← фронт на Vite + React, деплоится на Vercel
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html             ← Vite-шаблон, не наш прототип
│   ├── public/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx            ← корневой компонент
│   │   ├── components/
│   │   │   ├── SearchBox.tsx
│   │   │   ├── AnswerCard.tsx
│   │   │   ├── FeedbackButtons.tsx
│   │   │   └── SourcePill.tsx
│   │   ├── api.ts             ← fetch к POST /answer, /feedback
│   │   ├── types.ts           ← TS-типы для API response
│   │   └── index.css          ← все CSS-стили из прототипа
│   └── .env.example           ← VITE_API_BASE_URL
├── backend/                   ← бэкенд, деплоится на Railway
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── railway.toml
│   ├── src/
│   │   ├── main.py            ← FastAPI app
│   │   ├── routes.py          ← /answer, /search, /health
│   │   ├── retrieval.py       ← Chroma client + reranker
│   │   ├── generation.py      ← Claude client + промпт-логика
│   │   ├── schemas.py         ← Pydantic модели
│   │   ├── config.py          ← env-переменные
│   │   ├── postprocess.py     ← разбор ответа Claude в {lead, sections, sources}
│   │   └── logging_jsonl.py   ← структурированный лог запросов/ответов в JSONL
│   └── tests/
├── scripts/                   ← разовые скрипты, локально на машине
│   ├── parse_sitemap.py
│   ├── parse_articles.py
│   ├── build_index.py
│   └── eval.py
├── data/
│   ├── articles.jsonl         ← закоммичено (~8MB)
│   ├── golden_set.jsonl       ← 30–50 вопросов с эталонами
│   └── chroma/                ← .gitignored, собирается из articles.jsonl
└── .env.example
```

**Почему monorepo:**
- Один `git push` обновляет всё — фронт пересобирается на Vercel, бэк на Railway, каждый смотрит на свою папку.
- PRD/TDR/код в одном месте — удобно показать на собесе.
- CI (если будем делать) тоже один.

**Vercel root directory:** `frontend/`.
**Railway root directory:** `backend/`.

## 4. API контракт

### 4.1. POST /answer

**Request:**
```json
{
  "query": "как вернуть деньги если продавец не отвечает",
  "model": "haiku",
  "use_reranker": true,
  "top_k": 5
}
```

`model` и `use_reranker` опциональные, по дефолту берутся из env. `top_k` — сколько чанков отдаём в LLM.

**Response (success):**
```json
{
  "answer": {
    "lead": "Если продавец не отвечает более 3 дней...",
    "sections": [
      {
        "title": "Что делать",
        "items": [
          "Откройте чат с продавцом и нажмите...",
          "..."
        ]
      }
    ],
    "sources": [
      {
        "article_id": "1888",
        "title": "Возврат денег при безопасной сделке",
        "category": "Безопасность",
        "url": "https://support.avito.ru/articles/1888",
        "lastmod": "2025-12-10"
      }
    ]
  },
  "meta": {
    "latency_ms": 3420,
    "model": "claude-haiku-4-5",
    "retrieval_scores": [0.82, 0.78, 0.71, 0.65, 0.61],
    "reranker_used": true
  }
}
```

**Response (no relevant content):**
```json
{
  "answer": null,
  "fallback": "По вашему запросу не нашлось точного ответа. Можно [написать в поддержку](https://...).",
  "meta": { ... }
}
```

**Response (error):**
```json
{
  "error": "rate_limit_exceeded",
  "message": "Слишком много запросов, попробуйте через минуту"
}
```

### 4.2. POST /search (без LLM, для отладки и эвала)

```json
// Request
{ "query": "как вернуть деньги", "top_k": 10 }

// Response
{
  "results": [
    {
      "article_id": "1888",
      "chunk_text": "...",
      "score": 0.82,
      "title": "...",
      "category": "...",
      "url": "..."
    }
  ]
}
```

### 4.3. POST /feedback

Дополняет существующую запись в `logs.jsonl` оценкой пользователя (см. секцию 5).

```json
{
  "query": "...",
  "answer_id": "uuid",
  "rating": "up" | "down"
}
```

### 4.4. GET /health

```json
{ "status": "ok", "index_size": 3525, "uptime_s": 12345 }
```

### 4.5. CORS

`Access-Control-Allow-Origin: https://<vercel-domain>` — только для домена фронта. Локальная разработка — `http://localhost:5173` дополнительно через env.

## 5. Логирование запросов и ответов

### 5.1. Зачем

Лог запросов нужен **сам по себе**, не как часть фидбек-системы. Без него:
- Невозможно посмотреть, какие реальные вопросы задают и какие ответы получают.
- Невозможно вычислить eval-метрики на проде (latency P50/P95, частота fallback-ов).
- Невозможно собрать материал для следующих итераций (плохо отвеченные запросы → новые тест-кейсы для golden-set).
- На собесе нечего показать как «вот реальные данные, на которых я строил выводы».

Это **MUST** для проекта.

### 5.2. Что логируем

Каждый запрос → одна строка в `data/logs.jsonl`:

```json
{
  "ts": "2026-05-07T14:32:15.123Z",
  "request_id": "uuid4",
  "query": "как вернуть деньги если продавец не отвечает",
  "model": "claude-haiku-4-5",
  "use_reranker": true,
  "retrieval": [
    {"article_id": "1888", "score": 0.82, "title": "Возврат при безопасной сделке", "category": "Безопасность"},
    {"article_id": "2106", "score": 0.78, "title": "...", "category": "..."},
    {"article_id": "3314", "score": 0.71, "title": "...", "category": "..."},
    {"article_id": "1828", "score": 0.65, "title": "...", "category": "..."},
    {"article_id": "2243", "score": 0.61, "title": "...", "category": "..."}
  ],
  "answer": {
    "lead": "Если продавец не отвечает более 3 дней...",
    "sections": [{"title": "Что делать", "items": ["..."]}],
    "sources_used": ["1888", "2106"]
  },
  "fallback": false,
  "latency_ms": {
    "embedding": 145,
    "retrieval": 12,
    "reranker": 198,
    "generation": 2870,
    "total": 3225
  },
  "tokens": {"input": 1840, "output": 320},
  "cost_usd": 0.00344,
  "user_ip_hash": "a3f1...",
  "feedback": null
}
```

**Поле `feedback`** изначально `null`. Если пользователь нажмёт 👍/👎 — допишется `{"rating": "up", "ts": "..."}` через `POST /feedback` (см. 4.3). Реализация: при фидбеке ищем строку по `request_id` и переписываем; так как файл маленький — это норм. На больших объёмах перейдём на Postgres.

**Что не логируем:**
- Полный текст чанков (только `article_id` и метаданные) — иначе файл разрастётся в гигабайты.
- Сырой IP пользователя — только хеш с солью (см. 5.4).
- Системный промпт (он один и тот же, его версия в отдельном поле `prompt_version`).

### 5.3. Технические детали

**Файл:** `/data/logs.jsonl` на персистентном volume Railway. Не пересоздаётся при редеплое.

**Формат:** одна JSON-строка на запрос, append-only. Удобно читать через `tail`, парсить через `jq`, грузить в pandas одной строкой:
```python
df = pd.read_json('logs.jsonl', lines=True)
```

**Запись:** через `aiofiles` (async append) — не блокирует event loop FastAPI. Файл всегда открывается на append, lock не нужен на нашей нагрузке (1 worker uvicorn).

**Ротация:** не делаем для MVP. При 1k запросов/день файл растёт ~5MB/день — на месяц демо хватит. Если упрёмся — gzip старого файла раз в неделю по cron.

**Чтение:** через защищённый эндпоинт (см. 5.5).

### 5.4. Хеширование IP (privacy)

```python
import hashlib, os
salt = os.environ["IP_HASH_SALT"]  # секрет
ip_hash = hashlib.sha256(f"{salt}{client_ip}".encode()).hexdigest()[:16]
```

**Зачем хеш, а не сам IP:**
- GDPR-friendly. IP считается персональными данными в ЕС.
- Нам не нужен IP — нужно понимать «один пользователь задал 3 вопроса подряд» (для UX-аналитики). Хеш это покрывает.
- На случай утечки файла — деанонимизировать пользователя нельзя.

**Зачем соль:** без соли можно перебрать все IPv4 за минуту и сделать обратный мэппинг. Соль из env делает это бессмысленным.

### 5.5. Эндпоинты для просмотра логов

**`GET /admin/logs?limit=100&since=2026-05-07T00:00:00Z`** — читает последние N строк из `logs.jsonl`, возвращает JSON-массив.

**`GET /admin/logs.jsonl`** — отдаёт файл как есть, для скачивания и анализа в pandas/jupyter.

**Защита:** оба эндпоинта требуют header `X-Admin-Token: <secret>`, токен в env-переменной `ADMIN_TOKEN`. Без токена → 401. Это не production-grade auth, но достаточно чтобы файл не нашли по случайному скану.

На собесе: можно показать `curl -H "X-Admin-Token: ..." https://.../admin/logs.jsonl | jq .` живьём, либо открыть файл в pandas-ноутбуке заранее.

### 5.6. Что считаем по логам (примеры)

Эти запросы — материал для финального дашборда / слайда «что я узнал из реальных данных»:

```python
# Топ-10 категорий, по которым задают вопросы
df.explode('retrieval').retrieval.apply(lambda x: x['category']).value_counts().head(10)

# P50/P95 latency
df.latency_ms.apply(lambda x: x['total']).quantile([0.5, 0.95])

# Доля fallback-ов
df.fallback.mean()

# Helpful rate (когда есть фидбек)
df[df.feedback.notna()].feedback.apply(lambda x: x['rating']).value_counts(normalize=True)

# Стоимость на 1k запросов
(df.cost_usd.sum() / len(df)) * 1000
```

## 6. Деплой и инфраструктура

### 6.1. Что где живёт

| Компонент | Хост | Размер |
|---|---|---|
| Фронт (Vite-bundle: html + JS + CSS) | Vercel | ~150–250KB gzipped |
| FastAPI приложение | Railway | ~200MB образ |
| Chroma index | Railway volume `/data/chroma` | ~42MB |
| Логи запросов | Railway volume `/data/logs.jsonl` | растёт ~5MB/день |
| `data/articles.jsonl` | в репо | ~8MB |

### 6.2. Env-переменные

**Railway (backend):**
```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_MODEL=claude-haiku-4-5
USE_RERANKER=true
TOP_K_RETRIEVAL=20
TOP_K_RERANK=5
CHROMA_PATH=/data/chroma
LOGS_PATH=/data/logs.jsonl
IP_HASH_SALT=<random-32-bytes>
ADMIN_TOKEN=<random-32-bytes>
LOG_LEVEL=INFO
ALLOWED_ORIGIN=https://avi-help.vercel.app
```

**Vercel (frontend):**
- `VITE_API_BASE_URL=https://avi-help-api.up.railway.app` — задаётся в UI Vercel в Environment Variables. Vite подхватывает переменные с префиксом `VITE_` на этапе билда и инжектит в bundle.
- В коде: `const API = import.meta.env.VITE_API_BASE_URL`.

### 6.3. Обновление индекса

**MVP:** руками. После изменения статей на Авито:
1. На локалке: `python scripts/parse_articles.py` (~1–2 минуты через JSON API) → `python scripts/build_index.py` (~5 минут на embeddings).
2. `git add data/articles.jsonl data/chroma/ && git push`.
3. Railway автоматически перекатывает контейнер при пуше, индекс читается с диска при старте.

**После MVP (roadmap):** автоматизация теперь упрощена — образ парсера легковесный (нет Chromium, влезает в стандартный `python:3.11-slim`). Варианты:
- Cron на VPS в РФ + git push в репо. Самое простое.
- GitHub Actions с self-hosted runner в РФ. Чище в плане инфраструктуры.
- Webhook от Авито (если они когда-нибудь появятся). Маловероятно.

Прямой Github Actions из дефолтных раннеров не сработает — Авито блокирует IP вне РФ. Это свойство среды, не парсера.

### 6.4. Cold start и uptime

- Railway не усыпляет контейнеры на нашем плане → cold start не страшен.
- Если контейнер всё-таки рестартует — индекс читается с диска за ~1 сек, reranker и embedding-модель грузятся в lifespan event (~3–5 сек).
- Health check `/health` каждые 30 сек.

## 7. Ключевые технические решения (которые я выкинул из PRD)

### 7.1. Haiku по дефолту, Sonnet опциональный

**Решено:** Haiku 4.5 default, через `?model=sonnet` можно сравнить.

**Trade-off:**
- (+) latency: ожидаем P50 ~3 сек на Haiku vs ~6 сек на Sonnet. **Гипотеза**, проверим точные цифры в eval (раздел про latency в ML System Design).
- (+) стоимость в 3 раза ниже ($1/$5 vs $3/$15 за 1M токенов — проверено в Anthropic docs).
- (–) на сложных вопросах с противоречивыми источниками Sonnet может дать более точный ответ.

**Митигация минуса:** в eval измеряем оба варианта. Если faithfulness на Haiku < 0.85 — пересматриваем дефолт.

### 7.2. Reranker: bge-reranker-v2-m3, MUST с feature flag

**Решено:** reranker — обязательный компонент пайплайна. Включается по дефолту (`USE_RERANKER=true`).

**Зачем feature flag:**
- Для A/B-сравнения в eval (с reranker / без) — это часть метрик в ML System Design.
- Для дебага: если на проде что-то сломалось в reranker-пути, можно временно отключить переменной окружения без редеплоя кода.
- Не для «выключим если медленно» — мы уже посчитали, что 150–250ms укладывается в P95 ≤8 сек.

**Trade-off:**
- (+) Recall@5 растёт на 5–15% (точно померяем в eval).
- (–) +150–250ms latency — закладываем в бюджет P95.
- (–) +700MB RAM — на 8GB-плане это <10%, не критично.

**Альтернатива, которую не берём:** rerank через ту же Claude Haiku (отдать ей 20 чанков и попросить выбрать топ-5). Дороже, медленнее, нестабильнее.

### 7.3. Single-shot prompt vs цепочка extract → answer

**Решено:** single-shot. Один промпт = chunks + question → структурированный ответ.

**Альтернатива:** extract relevant facts → answer (ReAct/RAG-Fusion стиль).

**Почему single-shot:**
- Дешевле в 2x (один LLM-вызов вместо двух).
- Быстрее.
- На 5 чанках после reranker контекст уже сфокусированный — extract step мало добавляет.

**Когда стоит вернуться к цепочке:** если на eval faithfulness < 0.85 или ответы цепляют irrelevant информацию из чанков.

### 7.4. Стратегия чанкинга

**Решено:** структурный чанкинг с учётом реальной разметки support.avito.ru.

Анализ 9 реальных статей показал, что у Авито **5 разных шаблонов разметки** контента — от длинных агрегаторов с FAQ-блоками до плоских статей без заголовков. Стратегия должна работать на всех:
- Spoiler-блоки (раскрывающиеся FAQ) и tabset-блоки (вкладки) → отдельные чанки с метаданными о пути в иерархии.
- Структурные сепараторы — `<headline>` ИЛИ `<h2>` (есть не везде, нужно учитывать оба).
- `<h3>` внутри разделов уровня 1 → отдельные подчанки (типичный FAQ-стиль).
- Плоские статьи без заголовков → один чанк или sliding window 600 токенов с 80 overlap.

**Каждый чанк хранит** хлебные крошки `[article_title / section / subsection]` в начале текста — без этого после retrieval теряется контекст («если прошло 6 часов» теряет привязку к роли «гость» из табсета).

**Полный алгоритм, метаданные чанка, fallback-стратегии — в ML System Design (раздел 2.1).**

### 7.5. Инкрементальная переиндексация — пока не делаем

**Решено:** каждый запуск `build_index.py` пересоздаёт индекс с нуля.

**Почему:** ~5200 чанков × ~250 токенов = 1.3M токенов × $0.02/1M = **~$0.025**. Дешевле чем сложность инкремента.

**Когда станет важно:** при индексе в 50+ тысяч статей или при запуске реиндекса несколько раз в день. Тогда — diff по `lastmod`, апдейт только изменившихся чанков.

### 7.6. Стратегия логирования

См. подробно раздел 5. Кратко:
- **JSONL-файл на диске Railway** — для запросов/ответов/метрик/фидбека. Это MUST.
- **stdout** — для отладки и ошибок. Railway хранит 7 дней.
- **Postgres** — не делаем в MVP. Если масштаб дорастёт до уровня, где JSONL не справится — переезжаем; описано в roadmap.
- **Файл-кэш для eval** — все вызовы LLM на eval-сете кэшируются в `data/llm_cache.jsonl` локально. Повторный прогон бесплатный.

## 8. Безопасность

### 8.1. Что защищаем

- API-ключи (OpenAI, Anthropic) — только в env-переменных Railway, никогда в репо.
- Свой бюджет — rate limit на уровне Railway (5 req/sec на IP).
- Пользователя — не выдавать вредные/выдуманные ответы (см. промпт-инжиниринг в ML System Design).

### 8.2. Что НЕ защищаем (и почему)

- **Prompt injection.** В демо принимаем как риск. На проде — необходимо экранирование пользовательского запроса в промпте + фильтрация (например, отказ если в запросе «ignore previous instructions»). Закладываю в roadmap.
- **DDoS.** Railway даёт базовую защиту. Полноценный rate limit (Cloudflare/upstash) — после MVP.
- **Аутентификация пользователя.** Демо публичное.

### 8.3. PII в логах

- В query пользователь может ввести номер телефона / email — не пишем raw query в долгие логи. В stdout — да (Railway вытирает через 7 дней).
- При интеграции с прод-логами Авито — обязательная маскировка (телефоны, email-ы, номера объявлений ≠ логируем как `<PII>`). В roadmap.

## 9. Тестирование

### 9.1. Что тестируем

- **Unit:** `chunk_text()` — корректное разбиение по заголовкам + overlap.
- **Unit:** `postprocess_answer()` — парсинг ответа Claude в `{lead, sections, sources}`. Хрупкая часть, важно покрыть.
- **Integration:** `POST /answer` с моком Anthropic клиента — проверяем формат response.
- **Smoke на проде:** скрипт `python scripts/smoke.py` — запускаем 5 базовых вопросов через прод-API и проверяем что они отвечают.

### 9.2. Что не тестируем

- Качество ответов LLM — это eval, отдельный pipeline (см. ML System Design).
- Chroma как такового — доверяем библиотеке.
- Сетевые сбои OpenAI/Anthropic — обрабатываем try/except, но не моделируем в тестах.

## 10. Риски (с тех-стороны)

| Риск | Митигация |
|---|---|
| Cold start на Railway > 30 сек из-за загрузки reranker | Reranker инициализируется в lifespan event при старте, не при первом запросе. Health check ждёт его готовности. |
| OpenAI rate limit на embeddings во время массовой индексации | Batch API + ретраи с exponential backoff. На ~5200 чанков — это 3–5 минут, влезает в tier-1 лимиты. |
| Anthropic API падает в момент демо | Фолбэк на retrieval-only (`/search` отдаёт чанки, фронт показывает их как карточки без LLM-обзора) — degraded mode. |
| Память Railway переполняется | Маловероятно на текущем плане (8GB). Reranker ~700MB + FastAPI + Chroma ~300MB + индекс ~42MB ≈ ~1GB. Запас 7GB. Если решим грузить локальные embedding-модели — следим за расходом RAM. |
| **Внутренний JSON API Авито меняет схему / закрывается / требует auth** | Низкая вероятность за горизонт 5 дней до демо: API стабильно работает, без auth, проверен на 40 параллельных запросах. Если случится **до парсинга** — переписываем парсер на playwright за ~2 часа (HTML-структура та же). Если **после парсинга** — индекс уже собран, ничего не блокируется до следующей переиндексации. |
| `httpx` начинает получать 403/401 (вдруг API проверяет cookie/origin) | В headers сразу кладём правдоподобный `User-Agent`, `Origin: https://support.avito.ru`, `Referer: https://support.avito.ru/`. Перед массовым парсингом — пробный одиночный запрос для проверки. |
| Часть статей теряется при парсинге (тайм-аут, ошибка) | `asyncio.gather(..., return_exceptions=True)` — упавшие статьи логируем и пропускаем, не падает весь job. Если потеряли >5% — повтор для пропущенных id. |
| Структура HTML в `body` изменится при редизайне | Селекторы `<headline>`, `.spoiler`, `.tabset`, `.factoid` могут измениться. Парсер логирует статьи, где не нашёл ни одного известного блока, чтобы их можно было проанализировать вручную. Полный фолбэк — режем по `<p>` через sliding window. |

## 11. Что в ML System Design (не здесь)

В отдельный документ `03-ML-System-Design.md` вынесено:
- Полный пайплайн (offline indexing + online query) с тайминговым бюджетом по шагам.
- Стратегия chunking с учётом 5 разных шаблонов разметки support.avito.ru: `<headline>`, `<h2>`, h3 как FAQ, spoilers (FAQ Q→A), tabsets (вкладки), плоские статьи.
- Метаданные чанков: `path`, `chunk_type`, `factoid_kinds`, `anchor_id`, `tab_label`.
- Retrieval-схема: bi-encoder top-20 → reranker top-5, threshold для fallback.
- Generation через Anthropic tool use (структурированный JSON-вывод вместо парсинга markdown).
- Системный промпт целиком, формат подачи чанков, постфильтр по категориям, fallback-цепочка.
- Eval-pipeline: golden-set из 50 вопросов, retrieval-метрики (Recall@5, MRR), generation-метрики через LLM-as-judge на Sonnet, кэш для воспроизводимости.
- 4 конфигурации в ablation-eval (baseline без reranker, mvp, large-embeddings, llm-as-reranker).
- Roadmap ML-улучшений по горизонтам: 2 недели → 1–2 месяца → 3–6 месяцев → 6+.
