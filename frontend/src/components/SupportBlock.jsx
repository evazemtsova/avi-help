import styles from "./SupportBlock.module.css";

export default function SupportBlock() {
  return (
    <section className={styles.wrap}>
      <div className={styles.box}>
        <h2 className={styles.title}>Служба поддержки</h2>
        <p className={styles.text}>
          Если вы не нашли решение — напишите в поддержку. Среднее время
          ответа — 15 минут с 8:00 до 24:00 МСК.
        </p>
        <a
          href="https://www.avito.ru/help"
          target="_blank"
          rel="noopener noreferrer"
          className={styles.btn}
        >
          Задать вопрос
        </a>
      </div>
    </section>
  );
}
