from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import AsyncGenerator, Optional

from anthropic import Anthropic, AsyncAnthropic
from partial_json_parser import loads as partial_loads
from pydantic import BaseModel

from prompts import SAFETY_PRIMING, SYSTEM_PROMPT, USER_TEMPLATE, format_chunk
from retrieval import SearchHit

DEFAULT_MODEL = os.getenv("MODEL", "claude-haiku-4-5")
# Sprint 5 Блок 5 final: reranker откатили (был v2-m3 → base+10 → провалилось
# по Recall@5). Threshold возвращён к bi-encoder scale 0.3 (Sprint 2 default).
# Env-переменная RETRIEVAL_THRESHOLD_V2 на Railway теперь не нужна — default
# в коде совпадает с bi-encoder scale, в которой работает прод.
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD_V2", "0.3"))
MAX_TOKENS = 1024
SAFETY_CATEGORY = "Безопасность"

# Sprint 5 Блок 2: SAFETY_PRIMING активируется по триггерам в query пользователя,
# а не по retrieval-категории. До этого priming срабатывал на любую top-3 категорию
# «Безопасность» — давало false-positive на запросах про повреждённый товар
# (g020 «телефон со сколом» подтянул чанки «Меня обманули» → лишний SMS-warning).
SAFETY_TRIGGERS = frozenset({
    # Коды доступа / SMS
    "код", "смс", "sms",
    # Пароль (с анти-триггерами на access recovery)
    "пароль", "пороль",
    # Мошенничество (явные слова)
    "мошенник", "обман", "развод", "кинул", "увели",
    # Подозрительные ссылки / QR
    "ссылк", "фишинг", "qr",
    # Подозрительные звонки (3-е лицо: «кто-то звонит мне») —
    # ведущий пробел чтобы НЕ ловить «позвонить продавцу»/«позвонят» в инфинитиве.
    " звонят", " звонит", " названивают", " позвонили",
    # Социальная инженерия по телефону
    "служба безопасности", " сб ",
    # Вывод общения / денег вне Авито
    "перевод вне", "вне авито", "вне сделк",
    "whatsapp", "ватсап", "вотсап",
    "телеграм", "телега", " тг ",
})

# Анти-триггеры — query содержит safety-слово, но контекст не safety.
SAFETY_ANTI_TRIGGERS = frozenset({
    # Access recovery (нормальный flow смены пароля, не фишинг)
    "сменить пароль", "восстановить пароль", "забыл пароль",
    "сменить пороль", "восстановить пороль", "забыл пороль",
    "новый пароль", "новый пороль",
    # Код получения посылки (не SMS-код доступа)
    "код получения", "код плучения", "код посылки",
    "код пвз", "код для пункта", "код заказа",
})

# Sprint 5 Блок 3.5: competitor platforms — query про другую площадку → автоматически
# pre-LLM fallback. Это закрывает класс OOD-кейсов где reranker даёт высокий score
# (потому что чанки про размещение объявлений / доставку семантически близки), но
# ответить надо отказом. Padded substring match с ведущим пробелом для word-boundary.
COMPETITOR_PLATFORMS = frozenset({
    # Юла (склонения)
    " юла ", " юле ", " юлы ", " юлу ", " юлой ",
    # Озон
    " озон ", " озоне ", " озона ", " озону ",
    " ozon ",
    # Wildberries
    " wildberries ", " вайлдберриз ", " вб ",
    # Ламода
    " ламода ", " ламоде ", " lamoda ",
    # Яндекс.Маркет
    " яндекс маркет", " яндекс.маркет", " яндекс-маркет",
    " я.маркет", " я маркет",
    # Алиэкспресс
    " aliexpress ", " алиэкспресс ", " али ",
    # eBay
    " ебей ", " ebay ",
    # Сбермегамаркет
    " мегамаркет ", " сбермегамаркет ",
    # Авто-площадки
    " drom ", " дром ",
    # Яндекс.Лавка
    " лавка ", " лавке ", " лавку ",
    # Amazon, Joom
    " amazon ", " амазон ", " джум ",
})


def _is_competitor_query(query: str) -> bool:
    """True если в query упомянута конкурентная торговая площадка.
    Padded query + ведущий пробел в маркере = word-boundary без regex."""
    q = " " + query.lower() + " "
    return any(c in q for c in COMPETITOR_PLATFORMS)

LOW_RETRIEVAL_LEAD = (
    "По этому запросу не нашлось точной информации в справке. "
    "Попробуйте сформулировать вопрос конкретнее или обратитесь в чат поддержки."
)

ANSWER_TOOL = {
    "name": "respond_with_sources",
    "description": "Структурированный ответ пользователю с указанием источников.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lead": {
                "type": "string",
                "description": "Короткий ответ из 1-2 предложений. Без markdown.",
            },
            "sections": {
                "type": "array",
                "description": "Дополнительные разделы. Пусто если ответ полный в lead.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string", "description": "Может содержать markdown."},
                    },
                    "required": ["title", "body"],
                },
            },
            "sources_used": {
                "type": "array",
                "description": "chunk_id чанков, на которые опирается ответ. Только из предоставленных.",
                "items": {"type": "string"},
            },
            "is_fallback": {
                "type": "boolean",
                "description": "true если ответ — fallback (out-of-domain или низкая уверенность).",
            },
        },
        "required": ["lead", "sections", "sources_used", "is_fallback"],
    },
}


class Section(BaseModel):
    title: str
    body: str


class SourceMeta(BaseModel):
    article_id: int
    article_url: str
    title: str
    category: str
    section: Optional[str] = None
    lastmod: Optional[str] = None


class GenerationResult(BaseModel):
    lead: str
    sections: list[Section]
    sources_used: list[str]
    sources: list[SourceMeta]
    is_fallback: bool
    model: str
    usage: dict[str, int]


_anthropic_client: Optional[Anthropic] = None
_async_anthropic_client: Optional[AsyncAnthropic] = None


def _get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(timeout=30.0, max_retries=1)
    return _anthropic_client


def _get_async_anthropic_client() -> AsyncAnthropic:
    global _async_anthropic_client
    if _async_anthropic_client is None:
        _async_anthropic_client = AsyncAnthropic(timeout=30.0, max_retries=1)
    return _async_anthropic_client


def _resolve_sources(sources_used: list[str], hits: list[SearchHit]) -> list[SourceMeta]:
    """По chunk_id из sources_used достаёт метаданные из hits, дедуплицирует
    по article_id с сохранением порядка появления."""
    by_chunk = {h.chunk_id: h for h in hits}
    seen_articles: set[int] = set()
    sources: list[SourceMeta] = []
    for chunk_id in sources_used:
        hit = by_chunk.get(chunk_id)
        if hit is None or hit.article_id in seen_articles:
            continue
        seen_articles.add(hit.article_id)
        sources.append(
            SourceMeta(
                article_id=hit.article_id,
                article_url=hit.article_url,
                title=hit.title,
                category=hit.category,
                section=hit.section,
                lastmod=hit.lastmod,
            )
        )
    return sources


def _format_user_message(query: str, hits: list[SearchHit]) -> str:
    chunks_text = "\n\n".join(
        format_chunk(
            idx=i + 1,
            chunk_id=h.chunk_id,
            category=h.category,
            title=h.title,
            section=h.section,
            text=h.chunk_text,
        )
        for i, h in enumerate(hits)
    )
    return USER_TEMPLATE.format(query=query, chunks=chunks_text)


def _needs_safety_priming(query: str, hits: list[SearchHit]) -> bool:
    """Sprint 5 Блок 2: priming на основе query-триггеров.

    Возвращает True если в query есть хотя бы один SAFETY_TRIGGERS-маркер
    И при этом нет SAFETY_ANTI_TRIGGERS-маркера. Параметр hits сохранён
    в signature для совместимости с подменой в apply_config('baseline'),
    но в новой логике не используется.
    """
    q = " " + query.lower() + " "  # padding чтобы " сб " матчилось на границах
    if any(a in q for a in SAFETY_ANTI_TRIGGERS):
        return False
    return any(t in q for t in SAFETY_TRIGGERS)


def _extract_tool_use(response) -> Optional[dict]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    return None


def _normalize_sections(raw) -> list[dict]:
    """Haiku иногда возвращает sections в виде JSON-encoded строки вместо массива
    (даже при tool_choice=force). Пытаемся распарсить; на любой проблеме — пусто."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            print("WARN: tool_use.sections returned as string, dropping", file=sys.stderr)
            return []
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, dict)]


def _low_retrieval_fallback(model: str) -> GenerationResult:
    return GenerationResult(
        lead=LOW_RETRIEVAL_LEAD,
        sections=[],
        sources_used=[],
        sources=[],
        is_fallback=True,
        model=model,
        usage={"input_tokens": 0, "output_tokens": 0},
    )


def generate(query: str, hits: list[SearchHit]) -> GenerationResult:
    model = DEFAULT_MODEL

    # Pre-LLM fallback: пустой retrieval, низкий top-1 score, или query про
    # конкурентную площадку (Юла/Озон/WB и т.п. — reranker даёт им высокий score
    # на чанках про размещение/доставку, но ответ должен быть отказом).
    if (not hits
            or hits[0].score < RETRIEVAL_THRESHOLD
            or _is_competitor_query(query)):
        return _low_retrieval_fallback(model)

    system_prompt = SYSTEM_PROMPT
    if _needs_safety_priming(query, hits):
        system_prompt = SYSTEM_PROMPT + "\n\n" + SAFETY_PRIMING

    user_message = _format_user_message(query, hits)

    client = _get_anthropic_client()
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=system_prompt,
        tools=[ANSWER_TOOL],
        tool_choice={"type": "tool", "name": "respond_with_sources"},
        messages=[{"role": "user", "content": user_message}],
    )

    tool_input = _extract_tool_use(response)
    if tool_input is None:
        print("WARN: model did not return tool_use block, falling back", file=sys.stderr)
        return _low_retrieval_fallback(response.model)

    valid_chunk_ids = {h.chunk_id for h in hits}
    raw_sources_used = tool_input.get("sources_used") or []
    sources_used = [c for c in raw_sources_used if c in valid_chunk_ids]
    invalid = [c for c in raw_sources_used if c not in valid_chunk_ids]
    if invalid:
        print(f"WARN: model invented chunk_ids {invalid}, dropped", file=sys.stderr)

    is_fallback = bool(tool_input.get("is_fallback", False))

    # Если модель утверждает не-fallback ответ, но не сослалась ни на один валидный
    # чанк — это галлюцинация. Превращаем в fallback (TDR §4.5 [3]).
    if not is_fallback and not sources_used:
        print(
            "WARN: non-fallback answer with no valid sources_used, forcing fallback",
            file=sys.stderr,
        )
        return _low_retrieval_fallback(response.model)

    sections = [
        Section(title=s.get("title", ""), body=s.get("body", ""))
        for s in _normalize_sections(tool_input.get("sections"))
    ]
    sources = _resolve_sources(sources_used, hits)

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    return GenerationResult(
        lead=tool_input.get("lead", ""),
        sections=sections,
        sources_used=sources_used,
        sources=sources,
        is_fallback=is_fallback,
        model=response.model,
        usage=usage,
    )


# === Streaming ===

StreamEvent = dict


def _retrieval_sources(hits: list[SearchHit]) -> list[SourceMeta]:
    """Резолв всех hits в SourceMeta с дедупом по article_id (в порядке появления).
    Используется в meta-событии стриминга — UI получает пилюли источников сразу."""
    seen: set[int] = set()
    out: list[SourceMeta] = []
    for h in hits:
        if h.article_id in seen:
            continue
        seen.add(h.article_id)
        out.append(
            SourceMeta(
                article_id=h.article_id,
                article_url=h.article_url,
                title=h.title,
                category=h.category,
                section=h.section,
                lastmod=h.lastmod,
            )
        )
    return out


async def generate_stream(
    query: str, hits: list[SearchHit]
) -> AsyncGenerator[StreamEvent, None]:
    """Потоковая генерация.

    Yields события вида {"event": <name>, "data": {...}}:
      - meta: первое событие со списком retrieval-источников и предварительным
        is_fallback (true для pre-LLM fallback, false иначе).
      - lead_delta: инкрементальные куски lead, парсятся из partial input_json
        через partial-json-parser. Шлются только новые символы относительно
        ранее отправленных.
      - section: целая секция {title, body}, отправляется после закрытия
        tool_use (отдельные секции в стриминге не дробим — sliding-парсер на
        массиве усложняет код без пользы; полные секции достаточно).
      - done: финальные usage, model, sources_used, is_fallback, sources
        (resolved по sources_used). Если по какой-то причине LLM-ответ
        невалиден — превращаем в fallback и шлём lead_delta с fallback-текстом.
    """
    model = DEFAULT_MODEL

    # Pre-LLM fallback — пустой retrieval, низкий top-1 score или competitor-query.
    if (not hits
            or hits[0].score < RETRIEVAL_THRESHOLD
            or _is_competitor_query(query)):
        yield {"event": "meta", "data": {"sources": [], "is_fallback": True}}
        yield {"event": "lead_delta", "data": {"text": LOW_RETRIEVAL_LEAD}}
        yield {
            "event": "done",
            "data": {
                "model": model,
                "is_fallback": True,
                "sources_used": [],
                "sources": [],
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        return

    # meta до LLM-вызова: pre-resolved retrieval sources + предварительный is_fallback=false.
    pre_sources = _retrieval_sources(hits)
    yield {
        "event": "meta",
        "data": {
            "sources": [s.model_dump() for s in pre_sources],
            "is_fallback": False,
        },
    }

    system_prompt = SYSTEM_PROMPT
    if _needs_safety_priming(query, hits):
        system_prompt = SYSTEM_PROMPT + "\n\n" + SAFETY_PRIMING

    user_message = _format_user_message(query, hits)
    client = _get_async_anthropic_client()

    json_buffer = ""
    streamed_lead = ""

    async with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=system_prompt,
        tools=[ANSWER_TOOL],
        tool_choice={"type": "tool", "name": "respond_with_sources"},
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        async for event in stream:
            etype = getattr(event, "type", None)
            if etype != "content_block_delta":
                continue
            delta = event.delta
            if getattr(delta, "type", None) != "input_json_delta":
                continue
            json_buffer += delta.partial_json

            # Пробуем толерантный парс — на ранних дельтах JSON ещё ломаный.
            try:
                partial = partial_loads(json_buffer)
            except Exception:
                continue
            if not isinstance(partial, dict):
                continue
            current_lead = partial.get("lead")
            if not isinstance(current_lead, str):
                continue
            if len(current_lead) > len(streamed_lead) and current_lead.startswith(
                streamed_lead
            ):
                increment = current_lead[len(streamed_lead):]
                streamed_lead = current_lead
                yield {"event": "lead_delta", "data": {"text": increment}}
                # Anthropic SDK выдаёт content_block_delta пачками по ~5-10
                # событий per HTTP-chunk; uvicorn в одной итерации event-loop'а
                # бандлит socket-writes в один TCP-segment → пользователь видит
                # «бух весь параграф» вместо печати. 20мс между дельтами
                # разрывает batch и даёт визуальную скорость печати ~50 cps.
                await asyncio.sleep(0.02)

        final_message = await stream.get_final_message()

    tool_input = None
    for block in final_message.content:
        if getattr(block, "type", None) == "tool_use":
            tool_input = block.input
            break

    if tool_input is None:
        # Не должно случаться при tool_choice=force, но страхуемся.
        print("WARN: stream finished without tool_use block, forcing fallback",
              file=sys.stderr)
        if not streamed_lead:
            yield {"event": "lead_delta", "data": {"text": LOW_RETRIEVAL_LEAD}}
        yield {
            "event": "done",
            "data": {
                "model": final_message.model,
                "is_fallback": True,
                "sources_used": [],
                "sources": [],
                "usage": {
                    "input_tokens": final_message.usage.input_tokens,
                    "output_tokens": final_message.usage.output_tokens,
                },
            },
        }
        return

    final_lead = tool_input.get("lead", "")
    if final_lead.startswith(streamed_lead) and len(final_lead) > len(streamed_lead):
        tail = final_lead[len(streamed_lead):]
        yield {"event": "lead_delta", "data": {"text": tail}}
    elif final_lead and not streamed_lead:
        yield {"event": "lead_delta", "data": {"text": final_lead}}

    valid_chunk_ids = {h.chunk_id for h in hits}
    raw_sources_used = tool_input.get("sources_used") or []
    sources_used = [c for c in raw_sources_used if c in valid_chunk_ids]
    invalid = [c for c in raw_sources_used if c not in valid_chunk_ids]
    if invalid:
        print(f"WARN: model invented chunk_ids {invalid}, dropped", file=sys.stderr)

    is_fallback = bool(tool_input.get("is_fallback", False))
    if not is_fallback and not sources_used:
        print(
            "WARN: non-fallback answer with no valid sources_used, forcing fallback",
            file=sys.stderr,
        )
        is_fallback = True

    if not is_fallback:
        for s in _normalize_sections(tool_input.get("sections")):
            yield {
                "event": "section",
                "data": {
                    "title": s.get("title", ""),
                    "body": s.get("body", ""),
                },
            }
            # Разносим секции во времени, чтобы они появлялись по одной,
            # а не «бух всё разом» одним TCP-чанком вслед за последней
            # дельтой лида.
            await asyncio.sleep(0.08)

    sources = _resolve_sources(sources_used, hits)
    yield {
        "event": "done",
        "data": {
            "model": final_message.model,
            "is_fallback": is_fallback,
            "sources_used": sources_used,
            "sources": [s.model_dump() for s in sources],
            "usage": {
                "input_tokens": final_message.usage.input_tokens,
                "output_tokens": final_message.usage.output_tokens,
            },
        },
    }
