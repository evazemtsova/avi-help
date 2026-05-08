/**
 * API-клиент. В блоке 2 используется только getAnswer через /answer/sync.
 * SSE-стрим (/answer) подключим в блоке 3.
 *
 * Бэк: https://avi-help-production.up.railway.app/
 * Локально: http://localhost:8000
 *
 * Формат ответа /answer/sync:
 *   {
 *     query: str,
 *     answer: {
 *       lead, sections[], sources_used[], sources[], is_fallback,
 *       model, usage: { input_tokens, output_tokens }
 *     },
 *     retrieval_scores: float[],
 *     latency_ms: { retrieval, generation, total }
 *   }
 *
 * Внутренняя форма для UI (см. components/AnswerCard.jsx):
 *   { lead, sections[], sources[{ article_id, title, url, category, section, lastmod }],
 *     sources_used[], is_fallback, usage, model, latency_ms }
 */

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

const TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  constructor(message, { type = "unknown", status = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.type = type;
    this.status = status;
  }
}

export function getApiBase() {
  return API_BASE;
}

function normalizeSource(s) {
  return {
    article_id: s.article_id,
    title: s.title,
    url: s.article_url,
    category: s.category,
    section: s.section ?? null,
    lastmod: s.lastmod ?? null,
  };
}

function normalizeAnswer(data) {
  const a = data?.answer || {};
  return {
    lead: a.lead || "",
    sections: Array.isArray(a.sections) ? a.sections : [],
    sources: Array.isArray(a.sources) ? a.sources.map(normalizeSource) : [],
    sources_used: Array.isArray(a.sources_used) ? a.sources_used : [],
    is_fallback: Boolean(a.is_fallback),
    usage: a.usage || null,
    model: a.model || null,
    latency_ms: data?.latency_ms || null,
  };
}

/**
 * Запрос к /answer/sync. Опции:
 *   signal — внешний AbortSignal (используется блоком 3 для cancel)
 *   top_k  — top-K для retrieval, по умолчанию серверный
 */
export async function getAnswer(query, { signal, top_k } = {}) {
  const ctrl = new AbortController();
  const timeoutId = setTimeout(() => ctrl.abort("timeout"), TIMEOUT_MS);

  if (signal) {
    if (signal.aborted) ctrl.abort(signal.reason);
    else
      signal.addEventListener("abort", () => ctrl.abort(signal.reason), {
        once: true,
      });
  }

  const body = { query };
  if (typeof top_k === "number") body.top_k = top_k;

  let res;
  try {
    res = await fetch(`${API_BASE}/answer/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err?.name === "AbortError") {
      // Различаем internal timeout vs внешний cancel
      const reason = ctrl.signal.reason;
      if (reason === "timeout") {
        throw new ApiError(
          "Превышено время ожидания (30 секунд). Попробуйте ещё раз.",
          { type: "timeout" }
        );
      }
      throw new ApiError("Запрос отменён", { type: "abort" });
    }
    throw new ApiError(
      "Не удалось связаться с сервисом. Проверьте интернет.",
      { type: "network" }
    );
  }

  clearTimeout(timeoutId);

  if (!res.ok) {
    let detail = null;
    try {
      const json = await res.json();
      detail = json?.detail || null;
    } catch {
      /* ignore parse errors */
    }
    if (res.status === 503) {
      throw new ApiError(
        "Сервис прогревается, попробуйте через минуту.",
        { type: "warming", status: 503 }
      );
    }
    throw new ApiError(detail || `Сервис ответил ошибкой ${res.status}`, {
      type: "http",
      status: res.status,
    });
  }

  let data;
  try {
    data = await res.json();
  } catch {
    throw new ApiError("Сервис вернул некорректный ответ", { type: "parse" });
  }

  return normalizeAnswer(data);
}

/* ============================================================
 * SSE-стрим /answer
 *
 * EventSource не подходит — он только GET без body. Поэтому мы
 * используем fetch + ReadableStream + ручной парсинг SSE-формата.
 *
 * Колбэки (всё опционально, но обычно нужны все):
 *   onMeta({ sources, is_fallback })
 *   onLeadDelta({ text })       // инкрементальные дельты лида
 *   onSection({ title, body })  // целиком после закрытия tool_use массива
 *   onDone({ sources, sources_used, is_fallback, usage, model })
 *   onError(ApiError)           // фатально — стрим закрыт
 *
 * Опции:
 *   signal — внешний AbortSignal (App вызывает abort() при новом запросе)
 *   top_k  — top-K для retrieval, по умолчанию серверный
 *
 * Резолв promise = «стрим закрыт нормально или ошибкой». Колбэки уже
 * сделали свою работу — App не разбирает ответ из return value.
 * ============================================================ */

function parseSseBlock(block) {
  let event = "message";
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // SSE comment
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      // SSE: пробел после двоеточия опционален
      dataLines.push(line.slice(5).replace(/^\s/, ""));
    }
  }
  if (dataLines.length === 0) return null;
  let data;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }
  return { event, data };
}

function dispatchEvent({ event, data }, cb) {
  switch (event) {
    case "meta":
      cb.onMeta?.({
        sources: Array.isArray(data?.sources)
          ? data.sources.map(normalizeSource)
          : [],
        is_fallback: Boolean(data?.is_fallback),
      });
      break;
    case "lead_delta":
      if (typeof data?.text === "string" && data.text.length > 0) {
        cb.onLeadDelta?.({ text: data.text });
      }
      break;
    case "section":
      cb.onSection?.({
        title: data?.title || "",
        body: data?.body || "",
      });
      break;
    case "done":
      cb.onDone?.({
        sources: Array.isArray(data?.sources)
          ? data.sources.map(normalizeSource)
          : [],
        sources_used: Array.isArray(data?.sources_used)
          ? data.sources_used
          : [],
        is_fallback: Boolean(data?.is_fallback),
        usage: data?.usage || null,
        model: data?.model || null,
      });
      break;
    default:
      // unknown event — игнорируем
      break;
  }
}

export async function streamAnswer(query, callbacks = {}) {
  const { signal, top_k, onError } = callbacks;

  const ctrl = new AbortController();
  if (signal) {
    if (signal.aborted) ctrl.abort(signal.reason);
    else
      signal.addEventListener("abort", () => ctrl.abort(signal.reason), {
        once: true,
      });
  }

  const body = { query };
  if (typeof top_k === "number") body.top_k = top_k;

  let res;
  try {
    res = await fetch(`${API_BASE}/answer`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") {
      onError?.(new ApiError("Запрос отменён", { type: "abort" }));
      return;
    }
    onError?.(
      new ApiError("Не удалось связаться с сервисом. Проверьте интернет.", {
        type: "network",
      })
    );
    return;
  }

  if (!res.ok) {
    let detail = null;
    try {
      const json = await res.json();
      detail = json?.detail || null;
    } catch {
      /* ignore */
    }
    if (res.status === 503) {
      onError?.(
        new ApiError("Сервис прогревается, попробуйте через минуту.", {
          type: "warming",
          status: 503,
        })
      );
    } else {
      onError?.(
        new ApiError(detail || `Сервис ответил ошибкой ${res.status}`, {
          type: "http",
          status: res.status,
        })
      );
    }
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    onError?.(
      new ApiError("Браузер не поддерживает streaming response", {
        type: "parse",
      })
    );
    return;
  }

  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    // Читаем поток до его естественного завершения. Каждый chunk дописываем
    // в buffer, режем по двойному \n\n (граница SSE-события), парсим и
    // вызываем колбэк.
    // Safari mobile fix: бэк уже шлёт `X-Accel-Buffering: no` + первое
    // событие meta ~300 байт; этого хватает чтобы Safari не накапливал
    // chunks. Если когда-то начнёт буферизовать — на бэке добавим padding
    // комментарием в первое событие; здесь со стороны фронта обходов нет.
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Нормализуем CRLF → LF: бэк шлёт LF, но прокси иногда добавляют CR.
      let sep;
      while (
        (sep = findSseBoundary(buffer)) !== -1
      ) {
        const block = buffer.slice(0, sep);
        // длина разделителя: \n\n = 2, \r\n\r\n = 4
        const len = buffer.startsWith("\r\n\r\n", sep) ? 4 : 2;
        buffer = buffer.slice(sep + len);
        const ev = parseSseBlock(block);
        if (ev) dispatchEvent(ev, callbacks);
      }
    }
    // Финальный flush — на случай если последний event без trailing \n\n
    const tail = buffer.trim();
    if (tail) {
      const ev = parseSseBlock(tail);
      if (ev) dispatchEvent(ev, callbacks);
    }
  } catch (err) {
    if (err?.name === "AbortError" || ctrl.signal.aborted) {
      onError?.(new ApiError("Запрос отменён", { type: "abort" }));
      return;
    }
    onError?.(
      new ApiError("Соединение прервано во время стрима.", {
        type: "network",
      })
    );
  }
}

function findSseBoundary(s) {
  // Возвращает индекс начала разделителя (\n\n или \r\n\r\n), или -1.
  const lf = s.indexOf("\n\n");
  const crlf = s.indexOf("\r\n\r\n");
  if (lf === -1) return crlf;
  if (crlf === -1) return lf;
  return Math.min(lf, crlf);
}
