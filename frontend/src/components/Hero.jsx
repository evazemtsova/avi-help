import { forwardRef } from "react";
import SearchInput from "./SearchInput";
import styles from "./Hero.module.css";

const Hero = forwardRef(function Hero(
  { query, onQueryChange, onSubmit, disabled },
  sentinelRef
) {
  return (
    <section className={styles.hero}>
      <h1 className={styles.title}>
        Ответы на популярные вопросы по работе А-Помощи
      </h1>
      <div className={styles.searchWrap} ref={sentinelRef}>
        <SearchInput
          value={query}
          onChange={onQueryChange}
          onSubmit={onSubmit}
          disabled={disabled}
        />
      </div>
    </section>
  );
});

export default Hero;
