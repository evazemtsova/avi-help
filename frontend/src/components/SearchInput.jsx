import { useState } from "react";
import { useMediaQuery } from "../lib/useMediaQuery";
import styles from "./SearchInput.module.css";

const MAX_LEN = 200;
const PLACEHOLDER_FULL = "Напишите тему, например: деньги за заказ";
const PLACEHOLDER_SHORT = "Например: возврат денег";

export default function SearchInput({ value, onChange, onSubmit, disabled }) {
  // Если value/onChange не контролят снаружи — управляем сами.
  const [inner, setInner] = useState("");
  const isControlled = value !== undefined;
  const v = isControlled ? value : inner;
  const setV = isControlled ? onChange : setInner;

  // На узких экранах placeholder обрывается (Safari не уважает
  // text-overflow: ellipsis в input::placeholder). Показываем короткий.
  const isNarrow = useMediaQuery("(max-width: 480px)");
  const placeholder = isNarrow ? PLACEHOLDER_SHORT : PLACEHOLDER_FULL;

  function handleSubmit(e) {
    e.preventDefault();
    const q = v.trim();
    if (!q || disabled) return;
    onSubmit?.(q);
  }

  return (
    <form className={styles.box} onSubmit={handleSubmit}>
      <input
        type="text"
        className={styles.input}
        placeholder={placeholder}
        value={v}
        onChange={(e) => setV(e.target.value)}
        maxLength={MAX_LEN}
        autoComplete="off"
        aria-label="Поисковый запрос"
        enterKeyHint="search"
      />
      <button
        type="submit"
        className={styles.button}
        disabled={disabled || !v.trim()}
      >
        Поиск
      </button>
    </form>
  );
}
