import { useState } from "react";
import { ThumbsUp, ThumbsDown, Share2 } from "lucide-react";
import styles from "./FeedbackButtons.module.css";

/**
 * Состояния:
 *   rated = null    — ничего не нажато
 *   rated = "up"    — нажат лайк
 *   rated = "down"  — нажат дизлайк
 * После выбора кнопки disable обе (отправлено).
 *
 * onRate(rating)  — внешний обработчик (POST /feedback в блоке 4).
 * onShare()       — обработчик share (по умолчанию использует Web Share API
 *                   или копирует в буфер).
 * onToast(msg)    — показать toast снаружи; если не задан — внутренней
 *                   логики не делаем.
 */
export default function FeedbackButtons({
  query,
  bodyText,
  onRate,
  onToast,
}) {
  const [rated, setRated] = useState(null);

  function handleRate(rating) {
    if (rated) return;
    setRated(rating);
    onRate?.(rating);
    onToast?.(rating === "up" ? "Спасибо за оценку!" : "Спасибо, мы учтём это");
  }

  function handleShare() {
    const text = bodyText || "";
    const title = query ? `А-Помощь: ${query}` : "А-Помощь";
    if (navigator.share) {
      navigator.share({ title, text }).catch(() => {});
      return;
    }
    if (navigator.clipboard && text) {
      navigator.clipboard.writeText(text).then(
        () => onToast?.("Ответ скопирован"),
        () => {}
      );
    }
  }

  return (
    <div className={styles.feedback}>
      <button
        type="button"
        className={`${styles.btn} ${rated === "up" ? styles.active : ""}`}
        onClick={() => handleRate("up")}
        disabled={rated !== null}
        aria-label="Полезно"
      >
        <ThumbsUp size={18} strokeWidth={2} />
      </button>
      <button
        type="button"
        className={`${styles.btn} ${rated === "down" ? styles.active : ""}`}
        onClick={() => handleRate("down")}
        disabled={rated !== null}
        aria-label="Не помогло"
      >
        <ThumbsDown size={18} strokeWidth={2} />
      </button>
      <button
        type="button"
        className={styles.btn}
        onClick={handleShare}
        aria-label="Поделиться"
      >
        <Share2 size={18} strokeWidth={2} />
      </button>
    </div>
  );
}
