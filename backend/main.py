import json
import os
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    FastAPI,
    Header,
    HTTPException,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

from generation import GenerationResult, generate, generate_stream
from logging_jsonl import (
    FeedbackLogEntry,
    LatencyRecord,
    RequestLogEntry,
    RetrievalRecord,
    UsageRecord,
    cost_for,
    fallback_request_id,
    get_log_file,
    hash_ip,
    now_iso,
    read_logs,
    write_feedback_log,
    write_request_log,
)
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


def _client_ip(request: Request) -> Optional[str]:
    """Первый IP из X-Forwarded-For (Railway проксирует), либо peer-IP."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


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
    request_id: Optional[str] = None
    query: str = Field(..., min_length=1, max_length=500)
    answer_text: str = Field("", max_length=20000)
    sources_used: list[str] = Field(default_factory=list, max_length=20)
    rating: str = Field(..., pattern="^(up|down)$")


class AnswerResponse(BaseModel):
    query: str
    request_id: str
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


def _build_request_log(
    *,
    request_id: str,
    query: str,
    ip: Optional[str],
    endpoint: str,
    hits: list,
    is_fallback: bool,
    model: Optional[str],
    usage: dict,
    latency: dict,
) -> RequestLogEntry:
    in_t = (usage or {}).get("input_tokens", 0)
    out_t = (usage or {}).get("output_tokens", 0)
    return RequestLogEntry(
        ts=now_iso(),
        request_id=request_id,
        query=query,
        ip_hash=hash_ip(ip),
        endpoint=endpoint,
        retrieval=[RetrievalRecord(chunk_id=h.chunk_id, score=round(h.score, 4))
                   for h in hits],
        is_fallback=is_fallback,
        model=model,
        usage=UsageRecord(input_tokens=in_t, output_tokens=out_t),
        cost_usd=round(cost_for(model or "", in_t, out_t), 6),
        latency_ms=LatencyRecord(**latency),
    )


def _build_error_log(
    *,
    request_id: str,
    query: str,
    ip: Optional[str],
    endpoint: str,
    error_type: str,
    error_msg: str,
    hits: Optional[list] = None,
) -> RequestLogEntry:
    return RequestLogEntry(
        ts=now_iso(),
        request_id=request_id,
        query=query,
        ip_hash=hash_ip(ip),
        endpoint=endpoint,
        retrieval=[RetrievalRecord(chunk_id=h.chunk_id, score=round(h.score, 4))
                   for h in (hits or [])],
        is_fallback=False,
        error_type=error_type,
        error_msg=error_msg,
    )


@app.post("/answer/sync", response_model=AnswerResponse)
def answer_sync(
    req: AnswerRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    if _RETRIEVAL_INIT_ERROR is not None:
        raise HTTPException(status_code=503, detail=_RETRIEVAL_INIT_ERROR)

    request_id = uuid4().hex
    ip = _client_ip(request)

    t0 = time.perf_counter()
    try:
        hits = search(req.query, top_k=req.top_k)
        t_retrieval = time.perf_counter()
        result = generate(req.query, hits)
        t_done = time.perf_counter()
    except Exception as e:
        background_tasks.add_task(
            write_request_log,
            _build_error_log(
                request_id=request_id, query=req.query, ip=ip,
                endpoint="/answer/sync",
                error_type=type(e).__name__, error_msg=str(e)[:300],
            ),
        )
        raise

    latency = {
        "retrieval": int((t_retrieval - t0) * 1000),
        "generation": int((t_done - t_retrieval) * 1000),
        "total": int((t_done - t0) * 1000),
    }

    background_tasks.add_task(
        write_request_log,
        _build_request_log(
            request_id=request_id, query=req.query, ip=ip,
            endpoint="/answer/sync", hits=hits,
            is_fallback=result.is_fallback, model=result.model,
            usage=result.usage, latency=latency,
        ),
    )

    return AnswerResponse(
        query=req.query,
        request_id=request_id,
        answer=result,
        retrieval_scores=[round(h.score, 3) for h in hits],
        latency_ms=latency,
    )


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/answer")
async def answer(req: AnswerRequest, request: Request):
    if _RETRIEVAL_INIT_ERROR is not None:
        raise HTTPException(status_code=503, detail=_RETRIEVAL_INIT_ERROR)

    request_id = uuid4().hex
    ip = _client_ip(request)

    t0 = time.perf_counter()
    hits = search(req.query, top_k=req.top_k)
    t_retrieval = time.perf_counter()

    async def event_stream():
        # Накопители для лога — заполняются по ходу стрима.
        is_fallback = False
        model_used: Optional[str] = None
        usage = {"input_tokens": 0, "output_tokens": 0}
        try:
            async for ev in generate_stream(req.query, hits):
                etype = ev["event"]
                data = dict(ev["data"])
                if etype == "meta":
                    # Прокидываем request_id на фронт через первое meta-событие.
                    data["request_id"] = request_id
                    is_fallback = bool(data.get("is_fallback", False))
                elif etype == "done":
                    model_used = data.get("model")
                    if isinstance(data.get("usage"), dict):
                        usage = data["usage"]
                    is_fallback = bool(data.get("is_fallback", is_fallback))
                yield _sse_format(etype, data)
        except Exception as e:
            print(f"[/answer] stream error: {e!r}", file=sys.stderr)
            write_request_log(_build_error_log(
                request_id=request_id, query=req.query, ip=ip,
                endpoint="/answer",
                error_type=type(e).__name__, error_msg=str(e)[:300],
                hits=hits,
            ))
            return

        t_done = time.perf_counter()
        latency = {
            "retrieval": int((t_retrieval - t0) * 1000),
            "generation": int((t_done - t_retrieval) * 1000),
            "total": int((t_done - t0) * 1000),
        }
        # SSE-стрим уже отправлен — пишем лог inline (BackgroundTasks тут
        # стартует только после ответа, что в SSE = после закрытия стрима).
        try:
            write_request_log(_build_request_log(
                request_id=request_id, query=req.query, ip=ip,
                endpoint="/answer", hits=hits,
                is_fallback=is_fallback, model=model_used,
                usage=usage, latency=latency,
            ))
        except Exception as e:
            print(f"[/answer] log write failed: {e!r}", file=sys.stderr)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/feedback", status_code=204)
def feedback_endpoint(
    req: FeedbackRequest,
    background_tasks: BackgroundTasks,
):
    """Запись 👍/👎 в `data/logs/feedback_{date}.jsonl`. Не блокирует ответ —
    UI получает 204 и не зависит от диска. Если request_id не пришёл (старый
    клиент / fallback) — генерим из хеша query+ts."""
    rid = req.request_id or fallback_request_id(req.query)
    background_tasks.add_task(
        write_feedback_log,
        FeedbackLogEntry(
            ts=now_iso(),
            request_id=rid,
            query=req.query,
            rating=req.rating,
            sources_used=req.sources_used,
        ),
    )
    return None


# === Admin: чтение логов ===

def _check_admin(token: Optional[str]) -> None:
    expected = os.getenv("ADMIN_TOKEN")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/admin/logs")
def admin_logs(
    date: str,
    limit: int = 100,
    kind: str = "requests",
    x_admin_token: Optional[str] = Header(None),
):
    _check_admin(x_admin_token)
    if kind not in ("requests", "feedback"):
        raise HTTPException(status_code=400, detail="kind must be requests or feedback")
    items = read_logs(date, kind=kind, limit=limit)
    return {"date": date, "kind": kind, "count": len(items), "items": items}


@app.get("/admin/logs.jsonl")
def admin_logs_raw(
    date: str,
    kind: str = "requests",
    x_admin_token: Optional[str] = Header(None),
):
    _check_admin(x_admin_token)
    if kind not in ("requests", "feedback"):
        raise HTTPException(status_code=400, detail="kind must be requests or feedback")
    path = get_log_file(date, kind=kind)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no log file for {kind} on {date}")
    return FileResponse(
        path,
        media_type="application/x-ndjson",
        filename=path.name,
    )
