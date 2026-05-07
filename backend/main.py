from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

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


VOLUME_PATH = "/data"


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
