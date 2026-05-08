import { AlertCircle, RefreshCw, Loader } from "lucide-react";
import styles from "./ErrorState.module.css";

/**
 * Состояния ошибки:
 *   type="warming" — 503 от Railway (Chroma не готова), мягкий тон
 *   type="timeout" — таймаут 30с, retry рекомендуется
 *   остальные      — обычная ошибка сети/HTTP
 */
const TITLES = {
  warming: "Сервис прогревается",
  timeout: "Запрос занял слишком долго",
  network: "Не удалось связаться с сервисом",
  http: "Сервис ответил ошибкой",
  parse: "Сервис вернул некорректный ответ",
  unknown: "Не получилось получить ответ",
};

export default function ErrorState({ type = "unknown", message, onRetry }) {
  const isWarming = type === "warming";
  const title = TITLES[type] || TITLES.unknown;
  const Icon = isWarming ? Loader : AlertCircle;

  return (
    <div
      className={`${styles.wrap} ${isWarming ? styles.warming : ""}`}
      role="alert"
    >
      <div className={styles.icon}>
        <Icon size={20} aria-hidden="true" />
      </div>
      <div className={styles.body}>
        <div className={styles.title}>{title}</div>
        <div className={styles.message}>
          {message ||
            (isWarming
              ? "Бэкенд только что разогрелся после простоя. Попробуйте ещё раз через минуту."
              : "Проверьте соединение и попробуйте ещё раз.")}
        </div>
        {onRetry && (
          <button type="button" className={styles.retry} onClick={onRetry}>
            <RefreshCw size={14} aria-hidden="true" />
            <span>Попробовать снова</span>
          </button>
        )}
      </div>
    </div>
  );
}
