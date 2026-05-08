import json
import os
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

from generation import GenerationResult, generate, generate_stream
from retrieval import SearchHit, search, warmup


def _bootstrap_chroma_if_empty() -> None:
    """Если CHROMA_PATH пуст (нет chroma.sqlite3) и задан BOOTSTRAP_CHROMA_URL —
    скачиваем tar.gz и распаковываем. Идемпотентно: при заполненном volume
    ничего не делает. Для одноразовой инициализации Railway volume."""
    chroma_path_env = os.getenv("CHROMA_PATH")
    bootstrap_url = os.getenv("BOOTSTRAP_CHROMA_URL")
    if not chroma_path_env or not bootstrap_url:
        return

    chroma_path = Path(chroma_path_env)
    if (chroma_path / "chroma.sqlite3").exists():
        return

    print(
        f"Bootstrapping chroma at {chroma_path} from {bootstrap_url}",
        file=sys.stderr,
    )
    chroma_path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        urllib.request.urlretrieve(bootstrap_url, tmp.name)
        with tarfile.open(tmp.name, "r:gz") as tar:
            tar.extractall(path=str(chroma_path))
    print(
        f"Bootstrap done: {sum(1 for _ in chroma_path.rglob('*'))} entries in {chroma_path}",
        file=sys.stderr,
    )

app = FastAPI(title="A-Help API")

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


_RETRIEVAL_INIT_ERROR: str | None = None


@app.on_event("startup")
def _startup() -> None:
    global _RETRIEVAL_INIT_ERROR
    try:
        _bootstrap_chroma_if_empty()
    except Exception as e:
        print(f"Bootstrap failed (continuing without): {e}", file=sys.stderr)
    _RETRIEVAL_INIT_ERROR = warmup()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=50)


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    latency_ms: int


class AnswerRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(5, ge=1, le=20)


class FeedbackRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    answer_text: str = Field("", max_length=20000)
    sources_used: list[str] = Field(default_factory=list, max_length=20)
    rating: str = Field(..., pattern="^(up|down)$")


class AnswerResponse(BaseModel):
    query: str
    answer: GenerationResult
    retrieval_scores: list[float]
    latency_ms: dict[str, int]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "retrieval_ready": _RETRIEVAL_INIT_ERROR is None,
    }


@app.post("/search", response_model=SearchResponse)
def search_endpoint(req: SearchRequest):
    if _RETRIEVAL_INIT_ERROR is not None:
        raise HTTPException(status_code=503, detail=_RETRIEVAL_INIT_ERROR)

    t0 = time.perf_counter()
    hits = search(req.query, top_k=req.top_k)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return SearchResponse(query=req.query, hits=hits, latency_ms=elapsed_ms)


@app.post("/answer/sync", response_model=AnswerResponse)
def answer_sync(req: AnswerRequest):
    if _RETRIEVAL_INIT_ERROR is not None:
        raise HTTPException(status_code=503, detail=_RETRIEVAL_INIT_ERROR)

    t0 = time.perf_counter()
    hits = search(req.query, top_k=req.top_k)
    t_retrieval = time.perf_counter()

    result = generate(req.query, hits)
    t_done = time.perf_counter()

    return AnswerResponse(
        query=req.query,
        answer=result,
        retrieval_scores=[round(h.score, 3) for h in hits],
        latency_ms={
            "retrieval": int((t_retrieval - t0) * 1000),
            "generation": int((t_done - t_retrieval) * 1000),
            "total": int((t_done - t0) * 1000),
        },
    )


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/answer")
async def answer(req: AnswerRequest):
    if _RETRIEVAL_INIT_ERROR is not None:
        raise HTTPException(status_code=503, detail=_RETRIEVAL_INIT_ERROR)

    hits = search(req.query, top_k=req.top_k)

    async def event_stream():
        async for ev in generate_stream(req.query, hits):
            yield _sse_format(ev["event"], ev["data"])

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/feedback", status_code=204)
def feedback_endpoint(req: FeedbackRequest):
    """Stub-ручка обратной связи 👍/👎. Сейчас только пишет в stderr для
    дебага. Спринт 4 заменит на запись в JSONL вместе с retrieval-метаданными
    и хешем IP. UI шлёт вызов и не зависит от ответа — на ошибку ловит silent."""
    print(
        f"[feedback] rating={req.rating} sources={req.sources_used} "
        f"query={req.query[:80]!r}",
        file=sys.stderr,
    )
    return None
