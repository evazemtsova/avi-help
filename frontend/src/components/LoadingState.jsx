import { Sparkles } from "lucide-react";
import styles from "./LoadingState.module.css";

export default function LoadingState({ stage = "thinking" }) {
  // stage: "thinking" — до прихода первой meta из стрима;
  //        "writing"  — пилюли уже видны, ждём lead.
  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <Sparkles size={20} className={styles.spark} aria-hidden="true" />
        <span className={styles.title}>Обзор от ИИ</span>
      </div>
      <div className={styles.dots} aria-live="polite">
        <span>{stage === "thinking" ? "Ищу источники" : "Готовлю ответ"}</span>
        <span className={styles.dot} />
        <span className={styles.dot} />
        <span className={styles.dot} />
      </div>
    </div>
  );
}
