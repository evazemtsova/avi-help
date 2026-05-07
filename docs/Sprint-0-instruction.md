# Спринт 0 — пошаговая инструкция

**Цель:** к концу — на Vercel-ссылке открывается интерфейс, при сабмите приходит mock-ответ от живого Railway.
**Стек:** macOS, VS Code, Git, Python 3.11+, Node.js 18+.

---

## Шаг 1. Проверяем, что всё установлено

Открой **Terminal** (Cmd+Space → пишешь «Terminal» → Enter).

Прогони по очереди:

```bash
git --version
python3 --version
node --version
npm --version
```

Должны появиться версии. Если что-то не находится — установка:

- **Git:** обычно есть из коробки. Если нет — `xcode-select --install`.
- **Python:** ставится через [python.org](https://www.python.org/downloads/macos/) или `brew install python@3.12`.
- **Node:** [nodejs.org](https://nodejs.org/) (LTS-версия) или `brew install node`.

**Проверка:** все 4 команды показывают версии без ошибок.

---

## Шаг 2. Создаём репозиторий на GitHub

1. Заходишь на [github.com](https://github.com), жмёшь **New repository** (зелёная кнопка справа сверху или [тут](https://github.com/new)).
2. Заполняешь:
   - **Repository name:** `avi-help` (или как хочешь, но запомни)
   - **Description:** `AI Overview для справочного центра Авито (пет-проект)`
   - **Public** или **Private** — на твой выбор. Для портфолио лучше Public, но можно сделать публичным позже.
   - **Add a README file:** ✅ (поставь галку)
   - **Add .gitignore:** выбери из списка `Python`
   - **Choose a license:** `MIT License` (опционально)
3. Жмёшь **Create repository**.

**Проверка:** открывается страница репозитория с README.md.

---

## Шаг 3. Клонируем репо локально

В терминале:

```bash
cd ~/Documents
# или куда тебе удобно складывать проекты, например ~/projects

git clone https://github.com/ТВОЙ_USERNAME/avi-help.git
cd avi-help
```

**Проверка:** ты внутри папки `avi-help`, `ls` показывает `README.md` и `.gitignore`.

---

## Шаг 4. Открываем папку в VS Code

```bash
code .
```

Если команда `code` не работает — открой VS Code вручную, **File → Open Folder → выбери `avi-help`**.

(Чтобы `code` заработал в будущем: в VS Code жми Cmd+Shift+P, набирай «Shell Command: Install 'code' command in PATH», Enter.)

**Проверка:** в VS Code слева видна папка с `README.md` и `.gitignore`.

---

## Шаг 5. Создаём структуру папок

В терминале VS Code (Ctrl+\` чтобы открыть) внутри папки `avi-help`:

```bash
mkdir -p frontend backend data scripts docs
touch frontend/.gitkeep backend/.gitkeep data/.gitkeep scripts/.gitkeep docs/.gitkeep
```

`.gitkeep` — это хак: Git не отслеживает пустые папки, поэтому в каждую кладём пустой файл.

**Проверка:** в дереве VS Code видны 5 папок.

---

## Шаг 6. Кладём документы в `docs/`

У тебя уже есть PRD, TDR, ML System Design. Перетащи их в папку `docs/` прямо в VS Code (или скопируй через Finder). Этот план тоже положи туда как `04-Plan.md`.

Структура `docs/` должна быть примерно такой:

```
docs/
  01-PRD.md
  02-TDR.md
  03-ML-System-Design.md
  04-Plan.md
  Спринт-0-инструкция.md  (этот файл)
```

**Проверка:** все 4–5 файлов на месте, открываются.

---

## Шаг 7. Бэкенд: создаём Python-окружение

В терминале, внутри `avi-help`:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

После активации в начале строки появится `(.venv)` — это значит, ты внутри изолированного окружения. Все `pip install` отсюда не загрязнят систему.

```bash
pip install --upgrade pip
pip install fastapi "uvicorn[standard]" python-dotenv pydantic
pip freeze > requirements.txt
```

**Проверка:** `cat requirements.txt` показывает список с fastapi, uvicorn и т.д.

---

## Шаг 8. Бэкенд: пишем скелет

Создай файл `backend/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="A-Help API")

# CORS — чтобы фронт с Vercel мог стучаться в этот бэк
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # на проде сузим до домена Vercel
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str


class AnswerRequest(BaseModel):
    query: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search")
def search(req: SearchRequest):
    # Заглушка — потом заменим на реальный retrieval
    return {
        "query": req.query,
        "chunks": [
            {"chunk_id": "stub-1", "title": "Заглушка", "score": 0.99}
        ],
    }


@app.post("/answer")
def answer(req: AnswerRequest):
    # Заглушка — потом заменим на retrieval + LLM
    return {
        "query": req.query,
        "lead": f"Это mock-ответ на вопрос: «{req.query}». Реальный LLM подключим в Спринте 2.",
        "sections": [],
        "sources": [
            {
                "article_id": 1833,
                "url": "https://support.avito.ru/articles/1833",
                "title": "Пример статьи",
                "category": "Безопасность",
            }
        ],
    }
```

Создай рядом `backend/.env.example`:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
ADMIN_TOKEN=придумай-длинную-строку
```

И `backend/.env` (с реальными ключами, **этот файл никогда не коммитим**):

```
ANTHROPIC_API_KEY=твой-настоящий-ключ
OPENAI_API_KEY=твой-настоящий-ключ
ADMIN_TOKEN=любая-секретная-строка
```

В корне репо (не в `backend/`) создай или дополни `.gitignore`:

```
# Python
__pycache__/
*.pyc
.venv/
venv/

# Env
.env
.env.local

# IDE
.vscode/
.idea/

# OS
.DS_Store

# Data
data/llm_cache.jsonl
data/*.log
```

**Проверка:** `git status` не показывает `.venv/` и `.env`.

---

## Шаг 9. Бэкенд: локальный запуск

Из папки `backend/` (с активированным `.venv`):

```bash
uvicorn main:app --reload --port 8000
```

Должно появиться что-то типа:

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

В новой вкладке терминала (Cmd+T):

```bash
curl http://localhost:8000/health
```

Должно вернуть `{"status":"ok"}`.

```bash
curl -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{"query":"как вернуть деньги"}'
```

Должен вернуться mock-ответ.

**Проверка пройдена:** оба curl-запроса работают. Оставь uvicorn запущенным.

---

## Шаг 10. Фронтенд: создаём Vite-проект

В **новом** терминале (Cmd+T), вернись в корень репо:

```bash
cd ~/Documents/avi-help
```

Vite-шаблон создаётся в текущую папку, но у нас в `frontend/` уже есть `.gitkeep`. Чтобы не было конфликта:

```bash
rm frontend/.gitkeep
npm create vite@latest frontend -- --template react
cd frontend
npm install
```

**Проверка:** в `frontend/` появились `package.json`, `vite.config.js`, папки `src/` и `public/`.

---

## Шаг 11. Фронтенд: переносим прототип

У тебя есть `ativo-help__6_.html`. Положи его в `frontend/public/` как `legacy-prototype.html` (на всякий случай, как референс).

Теперь надо перенести содержимое прототипа в React-компонент. Вариант для Спринта 0: **просто отдаём прототип как есть**, превращение в React — задача для Спринта 3.

Самый простой путь: замени содержимое `frontend/index.html` на содержимое прототипа. Но добавь туда вызов API.

Для Спринта 0 хватит минимального React-компонента, который умеет дёргать API. Перепиши `frontend/src/App.jsx`:

```jsx
import { useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

function App() {
  const [query, setQuery] = useState('')
  const [answer, setAnswer] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setAnswer(null)
    try {
      const res = await fetch(`${API_BASE}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setAnswer(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '40px auto', padding: 16, fontFamily: 'sans-serif' }}>
      <h1>А-Помощь (skeleton)</h1>
      <p style={{ color: '#666' }}>API: {API_BASE}</p>

      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Задай вопрос…"
          style={{ width: '100%', padding: 12, fontSize: 16 }}
          maxLength={200}
        />
        <button type="submit" disabled={loading || !query} style={{ marginTop: 8, padding: '10px 16px' }}>
          {loading ? 'Думаю…' : 'Спросить'}
        </button>
      </form>

      {error && (
        <div style={{ marginTop: 16, color: 'crimson' }}>
          Ошибка: {error}
        </div>
      )}

      {answer && (
        <div style={{ marginTop: 16, padding: 16, border: '1px solid #ddd', borderRadius: 8 }}>
          <p>{answer.lead}</p>
          {answer.sources?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <strong>Источники:</strong>
              <ul>
                {answer.sources.map((s) => (
                  <li key={s.article_id}>
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.title}
                    </a>{' '}
                    <span style={{ color: '#999' }}>({s.category})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default App
```

В Спринте 3 заменим этот скелет на полноценный UI из прототипа.

Создай `frontend/.env.local`:

```
VITE_API_BASE_URL=http://localhost:8000
```

Создай `frontend/.env.example`:

```
VITE_API_BASE_URL=http://localhost:8000
```

**Проверка:** файлы созданы.

---

## Шаг 12. Фронтенд: локальный запуск

В терминале фронта:

```bash
npm run dev
```

Должно открыться что-то типа `http://localhost:5173`. Открой в браузере, введи запрос, нажми «Спросить» — должен вернуться mock-ответ от живого бэка.

**Проверка пройдена:** end-to-end работает локально. Бэк на 8000, фронт на 5173, фронт стучится в бэк, ответ приходит.

---

## Шаг 13. Первый коммит

В терминале, корень репо:

```bash
git add .
git status   # глянь, что не утащил .env и .venv
git commit -m "Sprint 0: skeleton (FastAPI backend + Vite/React frontend)"
git push origin main
```

**Проверка:** на GitHub в репо появились все папки и файлы.

---

## Шаг 14. Аккаунты для деплоя

Если ещё не зарегистрирован:

1. **Vercel:** [vercel.com/signup](https://vercel.com/signup) → войди через GitHub. Бесплатный план Hobby подходит.
2. **Railway:** [railway.app](https://railway.app) → войди через GitHub. Дадут $5 кредита бесплатно, для нашего проекта хватит. Если нужно больше — Hobby plan $5/мес. **Важно:** уточни актуальные планы и лимиты на сайте, они меняются.
3. **Anthropic API ключ:** [console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key. Положи $5–10 на счёт.
4. **OpenAI API ключ:** [platform.openai.com](https://platform.openai.com/api-keys) → Create new secret key. Положи $5 на счёт.

**Проверка:** все 4 аккаунта есть, два API-ключа лежат в локальном `backend/.env`.

---

## Шаг 15. Готовим бэк к деплою на Railway

Railway смотрит на репо и пытается понять, как запустить. Для FastAPI нужно сказать ему явно.

Создай `backend/Procfile` (без расширения):

```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Создай `backend/runtime.txt`:

```
python-3.12
```

`requirements.txt` уже есть с шага 7.

Закоммить:

```bash
git add backend/
git commit -m "backend: Procfile + runtime.txt for Railway"
git push
```

**Проверка:** на GitHub эти файлы видны.

---

## Шаг 16. Деплой бэка на Railway

1. Заходишь в [railway.app/dashboard](https://railway.app/dashboard).
2. Жмёшь **New Project** → **Deploy from GitHub repo**.
3. Если первый раз — Railway попросит подключить GitHub. Дай доступ только к репо `avi-help`.
4. Выбираешь репо `avi-help`. Railway создаёт сервис.
5. **Важно:** Railway по умолчанию смотрит в корень репо. Надо указать, что бэк живёт в `backend/`.
   - Открываешь сервис → **Settings** → ищешь **Root Directory** → ставишь `backend`.
   - Там же **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT` (на случай если Procfile не подхватится).
6. **Variables** (это вкладка в сервисе): добавляешь:
   - `ANTHROPIC_API_KEY` = твой ключ
   - `OPENAI_API_KEY` = твой ключ
   - `ADMIN_TOKEN` = любая длинная строка
7. **Networking** → **Generate Domain**. Получишь что-то типа `avi-help-api-production.up.railway.app`. Если хочешь именно `avi-help-api.up.railway.app` (как в TDR) — попробуй переименовать сервис в Settings; если занято, оставь любой работающий домен и поправь TDR.
8. Жди билд (1–3 минуты). Если падает — смотри логи в **Deployments**.

**Проверка:**

```bash
curl https://ТВОЙ-ДОМЕН.up.railway.app/health
```

Должно вернуть `{"status":"ok"}`.

---

## Шаг 17. Persistent volume на Railway

Это критично для будущей Chroma. Лучше проверить сейчас, на пустом каркасе.

1. В сервисе на Railway → **Settings** → **Volumes** → **Add Volume**.
2. **Mount Path:** `/data`
3. **Size:** 1 GB хватит (можно увеличить позже).
4. Сохраняешь, сервис рестартует.

Проверим, что volume действительно подключён и переживает рестарт. Добавь в `backend/main.py` тестовые ручки (потом удалим):

```python
import os
from datetime import datetime

VOLUME_PATH = "/data"

@app.post("/admin/test-volume-write")
def test_volume_write():
    if not os.path.exists(VOLUME_PATH):
        return {"error": f"{VOLUME_PATH} does not exist"}
    path = os.path.join(VOLUME_PATH, "test.txt")
    with open(path, "w") as f:
        f.write(f"written at {datetime.utcnow().isoformat()}")
    return {"path": path, "ok": True}


@app.get("/admin/test-volume-read")
def test_volume_read():
    path = os.path.join(VOLUME_PATH, "test.txt")
    if not os.path.exists(path):
        return {"error": "file not found"}
    with open(path) as f:
        return {"content": f.read()}
```

Закоммить, запушить:

```bash
git add backend/main.py
git commit -m "backend: temp volume test endpoints"
git push
```

Railway сам подхватит коммит и передеплоит (1–2 мин). Потом:

```bash
curl -X POST https://ТВОЙ-ДОМЕН.up.railway.app/admin/test-volume-write
curl https://ТВОЙ-ДОМЕН.up.railway.app/admin/test-volume-read
```

Должны увидеть содержимое. Теперь принудительно рестартани сервис:

- На Railway → сервис → три точки справа → **Restart**.

После рестарта снова:

```bash
curl https://ТВОЙ-ДОМЕН.up.railway.app/admin/test-volume-read
```

Должен вернуться **тот же** контент с прошлым timestamp. Это значит volume работает.

После проверки удали тестовые ручки из `main.py`, закоммить, запушь:

```bash
git add backend/main.py
git commit -m "backend: remove temp volume test endpoints"
git push
```

**Проверка пройдена:** volume подключён, переживает рестарт.

---

## Шаг 18. Деплой фронта на Vercel

1. Заходишь на [vercel.com/new](https://vercel.com/new).
2. **Import Git Repository** → выбираешь `avi-help`.
3. **Framework Preset:** Vercel сам определит Vite. Если не определил — выбери **Vite**.
4. **Root Directory:** жмёшь **Edit**, ставишь `frontend`.
5. **Build Command, Output Directory:** оставляешь дефолт (`npm run build`, `dist`).
6. **Environment Variables** → добавляешь:
   - `VITE_API_BASE_URL` = `https://ТВОЙ-ДОМЕН-RAILWAY.up.railway.app`
7. Жмёшь **Deploy**.
8. Через 1–2 минуты получаешь домен типа `avi-help.vercel.app`. Если хочешь именно его — в **Settings → Domains** проверь и переименуй, если занят (укажешь любой работающий и поправишь TDR).

**Проверка:** открываешь Vercel-ссылку в браузере, видишь UI, вводишь запрос, получаешь mock-ответ от Railway.

---

## Шаг 19. Сужаем CORS

Сейчас бэк принимает запросы откуда угодно (`allow_origins=["*"]`). Это ок для отладки, но лучше сразу ограничить.

В `backend/main.py`:

```python
import os

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,https://avi-help.vercel.app"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

На Railway в **Variables** добавь `ALLOWED_ORIGINS` со своим Vercel-доменом, через запятую с `localhost:5173`. Передеплой подхватится автоматически.

**Проверка:** Vercel-сайт продолжает работать (CORS не блокирует).

---

## Шаг 20. Финальная проверка спринта 0

Чек-лист, всё должно отвечать «да»:

- [ ] Открываешь Vercel-ссылку с телефона / другого браузера — UI грузится
- [ ] Вводишь запрос — приходит mock-ответ
- [ ] `curl https://ТВОЙ-ДОМЕН.up.railway.app/health` отвечает `{"status":"ok"}`
- [ ] В Railway-сервисе подключён volume на `/data`
- [ ] В репо нет `.env` и `.venv/` (`git status` чисто)
- [ ] Все ключи лежат в Railway Variables и в локальном `.env`
- [ ] Локально всё ещё работает: запускаешь `uvicorn` и `npm run dev`, end-to-end отвечает

Если всё «да» — Спринт 0 закрыт. Иди в `04-Plan.md`, поставь галки в чек-листе спринта, статус → `готов`.

---

## Если что-то пошло не так

**Vercel build падает с ошибкой про Vite/Node:**
В Project Settings → General → Node.js Version поставь `20.x`.

**Railway build падает на pip install:**
Открой Deployments → последний → **View Logs**. Скорее всего проблема в `requirements.txt` (например, версия не сошлась) — закрепи версии (`fastapi==0.115.0` и т.п.).

**CORS-ошибка в браузере на проде:**
Проверь, что `VITE_API_BASE_URL` на Vercel указывает именно на Railway-домен (с `https://`), и что `ALLOWED_ORIGINS` на Railway содержит твой Vercel-домен **без слеша в конце**.

**`fetch failed` в браузере:**
Открой DevTools → Network → посмотри, куда шёл запрос и что вернулось. Если адрес `localhost:8000` — значит env-переменная на Vercel не подхватилась, передеплой Vercel.

**Volume не подключается / `/data does not exist`:**
В Settings → Volumes проверь Mount Path именно `/data` (не `data`, не `/var/data`). После создания volume сервис должен автоматически рестартануть; если не рестартанул — рестартани вручную.

**API-ключи не работают на Railway:**
В Variables проверь, что нет лишних пробелов и кавычек. Anthropic-ключ начинается на `sk-ant-`, OpenAI — на `sk-`.
