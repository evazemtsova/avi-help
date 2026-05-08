import styles from "./Footer.module.css";

export default function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={styles.text}>
        А-Помощь — демонстрационный пет-проект (RAG-поиск по справочному
        центру). © 2026. <a href="#">Условия использования</a>.{" "}
        <a href="#">Политика обработки данных</a>. Сделано с использованием
        Claude.
      </div>
    </footer>
  );
}
