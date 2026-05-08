import { ChevronDown } from "lucide-react";
import styles from "./ExpandButton.module.css";

export default function ExpandButton({ expanded, onToggle }) {
  return (
    <button
      type="button"
      className={`${styles.btn} ${expanded ? styles.expanded : ""}`}
      onClick={onToggle}
    >
      <span>{expanded ? "Свернуть" : "Развернуть"}</span>
      <ChevronDown size={16} className={styles.chev} aria-hidden="true" />
    </button>
  );
}
