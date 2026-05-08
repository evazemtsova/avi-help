import { useEffect, useReducer, useRef, useState } from "react";
import Header from "./components/Header";
import Tabs from "./components/Tabs";
import Hero from "./components/Hero";
import AnswerCard from "./components/AnswerCard";
import LoadingState from "./components/LoadingState";
import ErrorState from "./components/ErrorState";
import FallbackState from "./components/FallbackState";
import CategoryGrid from "./components/CategoryGrid";
import SupportBlock from "./components/SupportBlock";
import Footer from "./components/Footer";
import ScrollTopButton from "./components/ScrollTopButton";
import Toast from "./components/Toast";
import SourcePopover from "./components/SourcePopover";
import { getAnswer, streamAnswer, submitFeedback, ApiError } from "./api";
import styles from "./App.module.css";

/**
 * Корневой стейт-менеджер.
 *
 * View-machine через useReducer (state накапливается из SSE-дельт):
 *   idle      — нет ответа, показываем категории
 *   streaming — стрим в процессе (stage: thinking | writing)
 *   answer    — финальный ответ
 *   fallback  — is_fallback=true с пустыми sources
 *   error     — ошибка сети/HTTP/таймаут/503
 *
 * VITE_USE_SYNC=1 → отладочный режим через /answer/sync (без стрима).
 * По умолчанию используется streaming.
 */

const USE_SYNC = import.meta.env.VITE_USE_SYNC === "1";

const initialState = { kind: "idle" };

function reducer(state, action) {
  switch (action.type) {
    case "START":
      return {
        kind: "streaming",
        stage: "thinking",
        lead: "",
        leadChunks: [],
        sections: [],
        sources: [],
        is_fallback: false,
        request_id: null,
        query: action.query,
      };
    case "META":
      if (state.kind !== "streaming") return state;
      return {
        ...state,
        stage: "writing",
        sources: action.sources,
        is_fallback: action.is_fallback,
        // request_id приходит в первом meta-событии — кладём в state, чтобы
        // FeedbackButtons мог пробросить его в /feedback.
        request_id: action.request_id ?? state.request_id,
      };
    case "LEAD_DELTA":
      if (state.kind !== "streaming") return state;
      return {
        ...state,
        lead: state.lead + action.text,
        leadChunks: [...state.leadChunks, action.text],
      };
    case "SECTION":
      if (state.kind !== "streaming") return state;
      return {
        ...state,
        sections: [...state.sections, { title: action.title, body: action.body }],
      };
    case "DONE": {
      if (state.kind !== "streaming") return state;
      // На done бэк присылает финальные sources (после валидации); если их
      // нет, оставляем те, что пришли в meta.
      const finalSources =
        action.sources && action.sources.length ? action.sources : state.sources;
      const data = {
        lead: state.lead,
        sections: state.sections,
        sources: finalSources,
        sources_used: action.sources_used || [],
        is_fallback: action.is_fallback,
        usage: action.usage,
        model: action.model,
        request_id: state.request_id,
      };
      if (action.is_fallback && (!finalSources || finalSources.length === 0)) {
        return { kind: "fallback", data, query: state.query };
      }
      return { kind: "answer", data, query: state.query };
    }
    case "SYNC_OK": {
      // Режим VITE_USE_SYNC: один результат вместо стрима.
      const { data, query } = action;
      if (data.is_fallback && (!data.sources || data.sources.length === 0)) {
        return { kind: "fallback", data, query };
      }
      return { kind: "answer", data, query };
    }
    case "ERROR":
      return {
        kind: "error",
        type: action.errType || "unknown",
        message: action.message || "",
        query: action.query,
      };
    case "CLOSE":
      return { kind: "idle" };
    default:
      return state;
  }
}

export default function App() {
  const [view, dispatch] = useReducer(reducer, initialState);
  // query поля ввода контролится отдельно — не зависит от view, чтобы при
  // отмене/ошибке инпут не очищался.
  const [query, setQuery] = useState("");
  const heroSentinelRef = useRef(null);
  const lastQueryRef = useRef("");
  // AbortController текущего стрима. При новом запросе — abort предыдущего.
  const streamCtrlRef = useRef(null);

  useEffect(() => {
    // Cancel при unmount
    return () => streamCtrlRef.current?.abort();
  }, []);

  async function pickAndShow(q) {
    const trimmed = q?.trim();
    if (!trimmed) return;
    // Двойной сабмит: если уже стримится тот же запрос — ничего не делаем.
    if (
      view.kind === "streaming" &&
      view.query === trimmed &&
      streamCtrlRef.current
    )
      return;

    // Cancel предыдущего стрима если был
    if (streamCtrlRef.current) {
      streamCtrlRef.current.abort();
      streamCtrlRef.current = null;
    }

    setQuery(trimmed);
    lastQueryRef.current = trimmed;
    dispatch({ type: "START", query: trimmed });

    if (USE_SYNC) {
      try {
        const data = await getAnswer(trimmed);
        dispatch({ type: "SYNC_OK", data, query: trimmed });
      } catch (err) {
        if (err instanceof ApiError && err.type === "abort") return;
        dispatch({
          type: "ERROR",
          errType: err?.type || "unknown",
          message: err?.message || String(err),
          query: trimmed,
        });
      }
      return;
    }

    const ctrl = new AbortController();
    streamCtrlRef.current = ctrl;

    await streamAnswer(trimmed, {
      signal: ctrl.signal,
      onMeta: ({ sources, is_fallback, request_id }) =>
        dispatch({ type: "META", sources, is_fallback, request_id }),
      onLeadDelta: ({ text }) => dispatch({ type: "LEAD_DELTA", text }),
      onSection: ({ title, body }) =>
        dispatch({ type: "SECTION", title, body }),
      onDone: (payload) => {
        if (streamCtrlRef.current === ctrl) streamCtrlRef.current = null;
        dispatch({ type: "DONE", ...payload });
      },
      onError: (err) => {
        if (streamCtrlRef.current === ctrl) streamCtrlRef.current = null;
        if (err?.type === "abort") return;
        dispatch({
          type: "ERROR",
          errType: err?.type || "unknown",
          message: err?.message || String(err),
          query: trimmed,
        });
      },
    });
  }

  function handleClose() {
    if (streamCtrlRef.current) {
      streamCtrlRef.current.abort();
      streamCtrlRef.current = null;
    }
    dispatch({ type: "CLOSE" });
  }

  function handleRetry() {
    pickAndShow(lastQueryRef.current || query);
  }

  /**
   * Колбэк FeedbackButtons. Собирает payload из текущего answer state,
   * шлёт в /feedback. Не ждёт результат — UI уже переключился в
   * «отправлено». Бэк-stub печатает в stderr; в Спринте 4 будет JSONL.
   */
  function handleRate(rating) {
    if (view.kind !== "answer" || !view.data) return;
    const a = view.data;
    const sectionsText = (a.sections || [])
      .map((s) => `${s.title}\n${s.body || ""}`)
      .join("\n\n");
    const answer_text = `${a.lead || ""}\n\n${sectionsText}`.trim();
    submitFeedback({
      request_id: a.request_id || null,
      query: view.query,
      answer_text,
      sources_used: a.sources_used || [],
      rating,
    });
  }

  const isLoading =
    view.kind === "streaming" && (view.lead === "" || view.stage === "thinking");

  return (
    <>
      <Header onSubmit={pickAndShow} heroSentinelRef={heroSentinelRef} />
      <main className={styles.main}>
        <Tabs />
        <Hero
          ref={heroSentinelRef}
          query={query}
          onQueryChange={setQuery}
          onSubmit={pickAndShow}
          disabled={view.kind === "streaming"}
        />

        {isLoading && <LoadingState stage={view.stage || "thinking"} />}

        {/*
          Один AnswerCard поверх streaming → answer. React видит только
          смену пропсов, не размонтирует узел — CSS `appear` срабатывает
          один раз при первом появлении карточки, дальше inplace-апдейт.
          Без этого на DONE карточка визуально перерисовывалась с нуля
          («обновление прошло») и секции вылетали разом.
        */}
        {((view.kind === "streaming" && view.lead !== "") ||
          view.kind === "answer") && (
          <AnswerCard
            query={view.query}
            answer={
              view.kind === "answer"
                ? view.data
                : {
                    lead: view.lead,
                    sections: view.sections,
                    sources: view.sources,
                    sources_used: [],
                    is_fallback: view.is_fallback,
                  }
            }
            leadChunks={view.kind === "streaming" ? view.leadChunks : null}
            streaming={view.kind === "streaming"}
            onRate={handleRate}
            onClose={handleClose}
          />
        )}

        {view.kind === "fallback" && (
          <FallbackState query={view.query} lead={view.data?.lead} />
        )}

        {view.kind === "error" && (
          <ErrorState
            type={view.type}
            message={view.message}
            onRetry={handleRetry}
          />
        )}

        <CategoryGrid onPick={pickAndShow} />
        <SupportBlock />
        <Footer />
      </main>

      <ScrollTopButton />
      <Toast />
      <SourcePopover />
    </>
  );
}
