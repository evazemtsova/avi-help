import { Sparkles, ExternalLink } from "lucide-react";
import styles from "./FallbackState.module.css";

export default function FallbackState({ query, lead }) {
  return (
    <div className={styles.wrap}>
      <header className={styles.header}>
        <Sparkles size={20} className={styles.spark} aria-hidden="true" />
        <span className={styles.title}>Обзор от ИИ</span>
      </header>
      <p className={styles.lead}>
        {lead ||
          (query
            ? `По запросу «${query}» в справке не нашлось точной статьи. Попробуйте сформулировать вопрос конкретнее или обратитесь в поддержку.`
            : "По вашему запросу не нашлось точной статьи. Попробуйте сформулировать вопрос конкретнее.")}
      </p>
      <div className={styles.tips}>
        <div className={styles.tipsTitle}>Что можно сделать:</div>
        <ul className={styles.list}>
          <li>Укажите категорию объявления или тип услуги.</li>
          <li>Сформулируйте конкретное действие, а не общую тему.</li>
          <li>
            Если вопрос вне Авито — справка не сможет помочь.
          </li>
        </ul>
        <a
          className={styles.supportLink}
          href="https://www.avito.ru/help"
          target="_blank"
          rel="noopener noreferrer"
        >
          <span>Написать в поддержку</span>
          <ExternalLink size={14} aria-hidden="true" />
        </a>
      </div>
    </div>
  );
}
