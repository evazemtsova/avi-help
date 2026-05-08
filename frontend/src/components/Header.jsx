import { useEffect, useRef, useState } from "react";
import styles from "./Header.module.css";

function Logo() {
  return (
    <div className={styles.logo}>
      <div className={styles.dots}>
        <span className={`${styles.dot} ${styles.dotGreen}`} />
        <span className={`${styles.dot} ${styles.dotRed}`} />
        <span className={`${styles.dot} ${styles.dotBlue}`} />
        <span className={`${styles.dot} ${styles.dotPurple}`} />
      </div>
      <span className={styles.logoText}>А-Помощь</span>
    </div>
  );
}

export default function Header({ onSubmit, heroSentinelRef }) {
  const [scrolled, setScrolled] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [value, setValue] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const sentinel = heroSentinelRef?.current;
    if (!sentinel) return;
    const obs = new IntersectionObserver(
      ([entry]) => setShowSearch(!entry.isIntersecting),
      { rootMargin: "-80px 0px 0px 0px", threshold: 0 }
    );
    obs.observe(sentinel);
    return () => obs.disconnect();
  }, [heroSentinelRef]);

  function handleSubmit(e) {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    onSubmit?.(q);
  }

  return (
    <header className={`${styles.header} ${scrolled ? styles.scrolled : ""}`}>
      <div className={styles.inner}>
        <Logo />
        <form
          className={`${styles.headerSearch} ${showSearch ? styles.visible : ""}`}
          onSubmit={handleSubmit}
          aria-hidden={!showSearch}
        >
          <input
            ref={inputRef}
            type="text"
            placeholder="Напишите тему, например: деньги за заказ"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            tabIndex={showSearch ? 0 : -1}
            maxLength={200}
          />
          <button type="submit" tabIndex={showSearch ? 0 : -1}>
            Поиск
          </button>
        </form>
        <span className={styles.login}>Вход и регистрация</span>
      </div>
    </header>
  );
}
