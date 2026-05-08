import { useMemo, useState } from "react";
import { Sparkles, X } from "lucide-react";
import SourceCluster from "./SourceCluster";
import Section from "./Section";
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

export default function AnswerCard({
  query,
  answer,
  streaming = false,
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
          {renderLeadWithCluster(answer.lead, sources)}
          {streaming && <span className={styles.cursor} aria-hidden="true" />}
        </p>

        {visibleSections.length > 0 && (
          <div
            className={`${styles.sectionsWrap} ${
              isLong && !expanded ? styles.fade : ""
            }`}
          >
            {visibleSections.map((s, i) => (
              <Section key={`${s.title}-${i}`} title={s.title} body={s.body} />
            ))}
          </div>
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
            onToast={showToast}
          />
        )}
      </div>
    </article>
  );
}
