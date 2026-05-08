import styles from "./SectionsSkeleton.module.css";

/**
 * Плейсхолдер на месте секций пока стрим идёт, а сами секции ещё не пришли.
 * Между последней lead_delta и первой section Anthropic делает паузу ~1.7с,
 * skeleton светится в это окно, дальше плавно подменяется реальными секциями.
 *
 * Паттерн взят с Google AI Overview: пользователь видит, что «там что-то будет»,
 * вместо пустоты или сухого спиннера.
 */
export default function SectionsSkeleton() {
  return (
    <div className={styles.skeleton} aria-hidden="true">
      <div className={styles.bar} style={{ width: "92%" }} />
      <div className={styles.bar} style={{ width: "84%" }} />
      <div className={styles.bar} style={{ width: "75%" }} />
      <div className={styles.bar} style={{ width: "68%" }} />
    </div>
  );
}
