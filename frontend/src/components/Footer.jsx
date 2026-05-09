import styles from "./Footer.module.css";

export default function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={styles.text}>
        А-Помощь — демонстрационный пет-проект (RAG-поиск по справочному
        центру Авито Службы Поддержки). 2026
      </div>
    </footer>
  );
}
