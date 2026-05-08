"""LLM cache for Anthropic messages.create — append-only JSONL by SHA-256 key.

Также кэширует embedding-вызовы OpenAI (отдельный файл), чтобы повторный прогон
eval не тратил ни Anthropic, ни OpenAI бюджет.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = _PROJECT_ROOT / "data" / "llm_cache.jsonl"
DEFAULT_EMB_CACHE_PATH = _PROJECT_ROOT / "data" / "embedding_cache.jsonl"

# Anthropic cache (in-memory index loaded from JSONL)
_cache: dict[str, dict[str, Any]] = {}
_loaded_path: Optional[Path] = None

# Embedding cache (separate file)
_emb_cache: dict[str, list[float]] = {}
_emb_loaded_path: Optional[Path] = None

_lock = threading.Lock()
_emb_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "writes": 0,
          "emb_hits": 0, "emb_misses": 0, "emb_writes": 0}


def _to_serializable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(v) for v in obj]
    return obj


def make_key(model: str, messages, tools, temperature, system=None) -> str:
    """SHA-256 over (model, messages, tools, temperature, system) — stable JSON."""
    payload = {
        "model": model,
        "messages": _to_serializable(messages),
        "tools": _to_serializable(tools),
        "temperature": temperature,
        "system": _to_serializable(system),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def load_cache(path: Path = DEFAULT_CACHE_PATH) -> int:
    """Подгружает все записи из JSONL в in-memory dict. Возвращает их количество.
    Безопасно вызывать повторно — каждый раз очищает _cache перед загрузкой."""
    global _loaded_path
    _cache.clear()
    _loaded_path = path
    if not path.exists():
        return 0
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            _cache[rec["key"]] = rec
            n += 1
    return n


def cache_get(key: str) -> Optional[dict]:
    rec = _cache.get(key)
    if rec is None:
        _stats["misses"] += 1
        return None
    _stats["hits"] += 1
    return rec


def cache_put(key: str, model: str, response_dict: dict, usage_dict: dict) -> None:
    if _loaded_path is None:
        load_cache()
    rec = {
        "key": key,
        "model": model,
        "response": response_dict,
        "usage": usage_dict,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with _lock:
        _cache[key] = rec
        with open(_loaded_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _stats["writes"] += 1


def stats() -> dict[str, int]:
    return dict(_stats)


def reset_stats() -> None:
    for k in _stats:
        _stats[k] = 0


# === Rehydration: cached response → object that mimics anthropic.types.Message ===

class _CachedBlock:
    __slots__ = ("type", "input", "text", "id", "name")

    def __init__(self, **kw):
        self.type = kw.get("type")
        self.input = kw.get("input")
        self.text = kw.get("text")
        self.id = kw.get("id")
        self.name = kw.get("name")


class _CachedUsage:
    __slots__ = ("input_tokens", "output_tokens")

    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class CachedMessage:
    """Mimics anthropic.types.Message: .content[*].type, .content[*].input,
    .model, .usage.input_tokens, .usage.output_tokens — этого достаточно для
    кода в backend/generation.py."""

    def __init__(self, content_blocks, model, usage_dict):
        self.content = [_CachedBlock(**b) for b in content_blocks]
        self.model = model
        self.usage = _CachedUsage(
            input_tokens=usage_dict.get("input_tokens", 0),
            output_tokens=usage_dict.get("output_tokens", 0),
        )


def rehydrate(rec: dict) -> CachedMessage:
    resp = rec["response"]
    return CachedMessage(
        content_blocks=resp.get("content", []),
        model=resp.get("model", rec.get("model", "")),
        usage_dict=rec.get("usage", {}),
    )


# === Wrapper around Anthropic client (drop-in for backend/generation.py) ===

def _serialize_response(resp) -> dict:
    """Берём из Anthropic Message только то, что использует наш генератор."""
    blocks = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        b = {"type": btype}
        if btype == "tool_use":
            b["input"] = getattr(block, "input", None)
            b["id"] = getattr(block, "id", None)
            b["name"] = getattr(block, "name", None)
        elif btype == "text":
            b["text"] = getattr(block, "text", None)
        blocks.append(b)
    return {"content": blocks, "model": resp.model}


class _CachedMessagesAPI:
    def __init__(self, real_messages):
        self._real = real_messages

    def create(self, **kwargs):
        model = kwargs.get("model", "")
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools", [])
        temperature = kwargs.get("temperature", 0)
        system = kwargs.get("system")
        key = make_key(model, messages, tools, temperature, system)

        cached = cache_get(key)
        if cached is not None:
            return rehydrate(cached)

        resp = self._real.create(**kwargs)
        usage_dict = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
        cache_put(key, resp.model, _serialize_response(resp), usage_dict)
        return resp


class CachedAnthropic:
    """Drop-in wrapper for anthropic.Anthropic — кэширует только messages.create.
    Все остальные API проксируются напрямую в реальный клиент."""

    def __init__(self, real_client):
        self._real = real_client
        self.messages = _CachedMessagesAPI(real_client.messages)

    def __getattr__(self, name):
        # Прокси для остальных атрибутов на случай если кто-то лезет напрямую.
        return getattr(self._real, name)


def cached_call(client, **kwargs):
    """Convenience helper согласно спеке Спринта 4."""
    return CachedAnthropic(client).messages.create(**kwargs)


# === Embedding cache ===

def _emb_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x00{text}".encode("utf-8")).hexdigest()


def load_embedding_cache(path: Path = DEFAULT_EMB_CACHE_PATH) -> int:
    global _emb_loaded_path
    _emb_cache.clear()
    _emb_loaded_path = path
    if not path.exists():
        return 0
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            _emb_cache[rec["key"]] = rec["vector"]
            n += 1
    return n


def embedding_get(model: str, text: str) -> Optional[list[float]]:
    key = _emb_key(model, text)
    vec = _emb_cache.get(key)
    if vec is None:
        _stats["emb_misses"] += 1
        return None
    _stats["emb_hits"] += 1
    return vec


def embedding_put(model: str, text: str, vector: list[float]) -> None:
    if _emb_loaded_path is None:
        load_embedding_cache()
    key = _emb_key(model, text)
    rec = {
        "key": key,
        "model": model,
        "text": text,
        "vector": vector,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with _emb_lock:
        _emb_cache[key] = vector
        with open(_emb_loaded_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _stats["emb_writes"] += 1
