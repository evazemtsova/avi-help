"""Structured JSONL логирование запросов и фидбека.

Файлы пишутся в `$LOG_PATH/requests_{YYYY-MM-DD}.jsonl` и
`$LOG_PATH/feedback_{YYYY-MM-DD}.jsonl`. По умолчанию `LOG_PATH=data/logs`
(относительно корня репо). На Railway переопределяется в `/data/logs`.

Если директория недоступна для записи — лог пишется в stderr и не падает.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = PROJECT_ROOT / "data" / "logs"

# Pricing для cost_usd. Дублируется с scripts/eval.py — эти числа маленькие
# и редко меняются; гонять через ещё один импорт только ради 3 строк хуже.
PRICING = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (5.0, 25.0),
}


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    if not model:
        return 0.0
    rate = PRICING.get(model)
    if rate is None:
        for prefix, r in PRICING.items():
            if model.startswith(prefix):
                rate = r
                break
    if rate is None:
        return 0.0
    return input_tokens * rate[0] / 1e6 + output_tokens * rate[1] / 1e6


def get_log_path() -> Path:
    raw = os.getenv("LOG_PATH")
    if raw:
        return Path(raw)
    return DEFAULT_LOG_PATH


def hash_ip(ip: Optional[str]) -> Optional[str]:
    """SHA-256 от (salt || ip), первые 16 hex-символов. None если ip пустой
    или не задан LOG_IP_SALT (без соли хеш реверсится перебором IPv4)."""
    if not ip:
        return None
    salt = os.getenv("LOG_IP_SALT")
    if not salt:
        return None
    return hashlib.sha256(f"{salt}\x00{ip}".encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    """ISO-8601 в UTC с суффиксом Z, до секунд."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# === Pydantic schemas ===

class RetrievalRecord(BaseModel):
    chunk_id: str
    score: float


class UsageRecord(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LatencyRecord(BaseModel):
    retrieval: int = 0
    generation: int = 0
    total: int = 0
    # Sprint 5/6 retrieval breakdown (None в legacy записях до коммита 97fef7e).
    embed_ms: Optional[int] = None
    chroma_ms: Optional[int] = None
    rerank_ms: Optional[int] = None
    bm25_ms: Optional[int] = None
    merge_ms: Optional[int] = None
    rerank_fetch_k: Optional[int] = None


class RequestLogEntry(BaseModel):
    ts: str
    request_id: str
    query: str
    ip_hash: Optional[str] = None
    endpoint: str
    retrieval: list[RetrievalRecord] = Field(default_factory=list)
    is_fallback: bool = False
    model: Optional[str] = None
    usage: Optional[UsageRecord] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[LatencyRecord] = None
    # При ошибке вместо usage/latency пишем error_type/error_msg.
    error_type: Optional[str] = None
    error_msg: Optional[str] = None


class FeedbackLogEntry(BaseModel):
    ts: str
    request_id: str
    query: str
    rating: str
    sources_used: list[str] = Field(default_factory=list)


# === Append helpers ===

def _append_jsonl(filename: str, line: str) -> None:
    """Пишем одну строку в JSONL. Если LOG_PATH не writable — fallback
    в stderr, не падаем."""
    log_path = get_log_path()
    try:
        log_path.mkdir(parents=True, exist_ok=True)
        target = log_path / filename
        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[log:fallback] {filename}: {line}", file=sys.stderr)
        print(f"[log:fallback] write failed: {e!r}", file=sys.stderr)


def write_request_log(entry: RequestLogEntry) -> None:
    today = entry.ts[:10]
    line = entry.model_dump_json(exclude_none=True)
    _append_jsonl(f"requests_{today}.jsonl", line)


def write_feedback_log(entry: FeedbackLogEntry) -> None:
    today = entry.ts[:10]
    line = entry.model_dump_json(exclude_none=True)
    _append_jsonl(f"feedback_{today}.jsonl", line)


# === Read helpers (admin endpoints) ===

def read_logs(date: str, kind: str = "requests",
              limit: Optional[int] = None) -> list[dict]:
    """Парсит файл за дату, kind = 'requests' или 'feedback'.
    Возвращает последние `limit` записей (или все если limit=None)."""
    log_path = get_log_path()
    target = log_path / f"{kind}_{date}.jsonl"
    if not target.exists():
        return []
    out: list[dict] = []
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None:
        out = out[-limit:]
    return out


def get_log_file(date: str, kind: str = "requests") -> Optional[Path]:
    """Путь к файлу за дату или None если нет."""
    log_path = get_log_path()
    target = log_path / f"{kind}_{date}.jsonl"
    if not target.exists():
        return None
    return target


def fallback_request_id(query: str) -> str:
    """Если /feedback пришёл без request_id — генерим из query+ts чтобы
    хоть как-то связать (несовершенно, но лучше пустого ид)."""
    h = hashlib.sha256(f"{query}\x00{now_iso()}".encode("utf-8")).hexdigest()
    return f"fb-{h[:16]}"
