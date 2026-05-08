import { useEffect, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, Paperclip, X } from "lucide-react";
import { closeCluster, useActiveCluster } from "../lib/sourcePopover";
import { formatLastmod } from "../utils/date";
import styles from "./SourcePopover.module.css";

/**
 * Глобальный поповер кластера источников. Каждый item — прямая ссылка
 * на support.avito.ru, открывается в новой вкладке. Поповер закрывается
 * на: клик-вне / Escape / scroll / resize / повторный клик на кластер.
 *
 * Бейджи у всех ссылок одинаковые (серый кружок со скрепкой), без
 * привязки к категории — единообразный визуал, как у внешних ссылок
 * во многих UI-системах.
 */

export default function SourcePopover() {
  const state = useActiveCluster();
  const popRef = useRef(null);

  useLayoutEffect(() => {
    const el = popRef.current;
    if (!el || !state?.anchorRect) return;
    const pop = el.getBoundingClientRect();
    const a = state.anchorRect;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const margin = 8;
    let top = a.bottom + 6;
    let left = a.left;
    if (left + pop.width > vw - margin) left = vw - pop.width - margin;
    if (left < margin) left = margin;
    if (top + pop.height > vh - margin) {
      top = Math.max(margin, a.top - pop.height - 6);
    }
    el.style.top = `${top}px`;
    el.style.left = `${left}px`;
    el.style.visibility = "visible";
  }, [state]);

  useEffect(() => {
    if (!state) return;
    const onKey = (e) => {
      if (e.key === "Escape") closeCluster();
    };
    const onPointerDown = (e) => {
      if (popRef.current?.contains(e.target)) return;
      if (e.target.closest?.("[data-source-marker]")) return;
      closeCluster();
    };
    const onScroll = () => closeCluster();
    const onResize = () => closeCluster();

    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
    };
  }, [state]);

  if (!state) return null;

  return createPortal(
    <div
      key={state.clusterId}
      ref={popRef}
      className={styles.popover}
      role="dialog"
      aria-label="Источники"
      style={{ top: -9999, left: -9999, visibility: "hidden" }}
    >
      <div className={styles.head}>
        <span className={styles.domain}>support.avito.ru</span>
        <button
          type="button"
          className={styles.close}
          onClick={closeCluster}
          aria-label="Закрыть"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>
      <ul className={styles.list}>
        {state.sources.map((s) => {
          const lastmodLabel = formatLastmod(s.lastmod);
          return (
            <li key={s.article_id}>
              <a
                className={styles.item}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className={styles.badge}>
                  <Paperclip size={14} aria-hidden="true" />
                </span>
                <span className={styles.text}>
                  <span className={styles.title}>{s.title}</span>
                  <span className={styles.meta}>
                    <span>{s.category || "Помощь"}</span>
                    {lastmodLabel && (
                      <>
                        <span className={styles.sep}>·</span>
                        <span>{lastmodLabel}</span>
                      </>
                    )}
                  </span>
                </span>
                <ExternalLink
                  size={14}
                  className={styles.icon}
                  aria-hidden="true"
                />
              </a>
            </li>
          );
        })}
      </ul>
    </div>,
    document.body
  );
}
