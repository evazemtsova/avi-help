import { useEffect, useState } from "react";
import { subscribe } from "../lib/toast";
import styles from "./Toast.module.css";

export default function Toast() {
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    let timer = null;
    const unsub = subscribe((m, d) => {
      setMsg(m);
      clearTimeout(timer);
      timer = setTimeout(() => setMsg(null), d);
    });
    return () => {
      unsub();
      clearTimeout(timer);
    };
  }, []);

  return (
    <div
      className={`${styles.toast} ${msg ? styles.show : ""}`}
      role="status"
      aria-live="polite"
    >
      {msg}
    </div>
  );
}
