import { useState } from "react";
import styles from "./Tabs.module.css";

const TABS = ["Пользователям", "Для бизнеса", "Путешествия"];

export default function Tabs() {
  const [active, setActive] = useState(0);
  return (
    <div className={styles.container}>
      <div className={styles.tabs} role="tablist">
        {TABS.map((label, i) => (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={active === i}
            className={`${styles.tab} ${active === i ? styles.active : ""}`}
            onClick={() => setActive(i)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
