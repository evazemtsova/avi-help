import Markdown from "react-markdown";
import styles from "./Section.module.css";

/**
 * Секция ответа: заголовок + markdown body. react-markdown по умолчанию
 * не пропускает raw HTML — это та защита, что нам нужна. Добавляем
 * минимальный маппинг тегов на свои стили + ссылки в новой вкладке.
 */
const components = {
  p: ({ children }) => <p className={styles.para}>{children}</p>,
  ul: ({ children }) => <ul className={styles.list}>{children}</ul>,
  ol: ({ children }) => <ol className={`${styles.list} ${styles.ordered}`}>{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong>{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className={styles.link}>
      {children}
    </a>
  ),
  // h1-h3 внутри section.body не ожидаются (структура у нас — sections),
  // но на всякий случай рендерим как жирный параграф вместо хедера.
  h1: ({ children }) => <p className={styles.para}><strong>{children}</strong></p>,
  h2: ({ children }) => <p className={styles.para}><strong>{children}</strong></p>,
  h3: ({ children }) => <p className={styles.para}><strong>{children}</strong></p>,
  code: ({ children }) => <code className={styles.code}>{children}</code>,
};

// Sprint 5 Block 5 follow-up: модель иногда отдаёт '•' (или копирует из чанка
// с U+2022/U+00B7/U+25CF/U+2219) — react-markdown НЕ парсит как list-item,
// строки схлопываются в один <p>. Нормализуем в '- ' до рендера.
function normalizeBullets(text) {
  if (!text) return text;
  return text.replace(/^[\s]*[•·●∙]\s+/gm, "- ");
}

export default function Section({ title, body }) {
  const normalized = normalizeBullets(body);
  return (
    <section className={styles.section}>
      <h3 className={styles.title}>{title}</h3>
      {normalized && <Markdown components={components}>{normalized}</Markdown>}
    </section>
  );
}
