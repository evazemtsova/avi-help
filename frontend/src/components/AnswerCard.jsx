import { useMemo, useState } from "react";
import { Sparkles, X } from "lucide-react";
import SourceCluster from "./SourceCluster";
import Section from "./Section";
import SectionsSkeleton from "./SectionsSkeleton";
import ExpandButton from "./ExpandButton";
import FeedbackButtons from "./FeedbackButtons";
import { showToast } from "../lib/toast";
import styles from "./AnswerCard.module.css";

/**
 * answer = { lead, sections[], sources[], sources_used[], is_fallback }
 *
 * Длинный ответ (estimateLength > LONG_THRESHOLD) рендерится с fade-обрезкой
 * и кнопкой «Развернуть».
 *
 * Источники — один inline-кластер после первого предложения лида (как в
 * Google AI Overview): пилюля «<категория>: <название> +N», клик
 * открывает SourcePopover со списком всех ссылок. Полоски пилюль под
 * лидом нет — иначе ссылки дублируются.
 *
 * `streaming` — для блока 3: добавит мигающий курсор в конец лида.
 */
const LONG_THRESHOLD = 600;

function renderInline(text) {
  if (!text) return null;
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return <strong key={i}>{p.slice(2, -2)}</strong>;
    }
    return <span key={i}>{p}</span>;
  });
}

/**
 * Вставляет один inline-кластер источников после первого предложения лида.
 * В блоке 1 один кластер на весь lead — pretty-print до прихода
 * per-sentence привязки от LLM (Спринт 5).
 */
function renderLeadWithCluster(text, sources) {
  if (!text) return null;
  if (!sources || sources.length === 0) return renderInline(text);

  const match = text.match(/[.!?](\s|$)/);
  const splitAt = match ? match.index + 1 : text.length;
  const before = text.slice(0, splitAt);
  const after = text.slice(splitAt);

  return (
    <>
      {renderInline(before)}
      <SourceCluster sources={sources} />
      {after && renderInline(after)}
    </>
  );
}

/**
 * Рендер лида во время стрима — каждый delta-chunk это отдельный <span>,
 * к которому при mount применяется CSS-анимация blur+opacity. Эффект
 * «текст приходит в фокус» вместо «появился кусок мгновенно».
 *
 * Bold-разметка (**...**) во время стрима не парсится — крайне редко
 * встречается в лидах справочного контента; после done renderInline
 * отрабатывает как обычно.
 */
function renderStreamingChunks(chunks) {
  if (!chunks || chunks.length === 0) return null;
  return chunks.map((c, i) => (
    <span key={i} className={styles.chunk}>
      {c}
    </span>
  ));
}

export default function AnswerCard({
  query,
  answer,
  leadChunks = null,
  streaming = false,
  onRate,
  onClose,
}) {
  const [expanded, setExpanded] = useState(false);

  const sections = useMemo(() => answer?.sections || [], [answer]);
  const sources = useMemo(() => answer?.sources || [], [answer]);

  const totalLength = useMemo(() => {
    if (!answer) return 0;
    let n = (answer.lead || "").length;
    sections.forEach((s) => {
      n += (s.title || "").length + (s.body || "").length;
    });
    return n;
  }, [answer, sections]);

  // Во время стрима не сворачиваем хвост: иначе при пересечении порога
  // (лид + первая секция > 600 знаков) визуально «прыгает» fade + expand
  // button. После done isLong кнопка появится, но карточка уже на экране.
  const isLong = !streaming && totalLength > LONG_THRESHOLD;

  const visibleSections = isLong && !expanded ? sections.slice(0, 1) : sections;
  const hiddenSections = isLong && !expanded ? sections.slice(1) : [];

  const bodyTextForShare = useMemo(() => {
    if (!answer) return "";
    const sectionsText = sections
      .map((s) => `${s.title}\n${s.body || ""}`)
      .join("\n\n");
    return `${answer.lead}\n\n${sectionsText}`.replace(/\*\*/g, "");
  }, [answer, sections]);

  if (!answer) return null;

  return (
    <article className={styles.card}>
      <header className={styles.cardHeader}>
        <div className={styles.headerLeft}>
          <Sparkles size={20} className={styles.spark} aria-hidden="true" />
          <span className={styles.title}>Обзор от ИИ</span>
        </div>
        {onClose && (
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Закрыть"
          >
            <X size={16} strokeWidth={2.5} />
          </button>
        )}
      </header>

      <div className={styles.body}>
        <p className={styles.lead}>
          {streaming
            ? renderStreamingChunks(leadChunks)
            : renderLeadWithCluster(answer.lead, sources)}
          {streaming && answer.lead && (
            <span className={styles.cursor} aria-hidden="true">
              ▍
            </span>
          )}
        </p>

        {streaming && sections.length === 0 ? (
          <SectionsSkeleton />
        ) : (
          visibleSections.length > 0 && (
            <div
              className={`${styles.sectionsWrap} ${
                isLong && !expanded ? styles.fade : ""
              }`}
            >
              {visibleSections.map((s, i) => (
                <Section
                  key={`${s.title}-${i}`}
                  title={s.title}
                  body={s.body}
                />
              ))}
            </div>
          )
        )}

        {isLong && (
          <ExpandButton
            expanded={expanded}
            onToggle={() => setExpanded((v) => !v)}
          />
        )}

        {expanded &&
          hiddenSections.map((s, i) => (
            <Section
              key={`hidden-${s.title}-${i}`}
              title={s.title}
              body={s.body}
            />
          ))}

        {!streaming && (
          <FeedbackButtons
            query={query}
            bodyText={bodyTextForShare}
            onRate={onRate}
            onToast={showToast}
          />
        )}
      </div>
    </article>
  );
}
