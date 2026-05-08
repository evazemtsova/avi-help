import { useRef } from "react";
import {
  openCluster,
  closeCluster,
  useIsClusterActive,
} from "../lib/sourcePopover";
import styles from "./SourceCluster.module.css";

/**
 * Inline-кластер источников — одна пилюля: бейдж + название первого
 * источника + «+N» если их больше.  Клик открывает SourcePopover со
 * списком всех ссылок кластера.
 *
 * Дизайн по референсу Google AI Overview: ссылки не дублируются (нет
 * отдельной полоски под лидом), вся группа источников живёт ровно
 * там, где привязана к тексту.
 */

const PALETTE = [
  "#00aaff",
  "#4da6ff",
  "#a855f7",
  "#00d747",
  "#ff6163",
  "#f59e0b",
];

function colorFor(source) {
  const key = source?.category || source?.title || "?";
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}

function letterFor(source) {
  const key = source?.category || source?.title || "?";
  return key.slice(0, 1).toUpperCase();
}

function clusterIdFor(sources) {
  return sources.map((s) => s.article_id).join(",");
}

function rectToPlain(r) {
  return {
    top: r.top,
    left: r.left,
    right: r.right,
    bottom: r.bottom,
    width: r.width,
    height: r.height,
  };
}

export default function SourceCluster({ sources }) {
  const ref = useRef(null);
  const id = sources && sources.length ? clusterIdFor(sources) : null;
  const isActive = useIsClusterActive(id);

  if (!sources || sources.length === 0) return null;

  const first = sources[0];
  const extra = sources.length - 1;

  function handleClick(e) {
    e.preventDefault();
    if (isActive) {
      closeCluster();
      return;
    }
    const rect = ref.current?.getBoundingClientRect();
    openCluster(id, sources, rect ? rectToPlain(rect) : null);
  }

  return (
    <button
      ref={ref}
      type="button"
      data-source-marker
      className={`${styles.cluster} ${isActive ? styles.active : ""}`}
      onClick={handleClick}
      aria-haspopup="dialog"
      aria-expanded={isActive}
      aria-label={
        sources.length === 1
          ? `Источник: ${first.title}`
          : `${sources.length} источника по теме, первый: ${first.title}`
      }
    >
      <span className={styles.badge} style={{ background: colorFor(first) }}>
        {letterFor(first)}
      </span>
      <span className={styles.title}>{first.title}</span>
      {extra > 0 && <span className={styles.plus}>+{extra}</span>}
    </button>
  );
}
